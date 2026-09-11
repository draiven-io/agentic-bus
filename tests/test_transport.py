"""The transport contract, and the in-process implementation of it.

Two things are being established here.

That a coordinator runs with no socket is the useful headline: it makes the
runtime embeddable in a host application that already owns a process, rather
than a service that has to be operated alongside one.

That the local transport behaves *like* a socket matters more. A local
transport with looser semantics would let code pass here and fail over a
network, which is worse than not having one — so the copy-on-send behaviour
that a socket gives away for free is tested explicitly.
"""

from __future__ import annotations

import asyncio

import pytest

from agentic_bus import AgentCapability, BaseAgent
from agentic_bus.core.protocol.envelope import (
    MessageType,
    SenderInfo,
    SenderKind,
    build_envelope,
)
from agentic_bus.core.transport.base import Peer, Transport, resolve_loopback
from agentic_bus.core.transport.local import LocalTransport
from agentic_bus.core.transport.ws import WSPeer, WSServer


def _envelope(payload: dict | None = None, session_id: str = "s1"):
    return build_envelope(
        MessageType.EVENT,
        SenderInfo(kind=SenderKind.AGENT, id="a1"),
        session_id,
        payload if payload is not None else {},
    )


class TestBothTransportsSatisfyTheContract:
    """If either drifts from the Protocol, the runtime silently loses one."""

    def test_ws_server_is_a_transport(self):
        assert isinstance(WSServer(), Transport)

    def test_local_transport_is_a_transport(self):
        assert isinstance(LocalTransport(), Transport)

    def test_ws_peer_is_a_peer(self):
        assert isinstance(WSPeer(ws=None), Peer)

    def test_ws_advertises_a_dialable_endpoint(self):
        assert WSServer(host="10.0.0.5", port=9000).agent_endpoint == "ws://10.0.0.5:9000"

    def test_a_wildcard_bind_is_advertised_as_loopback(self):
        # 0.0.0.0 means "bind everywhere"; nothing can connect *to* it.
        assert WSServer(host="0.0.0.0", port=9000).agent_endpoint == "ws://127.0.0.1:9000"
        assert resolve_loopback("::", 1) == "ws://127.0.0.1:1"

    def test_in_process_advertises_no_endpoint(self):
        # There is nothing to dial, and saying so is the point: a caller that
        # spawns agents must notice rather than invent an address.
        assert LocalTransport().agent_endpoint is None


