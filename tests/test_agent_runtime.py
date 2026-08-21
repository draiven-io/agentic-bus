"""Agent runtime behaviour: reconnection, concurrency, cancellation, auth.

These run against a **real** WebSocket server rather than a mocked socket.
Every defect covered here was invisible to a mock: the agent's receive loop,
its supervision loop and the server's disconnect all have to interact for the
bug to appear, and a mock replaces exactly the piece that misbehaves.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import websockets

from agentic_bus.agents.base.agent import BaseAgent, ReconnectPolicy
from agentic_bus.core.protocol.envelope import (
    MessageType,
    SenderInfo,
    SenderKind,
    build_envelope,
)
from agentic_bus.core.registry.capability_registry import AgentCapability


class FakeCoordinator:
    """Minimal stand-in for the coordinator's WebSocket endpoint.

    Records what agents send, can push messages back, and — the part that
    matters here — can be stopped and restarted on the same port.
    """

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.connections: list[Any] = []
        self.auth_headers: list[str] = []
        self._server: Any = None
        self.port: int = 0

    async def start(self, port: int = 0) -> int:
        self._server = await websockets.serve(self._handle, "127.0.0.1", port)
        self.port = port or next(iter(self._server.sockets)).getsockname()[1]
        return self.port

    async def _handle(self, ws) -> None:
        self.connections.append(ws)
        header = ws.request.headers.get("Authorization", "")
        self.auth_headers.append(header)
        try:
            async for raw in ws:
                self.received.append(json.loads(raw))
        except websockets.exceptions.ConnectionClosed:
            pass

    async def send(self, message_type: MessageType, session_id: str, payload: dict) -> None:
        """Push a coordinator-originated message to the newest connection."""
        env = build_envelope(
            message_type,
            SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            session_id,
            payload,
        )
        await self.connections[-1].send(env.model_dump_json())

    async def stop(self) -> None:
        """Drop every connection and release the port."""
        for ws in self.connections:
            await ws.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def uri(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    def registrations(self) -> list[dict[str, Any]]:
        return [
            m for m in self.received
            if m.get("session_id") == "__registration__"
        ]


class RecordingAgent(BaseAgent):
    """Agent whose task duration and cancellation are controllable."""

    def __init__(self, *args, duration: float = 0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.duration = duration
        self.started: list[str] = []
        self.finished: list[str] = []
        self.cancelled: list[str] = []

    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability(capability_id="test-cap", description="test")]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        marker = payload.get("marker", "?")
        self.started.append(marker)
        try:
            await asyncio.sleep(self.duration)
        except asyncio.CancelledError:
            self.cancelled.append(marker)
            raise
        self.finished.append(marker)
        return {"marker": marker}


async def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    """Poll until *predicate* holds. Returns False on timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


@pytest.fixture()
async def coordinator():
    bus = FakeCoordinator()
    await bus.start()
    yield bus
    await bus.stop()


class TestRegistration:
    async def test_agent_registers_on_connect(self, coordinator):
        agent = RecordingAgent(agent_id="a1", coordinator_uri=coordinator.uri)
        task = asyncio.create_task(agent.run_forever())

        assert await _wait_for(lambda: coordinator.registrations()), "never registered"

        reg = coordinator.registrations()[0]["payload"]["registration"]
        assert reg["agent_id"] == "a1"
        assert [c["capability_id"] for c in reg["capabilities"]] == ["test-cap"]

        await agent.stop()
        task.cancel()


class TestReconnection:
    """The defect: a dropped connection left the agent alive but unreachable.

    ``run_forever`` slept in a loop while the receive task had already exited,
    so the agent served nothing and never came back.
    """

    async def test_agent_reconnects_and_reregisters_after_coordinator_restart(self):
        bus = FakeCoordinator()
        port = await bus.start()

        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=bus.uri,
            reconnect=ReconnectPolicy(initial=0.05, maximum=0.2, jitter=False),
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: len(bus.registrations()) == 1), "initial registration"

        # Coordinator goes away, then comes back on the same port.
        await bus.stop()
        restarted = FakeCoordinator()
        await restarted.start(port=port)

        try:
            reconnected = await _wait_for(
                lambda: len(restarted.registrations()) >= 1, timeout=10.0
            )
            assert reconnected, "agent did not reconnect and re-register"
        finally:
            await agent.stop()
            task.cancel()
            await restarted.stop()

    async def test_agent_retries_when_coordinator_is_down_at_startup(self):
        """Starting before the coordinator must not be fatal."""
        bus = FakeCoordinator()
        port = await bus.start()
        await bus.stop()  # free the port; nothing is listening now

        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=f"ws://127.0.0.1:{port}",
            reconnect=ReconnectPolicy(initial=0.05, maximum=0.2, jitter=False),
        )
        task = asyncio.create_task(agent.run_forever())
        await asyncio.sleep(0.3)  # let a few attempts fail

        late = FakeCoordinator()
        await late.start(port=port)
        try:
            assert await _wait_for(
                lambda: len(late.registrations()) >= 1, timeout=10.0
            ), "agent never connected once the coordinator appeared"
        finally:
            await agent.stop()
            task.cancel()
            await late.stop()


