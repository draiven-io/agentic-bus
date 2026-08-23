"""Scope resolution at admission, end to end over the in-process transport.

One property carries this whole file, and it is the one RFC 0003 exists for:

    **Declaring a scope does not grant it.**

Before this, an agent's `required_scopes` went straight into the registry and
`carrier:qoute` registered as successfully as `carrier:quote`. So the tests
that matter are the ones showing an agent asking loudly and receiving nothing.
"""

from __future__ import annotations

import asyncio

from agentic_bus import AgentCapability, BaseAgent
from agentic_bus.core.persistence.scope_repository import ScopeRepository
from agentic_bus.core.transport.local import LocalTransport


class CarrierAgent(BaseAgent):
    """Declares two scopes: one its deployment knows, one it should not have."""

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="quote",
                description="Obtains freight quotes",
                required_scopes=["carrier:quote"],
            ),
            AgentCapability(
                capability_id="book",
                description="Books carrier capacity",
                required_scopes=["payments:write"],
            ),
        ]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        return {"ok": True}


class _Recorder:
    """Captures the coordinator's answer, which is where the grant is reported."""

    def __init__(self) -> None:
        self.ack = None

    async def __call__(self, ack):
        self.ack = ack


async def _register(monkeypatch, *, enforced: bool, agent=None):
    """Bring up an in-process coordinator and register one agent."""
    from agentic_bus.coordinator.runtime import CoordinatorRuntime

    monkeypatch.setenv(
        "AGBUS_SCOPE_CATALOGUE_ENFORCED", "true" if enforced else "false"
    )
    monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)

    transport = LocalTransport()
    runtime = CoordinatorRuntime(transport=transport)
    await runtime.start()

    agent = agent or CarrierAgent(agent_id="carrier-negotiator", registration_timeout=2.0)
    recorder = _Recorder()
    agent.on_registered = recorder

    await agent.attach(transport)
    await _eventually(lambda: recorder.ack is not None)
    return runtime, agent, recorder


class TestDeclaringDoesNotGrant:
    async def test_an_unbound_capability_is_granted_nothing(self, monkeypatch):
        """The agent asks for two scopes and receives none, because nobody bound them."""
        runtime, agent, rec = await _register(monkeypatch, enforced=False)
        try:
            assert rec.ack.accepted
            assert rec.ack.granted_scopes == [], (
                "scopes were granted without any administrator binding them"
            )
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_a_binding_is_what_grants(self, monkeypatch):
        repo = ScopeRepository()
        repo.add_scope("carrier:quote", "Obtain freight quotes")
        repo.bind("carrier-negotiator", "quote", ["carrier:quote"])

        runtime, agent, rec = await _register(monkeypatch, enforced=False)
        try:
            assert rec.ack.granted_scopes == ["carrier:quote"]
            # It asked for payments:write just as loudly, and did not get it.
            assert "payments:write" not in rec.ack.granted_scopes
        finally:
            await agent.stop()
            await runtime.stop()


class TestTheCataloguePosture:
    async def test_development_catalogues_on_first_sight(self, monkeypatch):
        runtime, agent, rec = await _register(monkeypatch, enforced=False)
        try:
            catalogue = ScopeRepository().catalogue()
            assert "carrier:quote" in catalogue
            assert "payments:write" in catalogue
            # Catalogued is not granted.
            assert rec.ack.granted_scopes == []
            assert rec.ack.unrecognised_scopes == []
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_enforcing_refuses_and_returns_the_catalogue(self, monkeypatch):
        repo = ScopeRepository()
        repo.add_scope("carrier:quote")
        repo.add_scope("carrier:book")

        runtime, agent, rec = await _register(monkeypatch, enforced=True)
        try:
            # Admitted — one uncatalogued scope narrows the grant rather than
            # refusing an agent whose other capabilities are fine (RFC 0001).
            assert rec.ack.accepted
            assert rec.ack.unrecognised_scopes == ["payments:write"]

            # The refusal is how the vocabulary propagates.
            assert "carrier:quote" in rec.ack.catalogue
            assert "carrier:book" in rec.ack.catalogue
            assert "payments:write" not in ScopeRepository().catalogue()
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_a_successful_registration_does_not_carry_the_catalogue(
        self, monkeypatch
    ):
        """Returning it every time would be noise; it is a correction, not a manifest."""
        repo = ScopeRepository()
        repo.add_scope("carrier:quote")
        repo.add_scope("payments:write")

        runtime, agent, rec = await _register(monkeypatch, enforced=True)
        try:
            assert rec.ack.unrecognised_scopes == []
            assert rec.ack.catalogue == []
        finally:
            await agent.stop()
            await runtime.stop()


class TestTheRequestIsKept:
    async def test_an_uncatalogued_scope_becomes_a_reviewable_request(
        self, monkeypatch
    ):
        ScopeRepository().add_scope("carrier:quote")

        runtime, agent, rec = await _register(monkeypatch, enforced=True)
        try:
            pending = ScopeRepository().pending_requests()

            assert [p.scope for p in pending] == ["payments:write"]
            assert pending[0].agent_id == "carrier-negotiator"
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_a_typo_is_visible_instead_of_silent(self, monkeypatch):
        """The failure that motivated RFC 0003.

        Before this, a misspelt scope registered successfully and every rule
        guarding the correct spelling silently stopped applying. Now it
        surfaces as a request, next to the catalogue that shows the fix.
        """

        class Typo(BaseAgent):
            def capabilities(self):
                return [
                    AgentCapability(
                        capability_id="quote", required_scopes=["carrier:qoute"]
                    )
                ]

            async def execute_task(self, payload, context):
                return {}

        ScopeRepository().add_scope("carrier:quote", "Obtain freight quotes")

        runtime, agent, rec = await _register(
            monkeypatch,
            enforced=True,
            agent=Typo(agent_id="typo-agent", registration_timeout=2.0),
        )
        try:
            assert rec.ack.unrecognised_scopes == ["carrier:qoute"]
            assert "carrier:quote" in rec.ack.catalogue, (
                "the correct spelling must be in the answer, or the agent "
                "author has no way to find it"
            )
            assert rec.ack.granted_scopes == []
        finally:
            await agent.stop()
            await runtime.stop()


async def _eventually(predicate, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False
