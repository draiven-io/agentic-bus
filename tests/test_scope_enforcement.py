"""The execution guard: does the agent hold what its capability needs?

Two defects motivated this file, and both were the same shape — a check that
looked present and ran over nothing.

`capability.check(principal=agent_id)` was the only call site, so the loop
comparing scopes iterated an empty list and the capability's own constraint
never applied. And nothing anywhere compared what an agent was granted against
what it said it needed.

So the tests that matter here are the ones proving a refusal actually happens.
A guard that passes everything passes these too, unless they assert the refusal.
"""

from __future__ import annotations

import pytest

from agentic_bus.core.ibac.capability import Capability
from agentic_bus.core.persistence.scope_repository import ScopeRepository
from agentic_bus.core.registry.capability_registry import (
    AgentCapability,
    AgentRegistration,
)
from agentic_bus.core.scopes import scope_enforcement_enabled
from agentic_bus.core.transport.local import LocalTransport


@pytest.fixture
async def runtime():
    from agentic_bus.coordinator.runtime import CoordinatorRuntime

    rt = CoordinatorRuntime(transport=LocalTransport())
    await rt.start()
    yield rt
    await rt.stop()


def _register(runtime, agent_id: str, capability_id: str, scopes: list[str]):
    """Put an agent in the registry, as a real registration would."""
    runtime.registry.register(
        AgentRegistration(
            agent_id=agent_id,
            capabilities=[
                AgentCapability(capability_id=capability_id, required_scopes=scopes)
            ],
        )
    )


class TestDeclaredScopes:
    async def test_reads_what_the_agent_declared_for_that_capability(self, runtime):
        _register(runtime, "carrier", "quote", ["carrier:quote"])

        assert runtime._declared_scopes("carrier", "quote") == ["carrier:quote"]

    async def test_a_capability_that_was_never_registered_declares_nothing(self, runtime):
        assert runtime._declared_scopes("nobody", "nothing") == []

    async def test_capabilities_are_independent(self, runtime):
        """The same agent can appear twice in a plan holding different scopes."""
        runtime.registry.register(
            AgentRegistration(
                agent_id="carrier",
                capabilities=[
                    AgentCapability(capability_id="quote", required_scopes=["carrier:quote"]),
                    AgentCapability(capability_id="book", required_scopes=["payments:write"]),
                ],
            )
        )

        assert runtime._declared_scopes("carrier", "quote") == ["carrier:quote"]
        assert runtime._declared_scopes("carrier", "book") == ["payments:write"]


class TestUngrantedScopes:
    async def test_an_unbound_capability_is_missing_everything(self, runtime):
        """The default that makes this guard worth having."""
        missing = runtime._ungranted_scopes("carrier", "quote", ["carrier:quote"])

        assert missing == ["carrier:quote"]

    async def test_a_bound_capability_is_missing_nothing(self, runtime):
        repo = ScopeRepository()
        repo.add_scope("carrier:quote")
        repo.bind("carrier", "quote", ["carrier:quote"])

        assert runtime._ungranted_scopes("carrier", "quote", ["carrier:quote"]) == []

    async def test_a_wildcard_grant_covers_a_specific_requirement(self, runtime):
        repo = ScopeRepository()
        repo.add_scope("carrier:*")
        repo.bind("carrier", "quote", ["carrier:*"])

        assert runtime._ungranted_scopes("carrier", "quote", ["carrier:quote"]) == []

    async def test_a_grant_does_not_cover_its_neighbours(self, runtime):
        repo = ScopeRepository()
        repo.add_scope("carrier:quote")
        repo.add_scope("payments:write")
        repo.bind("carrier", "book", ["carrier:quote"])

        missing = runtime._ungranted_scopes(
            "carrier", "book", ["carrier:quote", "payments:write"]
        )

        assert missing == ["payments:write"]

    async def test_declaring_nothing_requires_nothing(self, runtime):
        assert runtime._ungranted_scopes("carrier", "quote", []) == []

    async def test_a_binding_for_another_capability_does_not_count(self, runtime):
        """Grants are per capability, not per agent."""
        repo = ScopeRepository()
        repo.add_scope("payments:write")
        repo.bind("carrier", "quote", ["payments:write"])

        assert runtime._ungranted_scopes("carrier", "book", ["payments:write"]) == [
            "payments:write"
        ]