class TestLocalTransportBehavesLikeASocket:
    async def test_a_peer_appears_on_connect_and_goes_on_close(self):
        transport = LocalTransport()
        await transport.start()

        conn = await transport.connect("agent-1", on_receive=None)
        assert transport.get_peer("agent-1") is not None
        assert transport.peer_ids == ["agent-1"]

        await conn.close()
        assert transport.get_peer("agent-1") is None

    async def test_messages_travel_both_ways(self):
        to_coordinator: list = []
        to_agent: list = []

        async def coordinator_handler(envelope, peer):
            to_coordinator.append((envelope, peer))

        async def agent_handler(envelope, _peer):
            to_agent.append(envelope)

        transport = LocalTransport(on_message=coordinator_handler)
        await transport.start()
        conn = await transport.connect("agent-1", on_receive=agent_handler)

        await conn.send_envelope(_envelope({"direction": "up"}))
        assert to_coordinator[0][0].payload["direction"] == "up"

        # The handler is handed the channel back to the sender, so it can
        # answer without a lookup — same as the WebSocket server.
        await to_coordinator[0][1].send_envelope(_envelope({"direction": "down"}))
        assert to_agent[0].payload["direction"] == "down"

    async def test_the_receiver_cannot_mutate_the_sender_s_envelope(self):
        """A socket gives each side its own object. This must too."""
        received: list = []

        async def handler(envelope, _peer):
            received.append(envelope)

        transport = LocalTransport(on_message=handler)
        conn = await transport.connect("agent-1")

        sent = _envelope({"items": ["a"]})
        await conn.send_envelope(sent)

        received[0].payload["items"].append("b")

        assert sent.payload["items"] == ["a"], (
            "the receiver mutated the sender's payload — this would pass "
            "locally and behave differently over a socket"
        )

    async def test_disconnect_is_reported_once(self):
        gone: list[str] = []

        async def on_disconnect(peer_id):
            gone.append(peer_id)

        transport = LocalTransport(on_disconnect=on_disconnect)
        conn = await transport.connect("agent-1")

        await conn.close()
        await conn.close()  # idempotent

        assert gone == ["agent-1"]

    async def test_sending_after_close_is_refused(self):
        transport = LocalTransport()
        conn = await transport.connect("agent-1")
        await conn.close()

        with pytest.raises(ConnectionError):
            await conn.send_envelope(_envelope())

    async def test_a_handler_that_raises_does_not_kill_the_channel(self):
        seen: list = []

        async def handler(envelope, _peer):
            seen.append(envelope)
            raise RuntimeError("boom")

        transport = LocalTransport(on_message=handler)
        conn = await transport.connect("agent-1")

        await conn.send_envelope(_envelope({"n": 1}))
        await conn.send_envelope(_envelope({"n": 2}))

        assert len(seen) == 2, "one bad message closed the channel"

    async def test_broadcast_reaches_everyone_but_the_excluded(self):
        inboxes: dict[str, list] = {"a": [], "b": [], "c": []}

        def receiver(name):
            async def _recv(envelope, _peer):
                inboxes[name].append(envelope)

            return _recv

        transport = LocalTransport()
        for name in inboxes:
            await transport.connect(name, on_receive=receiver(name))

        await transport.broadcast(_envelope(), exclude={"b"})

        assert len(inboxes["a"]) == 1
        assert len(inboxes["b"]) == 0
        assert len(inboxes["c"]) == 1

    async def test_a_duplicate_peer_id_is_refused(self):
        transport = LocalTransport()
        await transport.connect("agent-1")

        with pytest.raises(ValueError, match="already connected"):
            await transport.connect("agent-1")

    async def test_stopping_closes_every_peer(self):
        transport = LocalTransport()
        await transport.start()
        await transport.connect("a")
        await transport.connect("b")

        await transport.stop()

        assert transport.peer_ids == []


class Weatherman(BaseAgent):
    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability(capability_id="forecast", description="Weather")]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        return {"forecast": "sunny"}


class TestACoordinatorWithNoSocket:
    """The point of the exercise: a runtime embedded rather than operated."""

    async def test_an_agent_registers_in_process(self):
        from agentic_bus.coordinator.runtime import CoordinatorRuntime

        transport = LocalTransport()
        runtime = CoordinatorRuntime(transport=transport)
        await runtime.start()

        agent = Weatherman(agent_id="weatherman", registration_timeout=2.0)
        try:
            await agent.attach(transport)

            assert await _eventually(lambda: runtime.registry.get("weatherman") is not None), (
                "the agent attached but never reached the capability registry"
            )
            assert agent.is_running
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_no_port_is_bound(self):
        """The whole reason to embed: nothing to bind, nothing to conflict."""
        from agentic_bus.coordinator.runtime import CoordinatorRuntime

        transport = LocalTransport()
        runtime = CoordinatorRuntime(transport=transport)
        await runtime.start()
        try:
            assert runtime._server.agent_endpoint is None
            assert runtime._server.description == "in-process"
        finally:
            await runtime.stop()

    async def test_detaching_removes_the_agent_from_the_registry(self):
        from agentic_bus.coordinator.runtime import CoordinatorRuntime

        transport = LocalTransport()
        runtime = CoordinatorRuntime(transport=transport)
        await runtime.start()

        agent = Weatherman(agent_id="weatherman", registration_timeout=2.0)
        await agent.attach(transport)
        await _eventually(lambda: runtime.registry.get("weatherman") is not None)

        try:
            await agent.stop()

            assert await _eventually(
                lambda: not runtime.registry.is_online("weatherman")
            ), "a detached agent stayed online in the registry"
        finally:
            await runtime.stop()

    async def test_managed_agents_are_refused_rather_than_spawned_blind(self):
        """There is no address to hand a subprocess, and saying so beats guessing."""
        from agentic_bus.coordinator.runtime import CoordinatorRuntime

        transport = LocalTransport()
        runtime = CoordinatorRuntime(transport=transport)
        await runtime.start()
        try:
            assert await runtime.start_managed_agent("anything") is False
        finally:
            await runtime.stop()


async def _eventually(predicate, timeout: float = 3.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False
