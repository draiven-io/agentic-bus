"""Agent runtime behaviour: reconnection, concurrency, cancellation, auth.

These run against a **real** WebSocket server rather than a mocked socket.
Every defect covered here was invisible to a mock: the agent's receive loop,
its supervision loop and the server's disconnect all have to interact for the
bug to appear, and a mock replaces exactly the piece that misbehaves.

The server is :class:`agentic_bus.testing.LocalBus` — the same harness the
SDK ships to agent authors. Using it here rather than a private fake means
these tests exercise the supported API, so a gap in it shows up as a gap in
our own tests first.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from agentic_bus.agents.base.agent import BaseAgent, ReconnectPolicy
from agentic_bus.core.protocol.envelope import LIP_PROTOCOL_VERSION, MessageType
from agentic_bus.core.registry.capability_registry import AgentCapability
from agentic_bus.testing import LocalBus


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
    async with LocalBus() as bus:
        yield bus


class TestRegistration:
    async def test_agent_registers_on_connect(self, coordinator):
        agent = RecordingAgent(agent_id="a1", coordinator_uri=coordinator.uri)
        task = asyncio.create_task(agent.run_forever())

        assert await _wait_for(lambda: coordinator.registrations), "never registered"

        reg = coordinator.registrations[0]
        assert reg.agent_id == "a1"
        assert [c["capability_id"] for c in reg.capabilities] == ["test-cap"]

        await agent.stop()
        task.cancel()


class TestReconnection:
    """The defect: a dropped connection left the agent alive but unreachable.

    ``run_forever`` slept in a loop while the receive task had already exited,
    so the agent served nothing and never came back.
    """

    async def test_agent_reconnects_and_reregisters_after_coordinator_restart(self):
        bus = LocalBus()
        await bus.start()
        port = bus.port

        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=bus.uri,
            reconnect=ReconnectPolicy(initial=0.05, maximum=0.2, jitter=False),
        )
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: len(bus.registrations) == 1), "initial registration"

        # Coordinator goes away, then comes back on the same port.
        await bus.stop()
        restarted = LocalBus(port=port)
        await restarted.start()

        try:
            reconnected = await _wait_for(
                lambda: len(restarted.registrations) >= 1, timeout=10.0
            )
            assert reconnected, "agent did not reconnect and re-register"
        finally:
            await agent.stop()
            task.cancel()
            await restarted.stop()

    async def test_agent_retries_when_coordinator_is_down_at_startup(self):
        """Starting before the coordinator must not be fatal."""
        bus = LocalBus()
        await bus.start()
        port = bus.port
        await bus.stop()  # free the port; nothing is listening now

        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=f"ws://127.0.0.1:{port}",
            reconnect=ReconnectPolicy(initial=0.05, maximum=0.2, jitter=False),
        )
        task = asyncio.create_task(agent.run_forever())
        await asyncio.sleep(0.3)  # let a few attempts fail

        late = LocalBus(port=port)
        await late.start()
        try:
            assert await _wait_for(
                lambda: len(late.registrations) >= 1, timeout=10.0
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
        assert await _wait_for(lambda: coordinator.registrations)

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
        assert await _wait_for(lambda: coordinator.registrations)

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
        assert await _wait_for(lambda: coordinator.registrations)

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
        assert await _wait_for(lambda: coordinator.registrations)

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
        assert await _wait_for(lambda: coordinator.registrations)

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
        bus = LocalBus()
        await bus.start()
        port = bus.port

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
        restarted = LocalBus(port=port)
        await restarted.start()
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
        assert await _wait_for(lambda: coordinator.registrations)

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


class TestCredentialsNeverReachTheLog:
    """The coordinator URI is deliberately never logged.

    It may carry credentials (``ws://agent:pw@host:8765``), and the reconnect
    loop logs on every attempt. A sanitised form was provably safe, but code
    scanning could not see through the sanitiser; rather than keep fighting
    it over an optional log field, the URI stays out of the logs entirely.
    What cannot be formatted cannot leak.
    """

    def test_credentials_are_stripped_from_arbitrary_text(self):
        """Connection errors routinely quote the URI they failed on, so the
        exception message still has to be scrubbed."""
        from agentic_bus.agents.base.agent import _strip_credentials

        assert (
            _strip_credentials("cannot connect to ws://agent:s3cret@host:8765")
            == "cannot connect to ws://***:***@host:8765"
        )
        assert _strip_credentials("no urls here") == "no urls here"

    def test_stripping_needs_no_knowledge_of_the_secret(self):
        """It takes only the message, so it also catches credentials in URLs
        that did not come from our own configuration."""
        from agentic_bus.agents.base.agent import _strip_credentials

        assert "hunter2" not in _strip_credentials("proxy ws://someone:hunter2@other:1")

    async def test_reconnect_logging_never_emits_the_uri(self, caplog, monkeypatch):
        """End to end: drive a failing connection and inspect the log.

        The failure is injected rather than produced by dialling a dead port,
        which takes seconds to be refused on some platforms and would make
        this both slow and timing-dependent.
        """
        import logging as _logging

        from agentic_bus.core.transport.ws import WSClient

        uri = "ws://agent:s3cret@127.0.0.1:1"

        async def refuse(self, extra_headers=None):
            raise ConnectionRefusedError(f"cannot connect to {uri}")

        monkeypatch.setattr(WSClient, "connect", refuse)

        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=uri,
            reconnect=ReconnectPolicy(initial=0.01, maximum=0.05, jitter=False),
        )
        with caplog.at_level(_logging.DEBUG):
            task = asyncio.create_task(agent.run_forever())
            await _wait_for(
                lambda: any("could not reach" in r.getMessage() for r in caplog.records)
            )
            await agent.stop()
            task.cancel()

        assert any("could not reach" in r.getMessage() for r in caplog.records), (
            "the connection failure was never logged, so this proves nothing"
        )
        assert "s3cret" not in caplog.text, "password leaked into the log"
        assert "agent:s3cret@" not in caplog.text, "credentials leaked into the log"
        assert "a1" in caplog.text, "the agent should still be identifiable"

        # We never format the URI ourselves. A host can still appear via a
        # third-party exception message — that is not a credential, and the
        # userinfo is scrubbed out of it on the way through.
        ours = [
            r.getMessage() for r in caplog.records
            if "could not reach" in r.getMessage()
        ]
        assert ours
        for message in ours:
            assert "127.0.0.1" not in message.split(":")[0], (
                "our own log line should not name the endpoint"
            )


class TestRegisterPerformative:
    """Registration is a protocol act (LIP 0.2.0), not a magic session id.

    Before this, agents registered by sending ``complete`` with
    ``session_id="__registration__"`` and a nested payload — a shape the
    specification never described, so nobody could write an interoperable
    agent from the spec alone.
    """

    async def test_registration_uses_the_register_performative(self, coordinator):
        agent = RecordingAgent(agent_id="a1", coordinator_uri=coordinator.uri)
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.registrations)

        # The envelope, not the parsed payload — this asserts on the wire
        # format, which is the whole point of the performative.
        envelope = coordinator.messages_of_type(MessageType.REGISTER)[0]
        assert envelope.message_type == MessageType.REGISTER
        # Against the constant, not a literal: this test is about the
        # register performative, and hardcoding the version made it fail
        # on an intentional bump. test_protocol.py owns versioning.
        assert envelope.protocol_version == LIP_PROTOCOL_VERSION
        # Fields sit directly in the payload, not nested under "registration".
        assert envelope.payload["agent_id"] == "a1"
        assert "registration" not in envelope.payload

        await agent.stop()
        task.cancel()

    async def test_no_complete_message_is_used_for_registration(self, coordinator):
        agent = RecordingAgent(agent_id="a1", coordinator_uri=coordinator.uri)
        task = asyncio.create_task(agent.run_forever())
        assert await _wait_for(lambda: coordinator.registrations)

        legacy = [
            m for m in coordinator.messages
            if m.session_id == "__registration__"
        ]
        assert legacy == [], "still registering via the deprecated complete form"

        await agent.stop()
        task.cancel()

    async def test_accepted_registration_is_logged(self, coordinator, caplog):
        import logging as _logging

        agent = RecordingAgent(agent_id="a1", coordinator_uri=coordinator.uri)
        with caplog.at_level(_logging.INFO):
            task = asyncio.create_task(agent.run_forever())
            assert await _wait_for(
                lambda: any("registered 1 capabilities" in r.getMessage()
                            for r in caplog.records)
            ), "acceptance was never confirmed"
            await agent.stop()
            task.cancel()

    async def test_refused_registration_is_surfaced(self, coordinator, caplog):
        """A refusal must be loud: the agent is connected but will never be
        asked to do anything."""
        import logging as _logging

        coordinator.accept_registrations = False
        coordinator.refusal_reason = "agent not approved"

        refusals: list[str] = []

        class WatchfulAgent(RecordingAgent):
            async def on_registration_refused(self, ack):
                refusals.append(ack.reason)

        agent = WatchfulAgent(agent_id="a1", coordinator_uri=coordinator.uri)
        with caplog.at_level(_logging.ERROR):
            task = asyncio.create_task(agent.run_forever())
            assert await _wait_for(lambda: refusals), "refusal hook never fired"
            await agent.stop()
            task.cancel()

        assert refusals == ["agent not approved"]
        assert "refused registration" in caplog.text

    async def test_missing_ack_does_not_stop_the_agent(self, caplog):
        """A coordinator older than LIP 0.2.0 never answers.

        Refusing to run against one would be a worse failure than running
        without confirmation, so the agent warns and carries on.
        """
        import logging as _logging

        bus = LocalBus(answer_registrations=False)
        await bus.start()
        agent = RecordingAgent(
            agent_id="a1",
            coordinator_uri=bus.uri,
            registration_timeout=0.2,
        )
        with caplog.at_level(_logging.WARNING):
            task = asyncio.create_task(agent.run_forever())
            assert await _wait_for(
                lambda: any("no 'registered' answer" in r.getMessage()
                            for r in caplog.records),
                timeout=5.0,
            ), "the missing acknowledgement was never reported"

            # Still serving: the agent must accept work despite the silence.
            await bus.send(
                MessageType.EXECUTE,
                "s1",
                {"execution_plan": {"marker": "s1", "context": {}}},
            )
            assert await _wait_for(lambda: agent.finished == ["s1"]), (
                "agent stopped serving after an unacknowledged registration"
            )
            await agent.stop()
            task.cancel()
        await bus.stop()