class TestTheCapabilityConstraintNowApplies:
    """The one-line defect: check() was called without the scopes to check."""

    def test_scopes_are_compared_when_passed(self):
        capability = Capability.issue(session_id="s1", scopes=["carrier:quote"])

        assert capability.check(scopes=["carrier:quote"]) is None

        violation = capability.check(scopes=["payments:write"])
        assert violation is not None
        assert "payments:write" in violation.reason

    def test_passing_no_scopes_checks_no_scopes(self):
        """Which is exactly why the old call site enforced nothing."""
        capability = Capability.issue(session_id="s1", scopes=["carrier:quote"])

        assert capability.check(principal="") is None
        assert capability.check(scopes=[]) is None

    def test_an_empty_grant_expresses_no_constraint(self):
        """Deliberate: an empty list is *not expressing* a scope constraint.

        The grant that does carry a default lives in the bindings, where empty
        means nothing was granted. Keeping the two separate is what lets this
        one stay permissive safely.
        """
        capability = Capability.issue(session_id="s1", scopes=[])

        assert capability.check(scopes=["anything:at:all"]) is None


class TestPosture:
    def test_enforcement_follows_the_catalogue_by_default(self, monkeypatch):
        monkeypatch.delenv("AGBUS_SCOPE_ENFORCED", raising=False)

        assert scope_enforcement_enabled(default=True) is True
        assert scope_enforcement_enabled(default=False) is False

    def test_it_can_be_turned_on_separately(self, monkeypatch):
        """Binding every capability takes longer than deciding to."""
        monkeypatch.setenv("AGBUS_SCOPE_ENFORCED", "true")

        assert scope_enforcement_enabled(default=False) is True

    def test_it_can_be_turned_off_separately(self, monkeypatch):
        monkeypatch.setenv("AGBUS_SCOPE_ENFORCED", "false")

        assert scope_enforcement_enabled(default=True) is False


class TestTheGuardActuallyFires:
    """The integration that matters: the executor refusing to dispatch.

    Everything above tests the helpers. This drives the real execution node,
    because the original defect was not a wrong comparison — it was a
    comparison that never ran, and only the call site shows that.
    """

    async def _execute(self, runtime, agent_id="carrier", capability_id="book"):
        executor = runtime._make_ws_executor(agent_id)
        return await executor(
            {
                "session_id": "s1",
                "_current_step_index": 0,
                "_capability_id": capability_id,
                "intent_text": "book capacity",
            }
        )

    async def test_enforcing_refuses_a_step_the_agent_was_not_granted(
        self, runtime, monkeypatch
    ):
        monkeypatch.setenv("AGBUS_SCOPE_ENFORCED", "true")
        runtime._scope_enforcement = True
        _register(runtime, "carrier", "book", ["payments:write"])

        with pytest.raises(PermissionError, match="payments:write"):
            await self._execute(runtime)

    async def test_a_granted_step_gets_past_the_guard(self, runtime, monkeypatch):
        """Past the scope guard, and on to failing for want of a connection.

        That second failure is the proof: the guard is no longer what stops it.
        """
        monkeypatch.setenv("AGBUS_SCOPE_ENFORCED", "true")
        runtime._scope_enforcement = True
        _register(runtime, "carrier", "book", ["payments:write"])

        repo = ScopeRepository()
        repo.add_scope("payments:write")
        repo.bind("carrier", "book", ["payments:write"])

        with pytest.raises(RuntimeError, match="not connected"):
            await self._execute(runtime)

    async def test_not_enforcing_warns_and_continues(self, runtime, monkeypatch, caplog):
        """A running deployment can see what enforcement would refuse."""
        monkeypatch.setenv("AGBUS_SCOPE_ENFORCED", "false")
        runtime._scope_enforcement = False
        _register(runtime, "carrier", "book", ["payments:write"])

        import logging

        with caplog.at_level(logging.WARNING):
            with pytest.raises(RuntimeError, match="not connected"):
                await self._execute(runtime)

        assert any(
            "payments:write" in r.message and "enforcement is off" in r.message
            for r in caplog.records
        ), "an ungranted step ran with no warning"

    async def test_an_agent_declaring_nothing_is_not_blocked(self, runtime, monkeypatch):
        """Most agents declare no scopes; enforcement must not brick them."""
        monkeypatch.setenv("AGBUS_SCOPE_ENFORCED", "true")
        runtime._scope_enforcement = True
        _register(runtime, "carrier", "book", [])

        with pytest.raises(RuntimeError, match="not connected"):
            await self._execute(runtime)
