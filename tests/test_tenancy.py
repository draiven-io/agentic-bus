"""Tenant isolation on the coordination path.

The data model has had tenants since the beginning and nothing here consulted
them: the registry was global, and discovery handed every registered agent's
description to a language model.

Two failures, and the second is the one people forget. The model could *pick*
another tenant's agent — and it *saw* them, which is disclosure regardless of
what it then picked. A capability description names things ("query ACME Corp's
payroll database"), so filtering candidates after the fact is too late.

Every assertion here is about an agent *not* being visible. A bus that leaks
passes any test that only checks the happy path.
"""

from __future__ import annotations

import pytest

from agentic_bus.core.persistence.tenant_repository import TenantRepository
from agentic_bus.core.persistence.user_repository import UserRepository
from agentic_bus.core.registry.capability_registry import (
    AgentCapability,
    AgentRegistration,
    CapabilityRegistry,
)
from agentic_bus.core.tenancy import TenantResolver, TenantScope
from agentic_bus.core.transport.local import LocalTransport


@pytest.fixture
def tenants():
    """Two customers, each with a user and an agent."""
    trepo, urepo = TenantRepository(), UserRepository()

    acme = trepo.create(slug="acme", name="ACME Corp")
    globex = trepo.create(slug="globex", name="Globex")

    alice = urepo.create(subject="auth0|alice", email="alice@acme.example")
    bob = urepo.create(subject="auth0|bob", email="bob@globex.example")
    urepo.assign_tenant(alice.id, acme.id)
    urepo.assign_tenant(bob.id, globex.id)

    trepo.assign_agent("acme-payroll", acme.id)
    trepo.assign_agent("globex-payroll", globex.id)

    return {
        "acme": acme.id,
        "globex": globex.id,
        "resolver": TenantResolver(user_repo=urepo, tenant_repo=trepo),
    }


class TestResolvingAScope:
    def test_an_enrolled_subject_resolves_to_its_tenants(self, tenants):
        scope = tenants["resolver"].scope_for("auth0|alice")

        assert scope.tenant_ids == [tenants["acme"]]
        assert scope.is_resolved

    def test_an_unknown_subject_resolves_to_nothing(self, tenants):
        """Not to everything. A subject nobody enrolled belongs nowhere."""
        scope = tenants["resolver"].scope_for("auth0|stranger")

        assert scope.tenant_ids == []
        assert not scope.is_resolved

    def test_an_absent_subject_resolves_to_nothing(self, tenants):
        assert tenants["resolver"].scope_for("").tenant_ids == []

    def test_a_single_tenant_is_named_for_the_manifest(self, tenants):
        scope = tenants["resolver"].scope_for("auth0|alice")

        assert scope.single_tenant_id == str(tenants["acme"])

    def test_membership_of_several_names_none(self, tenants):
        """Picking one arbitrarily would fire a boundary rule for a tenant
        nobody chose."""
        scope = TenantScope(tenant_ids=[1, 2])

        assert scope.single_tenant_id == ""


class TestVisibility:
    def test_a_requester_sees_its_own_tenant_s_agent(self, tenants):
        scope = tenants["resolver"].scope_for("auth0|alice")

        visible = tenants["resolver"].visible_agents(
            scope, ["acme-payroll", "globex-payroll"]
        )

        assert visible == ["acme-payroll"]

    def test_a_requester_does_not_see_another_tenant_s_agent(self, tenants):
        """The whole point."""
        scope = tenants["resolver"].scope_for("auth0|bob")

        visible = tenants["resolver"].visible_agents(
            scope, ["acme-payroll", "globex-payroll"]
        )

        assert "acme-payroll" not in visible

    def test_an_unassigned_agent_is_global(self, tenants):
        """How single-tenant deployments keep working without a flag."""
        scope = tenants["resolver"].scope_for("auth0|alice")

        visible = tenants["resolver"].visible_agents(scope, ["shared-translator"])

        assert visible == ["shared-translator"]

    def test_an_unidentified_requester_sees_only_global_agents(self, tenants):
        scope = tenants["resolver"].scope_for("auth0|stranger")

        visible = tenants["resolver"].visible_agents(
            scope, ["acme-payroll", "shared-translator"]
        )

        assert visible == ["shared-translator"]

    def test_tenancy_is_detected_by_assignment_not_by_a_flag(self, tenants):
        resolver = tenants["resolver"]

        assert resolver.any_agent_is_assigned(["acme-payroll"])
        assert not resolver.any_agent_is_assigned(["shared-translator"])


