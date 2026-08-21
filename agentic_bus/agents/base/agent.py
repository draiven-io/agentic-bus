"""Base provider agent framework (§20 of AGENTS.md).

Each provider agent MUST:
1. Authenticate using OIDC.
2. Register capabilities dynamically.
3. Receive intent and offer requests.
4. Produce offers.
5. Execute tasks only after explicit ``execute`` message.
6. Emit completion messages.
7. Support cancellation.

This module provides a base class ``BaseAgent`` that handles the protocol
handshake and message routing, allowing concrete agents to focus on
capability logic.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from agentic_bus.core.protocol.envelope import (
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
    IntentPayload,
    OfferPayload,
    CompletePayload,
    EventPayload,
    build_envelope,
)
from agentic_bus.core.transport.ws import WSClient, WSPeer
from agentic_bus.core.registry.capability_registry import AgentCapability, AgentRegistration
from agentic_bus.core.telemetry.tracing import agbus_span, inject_trace_context

logger = logging.getLogger(__name__)

#: Returns the bearer token used when connecting. May be sync or async, and
#: is called on every (re)connection so short-lived tokens can be refreshed.
TokenProvider = Callable[[], "str | Awaitable[str]"]


#: Matches the ``user:password@`` portion of any URL inside arbitrary text.
_URL_CREDENTIALS = re.compile(r"//[^/\s@]*:[^/\s@]*@")


def _safe_endpoint(uri: str) -> str:
    """Describe *uri* using only the parts that are safe to log.

    Built from an allowlist — scheme, host, port — rather than by redacting
    a blocklist out of the original string. Two reasons:

    * A blocklist has to anticipate every credential-bearing component; an
      allowlist cannot leak one it was never told about. Path and query are
      dropped for the same reason, since tokens turn up there too.
    * The password is never *read*, so it cannot reach a log through this
      function at all. An earlier version redacted it instead, which was
      safe in practice but still routed the credential through the logging
      expression — and static analysis was right to keep objecting.
    """
    try:
        parts = urlsplit(uri)
    except ValueError:
        return "<unparseable uri>"

    host = parts.hostname or "<unknown host>"
    endpoint = f"{parts.scheme}://{host}" if parts.scheme else host
    if parts.port:
        endpoint = f"{endpoint}:{parts.port}"
    return endpoint


def _strip_credentials(text: str) -> str:
    """Remove ``user:password@`` from any URL appearing in *text*.

    Connection errors routinely quote the URI they failed on, so sanitising
    our own URI is not enough. This works on the message alone and never
    takes the credential as an argument, so it also catches credentials in
    URLs that did not come from us.
    """
    return _URL_CREDENTIALS.sub("//***:***@", text)


class ReconnectPolicy:
    """Exponential backoff with full jitter between reconnection attempts.

    Jitter matters more than it looks: when a coordinator restarts, every
    agent notices at the same instant, and an unjittered backoff marches them
    all back in lockstep — repeatedly. Randomising the whole interval spreads
    the retries out.
    """

    def __init__(
        self,
        initial: float = 0.5,
        maximum: float = 30.0,
        multiplier: float = 2.0,
        jitter: bool = True,
    ):
        self.initial = initial
        self.maximum = maximum
        self.multiplier = multiplier
        self.jitter = jitter
        self._attempt = 0

    def reset(self) -> None:
        """Call after a successful connection, so the next outage starts fresh."""
        self._attempt = 0

    def next_delay(self) -> float:
        window = min(self.initial * (self.multiplier**self._attempt), self.maximum)
        self._attempt += 1
        return random.uniform(0, window) if self.jitter else window


class BaseAgent(ABC):
    """Abstract base class for Agentic Bus provider agents.

    Subclasses must implement:
    - ``capabilities()``: return the agent's capability descriptors.  Each
      ``AgentCapability`` can carry an ``output_model`` (a Pydantic class)
      that automatically derives the ``output_schema`` JSON Schema — the
      requester sees the shape of every answer before execution begins.
    - ``execute_task(payload, context)``: execute the authorised task.

    Offer generation is handled automatically by ``generate_offer`` based on
    the metadata already declared in each ``AgentCapability``.  Subclasses
    may override it for advanced scenarios but this is not required.
    """

    def __init__(
        self,
        agent_id: str,
        coordinator_uri: str = "ws://localhost:8765",
        version: str = "0.1.0",
        semantic_description: str = "",
        *,
        token_provider: TokenProvider | None = None,
        reconnect: ReconnectPolicy | None = None,
        max_concurrent_tasks: int = 8,
    ):
        """
        Parameters
        ----------
        token_provider:
            Returns the bearer token for the connection. Called on every
            (re)connection, so short-lived tokens are refreshed rather than
            captured once at startup. Defaults to an unsigned development
            identity, which only a coordinator running ``DevVerifier``
            accepts — supply one to talk to a coordinator with real OIDC.
        reconnect:
            Backoff policy between reconnection attempts. Pass ``None`` for
            the default; reconnection cannot be disabled, because an agent
            that stays silently dead after one blip is never the behaviour
            anyone wants.
        max_concurrent_tasks:
            Ceiling on simultaneously executing tasks. Work beyond this
            queues rather than being refused.
        """
        self.agent_id = agent_id
        self.coordinator_uri = coordinator_uri
        self.version = version
        self.semantic_description = semantic_description
        self._client: WSClient | None = None
        self._peer: WSPeer | None = None
        self._running = False

        self._token_provider = token_provider or self._default_token_provider
        self._reconnect = reconnect or ReconnectPolicy()
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)

        # In-flight work, grouped by session so ``dissolve`` can cancel
        # exactly the tasks belonging to the session being torn down.
        self._session_tasks: dict[str, set[asyncio.Task[None]]] = defaultdict(set)
        self._stopping = asyncio.Event()

    # -----------------------------------------------------------------------
    # Abstract methods – implement in subclasses
    # -----------------------------------------------------------------------

    @abstractmethod
    def capabilities(self) -> list[AgentCapability]:
        """Return the list of capabilities this agent exposes."""
        ...

    @abstractmethod
    async def execute_task(
        self,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a task and return the result."""
        ...

    # -----------------------------------------------------------------------
    # Answer validation – assigned agents validate execution output
    # -----------------------------------------------------------------------

    async def validate_answer(
        self,
        answer: dict[str, Any],
        intent_text: str,
        context: dict[str, Any],
        ibac_rules_summary: str = "",
    ) -> dict[str, Any]:
        """Validate an execution answer against this agent's expertise and IBAC rules.

        Called by the coordinator when this agent is the *assigned validator*
        for an intent.  External agents SHOULD override this method with
        domain-specific validation logic.

        Args:
            answer: The synthesised execution output to validate.
            intent_text: The original intent text.
            context: Session context including prior validation feedback.
            ibac_rules_summary: Human-readable summary of applicable IBAC rules.

        Returns:
            A dict with:
            - ``"approved"`` (bool): whether the answer passes validation.
            - ``"reason"`` (str): explanation of the decision.
            - ``"suggestions"`` (list[str]): optional improvement suggestions
              that will be fed back into the renegotiation loop.
        """
        # Default implementation: approve everything.
        # External agents MUST override this for meaningful validation.
        return {
            "approved": True,
            "reason": "Default validation — no domain-specific checks implemented.",
            "suggestions": [],
        }

    # -----------------------------------------------------------------------
    # Default offer generation
    # -----------------------------------------------------------------------

    async def generate_offer(
        self,
        intent: IntentPayload,
        capability: AgentCapability,
    ) -> OfferPayload:
        """Build an ``OfferPayload`` from the capability descriptor.

        All cost, latency, artifact, and constraint information is already
        declared on ``AgentCapability``, so agents typically don't need to
        override this.  The method is intentionally *not* abstract — override
        only when custom negotiation logic is needed.
        """
        return OfferPayload(
            capability_id=capability.capability_id,
            capability_description=capability.description,
            constraints=capability.operational_constraints,
            expected_artifacts=capability.expected_artifacts,
            estimated_cost=capability.estimated_cost,
            estimated_latency=capability.estimated_latency,
            required_scopes=capability.required_scopes,
            output_schema=capability.output_schema,
        )

    # -----------------------------------------------------------------------
    # Event emission — agents can send progress updates during execution
    # -----------------------------------------------------------------------

    async def send_event(
        self,
        session_id: str,
        summary: str,
        *,
        category: str = "agent",
        detail: dict[str, Any] | None = None,
        progress: float | None = None,
    ) -> None:
        """Send a progress / status event to the coordinator.

        The coordinator will forward the event to the requester over
        WebSocket, providing real-time visibility into agent execution.

        Use this inside ``execute_task`` to report intermediate progress,
        log messages, or partial results.

        Args:
            session_id: The session this event belongs to.
            summary: Human-readable description of the progress.
            category: Event category (``"agent"``, ``"info"``, ``"warning"``, etc.).
            detail: Arbitrary structured data to accompany the event.
            progress: Optional progress indicator between 0.0 and 1.0.
        """
        if not self._peer:
            logger.debug("Cannot send event — not connected")
            return

        event_env = build_envelope(
            MessageType.EVENT,
            SenderInfo(kind=SenderKind.AGENT, id=self.agent_id),
            session_id,
            EventPayload(
                category=category,
                summary=summary,
                detail=detail or {},
                agent_id=self.agent_id,
                progress=progress,
            ),
            inject_trace_context(),
        )
        try:
            await self._peer.send_envelope(event_env)
        except Exception:
            logger.debug("Failed to send event for session %s", session_id)

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to the coordinator, authenticate, and register capabilities."""
        self._client = WSClient(
            uri=self.coordinator_uri,
            on_message=self._on_message,
        )

        self._peer = await self._client.connect(
            extra_headers={"Authorization": f"Bearer {await self._auth_token()}"}
        )
        self._running = True
        logger.info("Agent %s connected to coordinator", self.agent_id)

        # Registration is per-connection, not once per process: the
        # coordinator holds the capability registry in memory against the
        # live socket, so a reconnected agent that skipped this would be
        # connected but invisible to discovery.
        await self._register()

    def _default_token_provider(self) -> str:
        """Unsigned development identity, accepted only by ``DevVerifier``."""
        return json.dumps({"sub": self.agent_id, "iss": "dev"})

    async def _auth_token(self) -> str:
        """Resolve the bearer token, awaiting the provider if it is async."""
        token = self._token_provider()
        if inspect.isawaitable(token):
            token = await token
        return token

    async def stop(self) -> None:
        """Stop the agent and cancel any work still in flight."""
        self._stopping.set()
        self._running = False
        await self._cancel_session_tasks()
        if self._client:
            await self._client.disconnect()
        logger.info("Agent %s disconnected", self.agent_id)

    async def run_forever(self) -> None:
        """Serve until stopped, reconnecting whenever the connection drops.

        A coordinator restart, a network blip or a proxy timeout closes the
        socket. Previously the receive loop simply exited and this method
        went on sleeping, so the agent stayed registered in nobody's registry
        and served nothing — alive to a process supervisor, dead to the bus.
        """
        self._stopping.clear()

        while not self._stopping.is_set():
            try:
                await self.start()
                self._reconnect.reset()
                # Returns when the connection drops, for any reason.
                await self._client.wait_closed()  # type: ignore[union-attr]
                if self._stopping.is_set():
                    break
                logger.warning(
                    "Agent %s lost its connection to %s",
                    self.agent_id,
                    _safe_endpoint(self.coordinator_uri),
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Covers a coordinator that is down, refusing, or rejecting
                # our token — all of which should be retried, not fatal.
                logger.warning(
                    "Agent %s could not connect to %s: %s: %s",
                    self.agent_id,
                    _safe_endpoint(self.coordinator_uri),
                    type(exc).__name__,
                    _strip_credentials(str(exc)),
                )

            if self._stopping.is_set():
                break

            delay = self._reconnect.next_delay()
            logger.info("Agent %s reconnecting in %.1fs", self.agent_id, delay)
            try:
                # Wake immediately if stop() is called mid-backoff instead of
                # making the caller wait out the delay.
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

        await self.stop()

    # -----------------------------------------------------------------------
    # Registration
    # -----------------------------------------------------------------------

    async def _register(self) -> None:
        """Send capability registration to the coordinator."""
        caps = self.capabilities()

        registration = AgentRegistration(
            agent_id=self.agent_id,
            version=self.version,
            capabilities=caps,
            semantic_description=self.semantic_description,
            required_scopes=[s for c in caps for s in c.required_scopes],
            supported_data_domains=[d for c in caps for d in c.supported_data_domains],
        )

        # Send registration as a special payload in an intent-like envelope
        # (The coordinator recognises registrations by sender kind + payload shape)
        env = build_envelope(
            message_type=MessageType.COMPLETE,  # Re-use complete as registration ack vehicle
            sender=SenderInfo(kind=SenderKind.AGENT, id=self.agent_id),
            session_id="__registration__",
            payload={"registration": registration.model_dump()},
            trace=inject_trace_context(),
        )
        if self._peer:
            await self._peer.send_envelope(env)
        logger.info("Agent %s registered %d capabilities", self.agent_id, len(caps))

    # -----------------------------------------------------------------------
    # Message handling
    # -----------------------------------------------------------------------

    async def _on_message(self, envelope: AgBusEnvelope, peer: WSPeer) -> None:
        """Route messages from the coordinator.

        Work that can take arbitrarily long — offer generation and task
        execution, both of which routinely call a model — is dispatched onto
        its own task. This handler runs *inside* the socket's receive loop,
        so awaiting that work here would stop the agent reading anything
        else, including the ``dissolve`` telling it to stop.
        """
        if envelope.message_type == MessageType.INTENT:
            self._spawn(envelope.session_id, self._handle_intent(envelope))
        elif envelope.message_type == MessageType.EXECUTE:
            self._spawn(envelope.session_id, self._handle_execute(envelope))
        elif envelope.message_type == MessageType.DISSOLVE:
            # Handled inline, and first: dissolution is the protocol's
            # guarantee that nothing survives the session, so it must cancel
            # in-flight work rather than queue behind it.
            await self._cancel_session_tasks(envelope.session_id)
            await self._handle_dissolve(envelope)
        else:
            logger.debug(
                "Agent %s ignoring message type %s",
                self.agent_id,
                envelope.message_type,
            )

    # -----------------------------------------------------------------------
    # Task lifecycle
    # -----------------------------------------------------------------------

    def _spawn(self, session_id: str, coro: Any) -> asyncio.Task[None]:
        """Run *coro* as a tracked task belonging to *session_id*."""
        task = asyncio.create_task(self._run_tracked(session_id, coro))
        self._session_tasks[session_id].add(task)
        task.add_done_callback(
            lambda t: self._session_tasks.get(session_id, set()).discard(t)
        )
        return task

    async def _run_tracked(self, session_id: str, coro: Any) -> None:
        """Execute *coro* under the concurrency limit, with a trace span."""
        entered = False
        try:
            async with self._semaphore:
                entered = True
                with agbus_span(
                    f"agent.{self.agent_id}.session.{session_id}",
                    attributes={"session_id": session_id},
                ):
                    await coro
        except asyncio.CancelledError:
            if not entered:
                # Cancelled while queued behind the concurrency limit, so the
                # coroutine never ran. Closing it keeps Python from reporting
                # "coroutine was never awaited" in the user's logs.
                coro.close()
            logger.info(
                "Agent %s cancelled work for session %s", self.agent_id, session_id
            )
            raise
        except Exception:
            # A crash in one session must not take down the agent.
            logger.exception(
                "Agent %s failed handling session %s", self.agent_id, session_id
            )

    async def _cancel_session_tasks(self, session_id: str | None = None) -> None:
        """Cancel in-flight tasks — for one session, or all of them.

        Awaits the cancelled tasks so that ``execute_task`` implementations
        get their ``CancelledError`` and finish their cleanup before this
        returns.
        """
        if session_id is None:
            sessions = list(self._session_tasks)
        else:
            sessions = [session_id]

        pending: list[asyncio.Task[None]] = []
        for sid in sessions:
            tasks = self._session_tasks.pop(sid, set())
            for task in tasks:
                if not task.done():
                    task.cancel()
                    pending.append(task)

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _handle_intent(self, envelope: AgBusEnvelope) -> None:
        """Respond to an intent with offers for each matching capability."""
        intent = IntentPayload.model_validate(envelope.payload)

        for cap in self.capabilities():
            try:
                offer = await self.generate_offer(intent, cap)

                offer_env = build_envelope(
                    MessageType.OFFER,
                    SenderInfo(kind=SenderKind.AGENT, id=self.agent_id),
                    envelope.session_id,
                    offer,
                    inject_trace_context(),
                )
                if self._peer:
                    await self._peer.send_envelope(offer_env)
                    logger.info(
                        "Agent %s sent offer for capability %s",
                        self.agent_id,
                        cap.capability_id,
                    )
            except Exception:
                logger.exception(
                    "Agent %s failed to generate offer for %s",
                    self.agent_id,
                    cap.capability_id,
                )

    async def _handle_execute(self, envelope: AgBusEnvelope) -> None:
        """Execute the authorised task and emit a complete message."""
        payload = envelope.payload
        execution_plan = payload.get("execution_plan", {})
        context = execution_plan.get("context", {})

        await self.send_event(
            envelope.session_id,
            f"Agent '{self.agent_id}' starting task execution…",
            category="agent",
        )

        try:
            result = await self.execute_task(execution_plan, context)
            status = "success"
            await self.send_event(
                envelope.session_id,
                f"Agent '{self.agent_id}' task completed successfully",
                category="agent",
                detail={"status": "success"},
            )
        except Exception as exc:
            logger.exception("Agent %s execution failed", self.agent_id)
            result = {"error": str(exc)}
            status = "error"
            await self.send_event(
                envelope.session_id,
                f"Agent '{self.agent_id}' task failed: {exc}",
                category="error",
                detail={"error": str(exc)},
            )

        complete_env = build_envelope(
            MessageType.COMPLETE,
            SenderInfo(kind=SenderKind.AGENT, id=self.agent_id),
            envelope.session_id,
            CompletePayload(
                status=status,
                artifacts=[result],
                metadata={"agent_id": self.agent_id},
            ),
            inject_trace_context(),
        )
        if self._peer:
            await self._peer.send_envelope(complete_env)

    async def _handle_dissolve(self, envelope: AgBusEnvelope) -> None:
        """Clean up any session-specific state upon dissolution."""
        logger.info(
            "Agent %s received dissolve for session %s",
            self.agent_id,
            envelope.session_id,
        )
        # Subclasses can override to clean up resources
