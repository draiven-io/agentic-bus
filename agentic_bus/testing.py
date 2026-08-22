"""Test your agent without a coordinator, an LLM, or a network.

Running an agent normally needs a coordinator, which needs a database, a web
framework and a model provider. That is a lot of moving parts to stand up in
order to answer "does my agent return the right thing" — enough that most
people skip writing the test.

:class:`LocalBus` is a stand-in coordinator that speaks the Liquid Interfaces
Protocol over a real WebSocket on localhost::

    import pytest
    from agentic_bus.testing import LocalBus

    async def test_forecast():
        async with LocalBus() as bus:
            agent = await bus.add_agent(WeatherAgent(agent_id="weather-01"))

            result = await bus.execute(agent.agent_id, {"city": "Lisbon"})

            assert result.status == "success"
            assert result.artifacts[0]["forecast"] == "sunny"

It uses a real socket rather than calling handlers directly, deliberately: the
agent's serialisation, its receive loop and its concurrency all take part, so
the test exercises the code that actually runs in production. Faking those out
is what lets connection-level bugs survive a green test suite.

Everything here works on the base install — no ``[server]`` extra — because
an agent author should not have to install a coordinator to test an agent.

What this is not
----------------
Not a coordinator. Discovery, negotiation and plan composition are
LLM-driven in the real runtime and are not reproduced; :class:`LocalBus`
drives the lifecycle explicitly instead, so tests stay deterministic. Use it
to check what your agent *does*, not to check how a coordinator would choose
it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable

import websockets

from agentic_bus.core.protocol.envelope import (
    LIP_PROTOCOL_VERSION,
    AgBusEnvelope,
    CompletePayload,
    EventPayload,
    MessageType,
    OfferPayload,
    RegisterPayload,
    SenderInfo,
    SenderKind,
    build_envelope,
)

__all__ = ["LocalBus", "RegisteredAgent"]

_COORDINATOR = SenderInfo(kind=SenderKind.COORDINATOR, id="local-bus")


class RegisteredAgent:
    """What an agent told the bus about itself when it registered."""

    def __init__(self, registration: RegisterPayload):
        self.registration = registration

    @property
    def agent_id(self) -> str:
        return self.registration.agent_id

    @property
    def capability_ids(self) -> list[str]:
        return [
            c.get("capability_id", "")
            for c in self.registration.capabilities
        ]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RegisteredAgent {self.agent_id} caps={self.capability_ids}>"


class LocalBus:
    """An in-process stand-in for a coordinator.

    Deliberately not named ``TestBus``: pytest collects classes whose names
    begin with ``Test``, and would report this one as an uncollectable test
    class in every file that imported it.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        accept_registrations: bool = True,
        refusal_reason: str = "not approved",
        answer_registrations: bool = True,
    ):
        """
        Parameters
        ----------
        port:
            0 picks a free port, so parallel tests do not collide.
        accept_registrations:
            Set ``False`` to exercise the refusal path — an agent that is
            not approved, or offers a capability it may not.
        answer_registrations:
            Set ``False`` to behave like a coordinator older than LIP 0.2.0,
            which never sends ``registered`` at all. Use it to check your
            agent still serves when it gets no acknowledgement.
        """
        self.host = host
        self.port = port
        self.accept_registrations = accept_registrations
        self.refusal_reason = refusal_reason
        self.answer_registrations = answer_registrations

        self.messages: list[AgBusEnvelope] = []
        #: Raw frames that could not be parsed as an envelope. They never
        #: reach ``messages``, so without recording them here a malformed
        #: sender is invisible to anything inspecting the transcript.
        self.malformed: list[str] = []
        #: ``Authorization`` header from each connection, in order. Lets a
        #: test assert its ``token_provider`` was used, and that a reconnect
        #: refreshed the token rather than replaying the first one.
        self.auth_headers: list[str] = []

        self._server: Any = None
        self._sockets: dict[str, Any] = {}
        self._agents: dict[str, RegisteredAgent] = {}
        self._agent_tasks: list[asyncio.Task[None]] = []
        self._started_agents: list[Any] = []
        self._waiters: list[tuple[Callable[[AgBusEnvelope], bool], asyncio.Future]] = []

    # -- lifecycle ----------------------------------------------------------

    async def __aenter__(self) -> "LocalBus":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def start(self) -> "LocalBus":
        self._server = await websockets.serve(self._handle, self.host, self.port)
        if not self.port:
            self.port = next(iter(self._server.sockets)).getsockname()[1]
        return self

    async def stop(self) -> None:
        """Stop every agent this bus started, then close the server.

        Agents are stopped first so their cleanup runs against a live
        connection rather than a half-torn-down one.
        """
        for agent in self._started_agents:
            try:
                await agent.stop()
            except Exception:  # noqa: BLE001 - teardown must not mask failures
                pass
        for task in self._agent_tasks:
            task.cancel()
        if self._agent_tasks:
            await asyncio.gather(*self._agent_tasks, return_exceptions=True)

        for socket in list(self._sockets.values()):
            try:
                await socket.close()
            except Exception:  # noqa: BLE001
                pass

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def uri(self) -> str:
        return f"ws://{self.host}:{self.port}"

    # -- agents -------------------------------------------------------------

    async def add_agent(self, agent: Any, *, timeout: float = 5.0) -> RegisteredAgent:
        """Point *agent* at this bus, start it, and wait until it registers.

        Returns once the agent is discoverable, so a test never races its own
        setup. Raises :class:`TimeoutError` rather than letting the test fail
        later in a way that hides the cause.
        """
        agent.coordinator_uri = self.uri
        self._started_agents.append(agent)
        self._agent_tasks.append(asyncio.create_task(agent.run_forever()))

        agent_id = getattr(agent, "agent_id", "")
        try:
            # Waits for *admission*, not merely for the register message to
            # arrive. The two differ exactly when the bus refuses the agent,
            # and waiting on the message there would report success for an
            # agent that is not actually usable.
            await self.wait_for(
                lambda e: agent_id in self._agents,
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            hint = (
                " (the bus is configured to refuse registrations)"
                if not self.accept_registrations
                else ""
            )
            raise TimeoutError(
                f"agent {agent_id!r} did not register within {timeout}s{hint}"
            ) from exc
        return self._agents[agent_id]

    @property
    def agents(self) -> dict[str, RegisteredAgent]:
        """Agents currently registered, keyed by ``agent_id``."""
        return dict(self._agents)

    # -- driving the lifecycle ---------------------------------------------

    async def send_intent(
        self,
        intent_text: str,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
        context: dict[str, Any] | None = None,
        expect_offers: int = 1,
        timeout: float = 5.0,
    ) -> list[OfferPayload]:
        """Deliver an intent and collect the offers it produces.

        With no *agent_id*, every registered agent receives it — which is
        how you check that an agent offers for the intents it should, and
        stays quiet for the ones it should not.
        """
        session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        payload = {"intent_text": intent_text, "context": context or {}}

        collected: list[OfferPayload] = []

        def collect(envelope: AgBusEnvelope) -> bool:
            if (
                envelope.message_type == MessageType.OFFER
                and envelope.session_id == session_id
            ):
                collected.append(OfferPayload.model_validate(envelope.payload))
            return len(collected) >= expect_offers

        waiter = self._register_waiter(collect)
        await self._send(payload, MessageType.INTENT, session_id, agent_id)

        try:
            await asyncio.wait_for(waiter, timeout=timeout)
        except asyncio.TimeoutError:
            pass  # fewer offers than hoped is a valid result to assert on
        finally:
            self._discard_waiter(waiter)
        return collected

    async def execute(
        self,
        agent_id: str,
        payload: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        context: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> CompletePayload:
        """Authorise execution and wait for the agent's completion.

        The completion is returned whether the agent succeeded or failed —
        check ``status``, since a failing task is a normal outcome the agent
        is expected to report rather than raise.
        """
        session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        plan = dict(payload or {})
        plan["context"] = context or {}

        waiter = self._register_waiter(
            lambda e: (
                e.message_type == MessageType.COMPLETE
                and e.session_id == session_id
                and e.sender.id == agent_id
            )
        )
        await self._send(
            {"execution_plan": plan, "authorized_scopes": []},
            MessageType.EXECUTE,
            session_id,
            agent_id,
        )
        try:
            envelope = await asyncio.wait_for(waiter, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"agent {agent_id!r} did not complete within {timeout}s"
            ) from exc
        finally:
            self._discard_waiter(waiter)
        return CompletePayload.model_validate(envelope.payload)

    async def send(
        self,
        message_type: MessageType,
        session_id: str,
        payload: dict[str, Any],
        *,
        agent_id: str | None = None,
    ) -> None:
        """Send a raw message, without waiting for a reply.

        The lower-level escape hatch beneath ``send_intent`` and ``execute``:
        use it to start work you do not intend to wait for (checking that two
        tasks run concurrently, say), or to send a message shape those helpers
        do not cover. With no *agent_id* it goes to every registered agent.
        """
        await self._send(payload, message_type, session_id, agent_id)

    async def dissolve(self, session_id: str, *, reason: str = "test teardown") -> None:
        """Dissolve a session, cancelling whatever the agent still has running."""
        await self._send({"reason": reason}, MessageType.DISSOLVE, session_id, None)

    # -- introspection ------------------------------------------------------

    @property
    def registrations(self) -> list[RegisterPayload]:
        return [
            RegisterPayload.model_validate(e.payload)
            for e in self.messages
            if e.message_type == MessageType.REGISTER
        ]

    def messages_of_type(self, message_type: MessageType) -> list[AgBusEnvelope]:
        return [e for e in self.messages if e.message_type == message_type]

    def events(self, *, session_id: str | None = None) -> list[EventPayload]:
        """Progress events the agent emitted, for asserting on its reporting."""
        return [
            EventPayload.model_validate(e.payload)
            for e in self.messages_of_type(MessageType.EVENT)
            if session_id is None or e.session_id == session_id
        ]

    async def wait_for(
        self,
        predicate: Callable[[AgBusEnvelope], bool],
        *,
        timeout: float = 5.0,
    ) -> AgBusEnvelope:
        """Wait for a message matching *predicate*.

        Checks messages already received before waiting, so a test cannot
        miss something that arrived while it was doing something else.
        """
        for envelope in self.messages:
            if predicate(envelope):
                return envelope

        waiter = self._register_waiter(predicate)
        try:
            return await asyncio.wait_for(waiter, timeout=timeout)
        finally:
            self._discard_waiter(waiter)

    # -- internals ----------------------------------------------------------

    async def _handle(self, socket: Any) -> None:
        self.auth_headers.append(socket.request.headers.get("Authorization", ""))
        try:
            async for raw in socket:
                try:
                    envelope = AgBusEnvelope.from_wire(json.loads(raw))
                except Exception:
                    self.malformed.append(str(raw)[:500])
                    continue
                self.messages.append(envelope)

                if envelope.message_type == MessageType.REGISTER:
                    await self._on_register(socket, envelope)

                self._resolve_waiters(envelope)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _on_register(self, socket: Any, envelope: AgBusEnvelope) -> None:
        registration = RegisterPayload.model_validate(envelope.payload)
        accepted = self.accept_registrations

        if accepted:
            self._sockets[registration.agent_id] = socket
            self._agents[registration.agent_id] = RegisteredAgent(registration)

        if not self.answer_registrations:
            return  # pre-0.2.0 coordinators never replied

        ack = build_envelope(
            MessageType.REGISTERED,
            _COORDINATOR,
            "",
            {
                "accepted": accepted,
                "agent_id": registration.agent_id,
                "reason": "" if accepted else self.refusal_reason,
                "registered_capabilities": (
                    [c.get("capability_id", "") for c in registration.capabilities]
                    if accepted
                    else []
                ),
                "coordinator_protocol_version": LIP_PROTOCOL_VERSION,
            },
        )
        await socket.send(ack.model_dump_json())

    async def _send(
        self,
        payload: dict[str, Any],
        message_type: MessageType,
        session_id: str,
        agent_id: str | None,
    ) -> None:
        if agent_id is not None:
            targets = [self._require_socket(agent_id)]
        else:
            targets = list(self._sockets.values())
            if not targets:
                raise RuntimeError(
                    "no agents are registered — call add_agent() first"
                )

        envelope = build_envelope(message_type, _COORDINATOR, session_id, payload)
        raw = envelope.model_dump_json()
        for socket in targets:
            await socket.send(raw)

    def _require_socket(self, agent_id: str) -> Any:
        socket = self._sockets.get(agent_id)
        if socket is None:
            known = ", ".join(sorted(self._sockets)) or "none"
            raise KeyError(f"agent {agent_id!r} is not registered (registered: {known})")
        return socket

    def _register_waiter(
        self, predicate: Callable[[AgBusEnvelope], bool]
    ) -> asyncio.Future:
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiters.append((predicate, future))
        return future

    def _discard_waiter(self, future: asyncio.Future) -> None:
        self._waiters = [(p, f) for p, f in self._waiters if f is not future]

    def _resolve_waiters(self, envelope: AgBusEnvelope) -> None:
        for predicate, future in list(self._waiters):
            if future.done():
                continue
            try:
                matched = predicate(envelope)
            except Exception:  # noqa: BLE001 - a bad predicate is the test's bug
                continue
            if matched:
                future.set_result(envelope)