class TestTheRegistryFiltersBeforeSummarising:
    """After the fact would be too late: the description is already in a prompt."""

    def _registry(self):
        registry = CapabilityRegistry()
        for agent_id, description in (
            ("acme-payroll", "Query ACME Corp's payroll database"),
            ("globex-payroll", "Query Globex payroll"),
        ):
            registry.register(
                AgentRegistration(
                    agent_id=agent_id,
                    semantic_description=description,
                    capabilities=[AgentCapability(capability_id="query")],
                )
            )
        return registry

    def test_unfiltered_summaries_include_everything(self):
        assert len(self._registry().capability_summaries()) == 2

    def test_a_bound_excludes_the_other_tenant_entirely(self):
        summaries = self._registry().capability_summaries(only=["acme-payroll"])

        assert [s["agent_id"] for s in summaries] == ["acme-payroll"]
        # Not merely absent from the result — absent from the text a model sees.
        assert "Globex" not in str(summaries)

    def test_an_empty_bound_shows_nothing(self):
        """Distinct from None. A requester who may see nothing sees nothing."""
        assert self._registry().capability_summaries(only=[]) == []

    def test_none_means_no_restriction(self):
        assert len(self._registry().capability_summaries(only=None)) == 2


@pytest.fixture
async def runtime():
    from agentic_bus.coordinator.runtime import CoordinatorRuntime

    rt = CoordinatorRuntime(transport=LocalTransport())
    await rt.start()
    yield rt
    await rt.stop()


class TestTheCoordinatorApplies:
    async def test_a_bus_without_tenancy_is_unrestricted(self, runtime):
        """No assignments anywhere: the filter must be the identity function."""
        runtime.registry.register(
            AgentRegistration(agent_id="translator", capabilities=[])
        )
        session = runtime.sessions.create(requester_id="u1")

        assert runtime._visible_agents(session) is None

    async def test_a_session_is_bounded_once_agents_are_assigned(
        self, runtime, tenants
    ):
        for agent_id in ("acme-payroll", "globex-payroll", "shared-translator"):
            runtime.registry.register(
                AgentRegistration(agent_id=agent_id, capabilities=[])
            )

        session = runtime.sessions.create(
            requester_id="alice", oidc_subject="auth0|alice"
        )
        session.tenant_ids = [tenants["acme"]]

        visible = runtime._visible_agents(session)

        assert "acme-payroll" in visible
        assert "shared-translator" in visible
        assert "globex-payroll" not in visible

    async def test_a_session_with_no_tenant_sees_only_global_agents(
        self, runtime, tenants
    ):
        for agent_id in ("acme-payroll", "shared-translator"):
            runtime.registry.register(
                AgentRegistration(agent_id=agent_id, capabilities=[])
            )

        session = runtime.sessions.create(requester_id="anon")

        assert runtime._visible_agents(session) == ["shared-translator"]

    async def test_the_manifest_carries_the_tenant(self, runtime, tenants):
        """Populating this is what lets a boundary rule reading it fire at all."""
        from agentic_bus.core.ibac.engine import IBACEvaluationPoint

        session = runtime.sessions.create(
            requester_id="alice", oidc_subject="auth0|alice"
        )
        session.tenant_ids = [tenants["acme"]]

        manifest = runtime._build_manifest(
            evaluation_point=IBACEvaluationPoint.ARTIFACT_EMISSION, session=session
        )

        assert manifest.derived.tenant_id == str(tenants["acme"])
