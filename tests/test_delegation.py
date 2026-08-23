"""The delegation chain: an agent cannot exceed the person it acts for.

This is the link agent protocols are usually criticised for not expressing.
An agent authorised to issue refunds, acting for a user who may not issue
refunds, must not issue a refund — and nothing in a capability registry or a
tool description says so, because the fact lives on the requester's
credential.

Three narrowings, each with a different justification:

    requester's credential  →  what the interaction claimed  →  what this
                                                                agent was bound to

The tests worth reading are the ones where a step is refused *despite* the
agent being perfectly entitled to it in isolation.
"""

from __future__ import annotations

import pytest

from agentic_bus.core.scopes import intersect, narrow
from agentic_bus.core.transport.local import LocalTransport


class TestTheTwoEmptySemantics:
    """The distinction that carries this module, in one place.

    Reading an empty binding the way an empty credential is read would turn
    an unbound capability into an unrestricted one — so they are separate
    functions, and each call site has to say which it means.
    """

    def test_an_empty_ceiling_expresses_no_limit(self):
        assert narrow(["payments:refund"], []) == ["payments:refund"]

    def test_an_empty_grant_grants_nothing(self):
        assert intersect(["payments:refund"], []) == []

    def test_they_agree_whenever_the_bound_is_non_empty(self):
        for requested, bound in (
            (["a:read"], ["a:read"]),
            (["a:read", "b:write"], ["a:*"]),
            (["a:read"], ["b:write"]),
        ):
            assert narrow(requested, bound) == intersect(requested, bound)


class TestNarrow:
    def test_a_ceiling_bounds_what_was_requested(self):
        assert narrow(["a:read", "a:write"], ["a:read"]) == ["a:read"]

    def test_a_hierarchical_ceiling_admits_children(self):
        assert narrow(["payments:refund"], ["payments:*"]) == ["payments:refund"]

    def test_an_empty_ceiling_expresses_no_limit(self):
        """Absence of a claim is not a restriction.

        A credential carrying no `scope` claim usually belongs to an identity
        provider that does not use scopes, not to a holder who may do nothing.
        Reading absence as denial would refuse every caller whose IdP is
        configured differently, to protect nothing.
        """
        assert narrow(["anything"], []) == ["anything"]

    def test_requesting_nothing_yields_nothing(self):
        assert narrow([], ["a:read"]) == []

    def test_a_ceiling_cannot_add(self):
        """Narrowing only removes. A ceiling is not a grant."""
        assert narrow(["a:read"], ["a:read", "b:write"]) == ["a:read"]


@pytest.fixture
async def runtime():
    from agentic_bus.coordinator.runtime import CoordinatorRuntime

    rt = CoordinatorRuntime(transport=LocalTransport())
    await rt.start()
    yield rt
    await rt.stop()


class TestTheGrantHandedToAnAgent:
    async def test_without_enforcement_the_capability_passes_through(
        self, runtime, monkeypatch
    ):
        """Narrowing to bindings nobody authored yet would refuse working systems."""
        runtime._scope_enforcement = False

        grant = runtime._grant_for("carrier", "book", ["payments:refund"])

        assert grant == ["payments:refund"]

    async def test_with_enforcement_the_binding_bounds_it(self, runtime):
        from agentic_bus.core.persistence.scope_repository import ScopeRepository

        runtime._scope_enforcement = True
        repo = ScopeRepository()
        repo.add_scope("carrier:quote")
        repo.bind("carrier", "book", ["carrier:quote"])

        # The interaction claimed a refund; this agent was never bound to one.
        grant = runtime._grant_for(
            "carrier", "book", ["payments:refund", "carrier:quote"]
        )

        assert grant == ["carrier:quote"]

    async def test_an_unbound_capability_is_granted_nothing_under_enforcement(
        self, runtime
    ):
        runtime._scope_enforcement = True

        assert runtime._grant_for("carrier", "book", ["payments:refund"]) == []

    async def test_a_capability_expressing_no_constraint_yields_the_binding(
        self, runtime
    ):
        """Not an intersection with nothing — the binding is the whole authority."""
        from agentic_bus.core.persistence.scope_repository import ScopeRepository

        runtime._scope_enforcement = True
        repo = ScopeRepository()
        repo.add_scope("carrier:quote")
        repo.bind("carrier", "quote", ["carrier:quote"])

        assert runtime._grant_for("carrier", "quote", []) == ["carrier:quote"]


class TestTheRequesterIsTheCeiling:
    """The case the whole chain exists for."""

    def test_an_agent_cannot_exceed_the_person_it_acts_for(self):
        # The agent is bound to refunds and the interaction asked for one…
        claimed = ["payments:refund"]
        # …but the requester's credential does not carry it.
        requester_authority = ["orders:read"]

        assert narrow(claimed, requester_authority) == []

    def test_a_requester_who_holds_it_passes_it_through(self):
        assert narrow(["payments:refund"], ["payments:*", "orders:read"]) == [
            "payments:refund"
        ]

    async def test_a_session_records_the_authority_as_a_derived_fact(self, runtime):
        """From the verified connection, so the requester cannot widen it by asking."""
        session = runtime.sessions.create(requester_id="u1", oidc_subject="auth0|1")

        assert session.requester_authority == []

        session.requester_authority = ["orders:read"]
        assert runtime.sessions.get(session.session_id).requester_authority == [
            "orders:read"
        ]