class TestConcurrency:
    """The defect: handlers were awaited inside the socket's receive loop.

    One slow ``execute_task`` therefore stopped the agent reading anything
    else at all.
    """

    async def test_a_slow_task_does_not_block_further_messages(self, coordinator):
        agent = RecordingAgent(
            agent_id="a1", coordinator_uri=coordinator.uri, duration=1.0
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.registrations())

        for marker in ("first", "second"):
            await coordinator.send(
                MessageType.EXECUTE,
                f"session-{marker}",
                {"execution_plan": {"marker": marker, "context": {}}},
            )

        # Both must be running concurrently; serially the second would not
        # start until the first finished a second later.
        both_started = await _wait_for(lambda: len(agent.started) == 2, timeout=2.0)
        assert both_started, f"only started {agent.started} — dispatch is serial"
        assert agent.finished == [], "tasks finished too early to prove concurrency"

        await agent.stop()
        task.cancel()

    async def test_concurrency_is_bounded(self, coordinator):
        """Work beyond the limit queues rather than spawning without bound."""
        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=coordinator.uri,
            duration=1.0,
            max_concurrent_tasks=2,
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.registrations())

        for i in range(5):
            await coordinator.send(
                MessageType.EXECUTE,
                f"session-{i}",
                {"execution_plan": {"marker": str(i), "context": {}}},
            )

        await asyncio.sleep(0.4)
        assert len(agent.started) == 2, f"expected 2 running, got {agent.started}"

        await agent.stop()
        task.cancel()


class TestCancellation:
    """The defect: ``dissolve`` only logged.

    The protocol says dissolution triggers *mandatory* cleanup, but in-flight
    work carried on regardless.
    """

    async def test_dissolve_cancels_in_flight_work_for_that_session(self, coordinator):
        agent = RecordingAgent(
            agent_id="a1", coordinator_uri=coordinator.uri, duration=5.0
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.registrations())

        await coordinator.send(
            MessageType.EXECUTE,
            "doomed",
            {"execution_plan": {"marker": "doomed", "context": {}}},
        )
        assert await _wait_for(lambda: agent.started == ["doomed"])

        await coordinator.send(MessageType.DISSOLVE, "doomed", {"reason": "test"})

        assert await _wait_for(lambda: agent.cancelled == ["doomed"], timeout=3.0), (
            "execute_task was never cancelled by dissolve"
        )
        assert agent.finished == [], "task completed despite dissolution"

        await agent.stop()
        task.cancel()

    async def test_dissolve_leaves_other_sessions_running(self, coordinator):
        agent = RecordingAgent(
            agent_id="a1", coordinator_uri=coordinator.uri, duration=2.0
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.registrations())

        for marker in ("keep", "drop"):
            await coordinator.send(
                MessageType.EXECUTE,
                marker,
                {"execution_plan": {"marker": marker, "context": {}}},
            )
        assert await _wait_for(lambda: len(agent.started) == 2)

        await coordinator.send(MessageType.DISSOLVE, "drop", {"reason": "test"})
        assert await _wait_for(lambda: agent.cancelled == ["drop"], timeout=3.0)
        assert "keep" not in agent.cancelled, "cancelled an unrelated session"

        await agent.stop()
        task.cancel()

    async def test_stop_cancels_everything(self, coordinator):
        agent = RecordingAgent(
            agent_id="a1", coordinator_uri=coordinator.uri, duration=5.0
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.registrations())

        await coordinator.send(
            MessageType.EXECUTE,
            "s1",
            {"execution_plan": {"marker": "s1", "context": {}}},
        )
        assert await _wait_for(lambda: agent.started == ["s1"])

        await agent.stop()
        assert agent.cancelled == ["s1"], "stop() left work running"
        task.cancel()


class TestAuthentication:
    """The defect: the dev identity was hardcoded, so the SDK could not
    authenticate against a coordinator running real OIDC."""

    async def test_default_token_is_the_dev_identity(self, coordinator):
        agent = RecordingAgent(agent_id="a1", coordinator_uri=coordinator.uri)
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.auth_headers)

        token = coordinator.auth_headers[0].removeprefix("Bearer ")
        assert json.loads(token) == {"sub": "a1", "iss": "dev"}

        await agent.stop()
        task.cancel()

    async def test_custom_sync_token_provider_is_used(self, coordinator):
        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=coordinator.uri,
            token_provider=lambda: "static-token",
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.auth_headers)
        assert coordinator.auth_headers[0] == "Bearer static-token"

        await agent.stop()
        task.cancel()

    async def test_async_token_provider_is_awaited(self, coordinator):
        async def fetch_token() -> str:
            await asyncio.sleep(0)
            return "async-token"

        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=coordinator.uri,
            token_provider=fetch_token,
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.auth_headers)
        assert coordinator.auth_headers[0] == "Bearer async-token"

        await agent.stop()
        task.cancel()

    async def test_token_is_refreshed_on_reconnect(self):
        """Short-lived tokens are the normal case, so a reconnect must not
        replay the token captured at startup."""
        bus = FakeCoordinator()
        port = await bus.start()

        issued: list[str] = []

        def rotating_token() -> str:
            token = f"token-{len(issued)}"
            issued.append(token)
            return token

        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=bus.uri,
            token_provider=rotating_token,
            reconnect=ReconnectPolicy(initial=0.05, maximum=0.2, jitter=False),
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: bus.auth_headers)
        assert bus.auth_headers[0] == "Bearer token-0"

        await bus.stop()
        restarted = FakeCoordinator()
        await restarted.start(port=port)
        try:
            assert await _wait_for(
                lambda: restarted.auth_headers, timeout=10.0
            ), "never reconnected"
            assert restarted.auth_headers[0] != "Bearer token-0", (
                "reconnect replayed the original token instead of refreshing it"
            )
        finally:
            await agent.stop()
            task.cancel()
            await restarted.stop()


class TestNoResourceLeaks:
    async def test_cancelling_queued_work_does_not_leak_a_coroutine(self, coordinator):
        """Cancelling while queued behind the concurrency limit must not
        leave an un-awaited coroutine, which Python reports as a
        RuntimeWarning in the user's logs."""
        import warnings

        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=coordinator.uri,
            duration=5.0,
            max_concurrent_tasks=1,
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.registrations())

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            # Two messages, limit of one: the second sits on the semaphore.
            for marker in ("running", "queued"):
                await coordinator.send(
                    MessageType.EXECUTE,
                    f"session-{marker}",
                    {"execution_plan": {"marker": marker, "context": {}}},
                )
            assert await _wait_for(lambda: agent.started == ["running"])

            await agent.stop()
            task.cancel()
            await asyncio.sleep(0.1)

            leaked = [
                w for w in caught
                if "never awaited" in str(w.message)
            ]
            assert leaked == [], f"leaked coroutine: {[str(w.message) for w in leaked]}"


class TestCredentialRedaction:
    """A coordinator URI may carry credentials (``ws://agent:pw@host``).

    The reconnect loop logs the URI on every attempt, so an unredacted one
    would write the password to the log repeatedly — flagged by CodeQL as
    clear-text logging of sensitive information.
    """

    def test_password_is_redacted_from_the_uri(self):
        from agentic_bus.agents.base.agent import _redact_uri

        assert _redact_uri("ws://agent:s3cret@host:8765") == "ws://agent:***@host:8765"
        assert "s3cret" not in _redact_uri("wss://u:s3cret@h/path?q=1")

    def test_uris_without_credentials_are_untouched(self):
        from agentic_bus.agents.base.agent import _redact_uri

        for uri in ("ws://localhost:8765", "wss://bus.example.com/lip", "ws://user@host"):
            assert _redact_uri(uri) == uri

    def test_password_is_redacted_from_exception_text(self):
        """Connection errors often quote the URI they failed on."""
        from agentic_bus.agents.base.agent import _redact_secret

        message = "cannot connect to ws://agent:s3cret@host:8765"
        assert _redact_secret(message, "s3cret") == "cannot connect to ws://agent:***@host:8765"
        assert _redact_secret("plain failure", None) == "plain failure"

    async def test_reconnect_logging_never_emits_the_password(self, caplog, monkeypatch):
        """End to end: drive a failing connection and inspect the log.

        The failure is injected rather than produced by dialling a dead port:
        a refused connection takes seconds to surface on some platforms, which
        would make this test both slow and timing-dependent.
        """
        import logging as _logging

        from agentic_bus.core.transport.ws import WSClient

        uri = "ws://agent:s3cret@127.0.0.1:1"

        async def refuse(self, extra_headers=None):
            # Connection errors routinely quote the URI they failed on, so the
            # password can reach the log through the exception as well as
            # through the URI argument.
            raise ConnectionRefusedError(f"cannot connect to {uri}")

        monkeypatch.setattr(WSClient, "connect", refuse)

        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=uri,
            reconnect=ReconnectPolicy(initial=0.01, maximum=0.05, jitter=False),
        )
        with caplog.at_level(_logging.DEBUG):
            task = asyncio.create_task(agent.run_forever())
            await _wait_for(lambda: any("could not connect" in r.getMessage() for r in caplog.records))
            await agent.stop()
            task.cancel()

        assert any("could not connect" in r.getMessage() for r in caplog.records), (
            "the connection failure was never logged, so this proves nothing"
        )
        assert "s3cret" not in caplog.text, "password leaked into the log"
        assert "***" in caplog.text, "URI was not redacted at all"
