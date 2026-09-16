"""Enforcing a grant inside the agent, and reconciling it outside.

Be precise about what this defends, because overstating it would be worse than
not having it:

**Not** a malicious agent binary. Code that controls the process can call
anything and report anything, and nothing running in that process could stop
it.

**Yes** a compromised agent brain — the realistic threat when a language model
drives the agent. An injected prompt can persuade the model to call
``send_email``; it cannot persuade the invocation path to skip the guard,
because the guard is not in the model's control.

The tests that carry that claim are the ones showing a *use* recorded even when
the call was refused, and reconciliation catching use beyond the grant.
"""

from __future__ import annotations

import asyncio

import pytest

from agentic_bus.agents.scope_guard import (
    ScopeDenied,
    ScopeGrant,
    current_grant,
    require_scope,
    reset_grant,
    scope_is_held,
    ScopedResource,
    set_grant,
)


class TestTheGrant:
    def test_a_held_scope_passes(self):
        grant = ScopeGrant(granted=["payments:write"])

        grant.require("payments:write")

        assert grant.used == ["payments:write"]
        assert grant.denied == []

    def test_a_scope_not_held_is_refused(self):
        grant = ScopeGrant(granted=["carrier:quote"])

        with pytest.raises(ScopeDenied) as exc:
            grant.require("payments:write")

        assert exc.value.scope == "payments:write"
        assert exc.value.granted == ["carrier:quote"]

    def test_a_refused_attempt_is_still_recorded(self):
        """The more interesting half: what it *tried* to do."""
        grant = ScopeGrant(granted=[])

        with pytest.raises(ScopeDenied):
            grant.require("payments:write")

        assert grant.used == ["payments:write"]
        assert grant.denied == ["payments:write"]

    def test_a_wildcard_grant_covers_its_children(self):
        grant = ScopeGrant(granted=["payments:*"])

        grant.require("payments:refund")

        assert grant.denied == []

    def test_an_empty_grant_holds_nothing(self):
        grant = ScopeGrant(granted=[])

        assert not grant.permits("anything")

    def test_repeated_use_is_recorded_once(self):
        grant = ScopeGrant(granted=["a:b"])

        grant.require("a:b")
        grant.require("a:b")

        assert grant.used == ["a:b"]

    def test_a_denied_scope_subclasses_permission_error(self):
        """So an agent catching broad permission failures behaves sensibly."""
        assert issubclass(ScopeDenied, PermissionError)


class TestTheContextVariable:
    def test_require_scope_uses_the_installed_grant(self):
        grant = ScopeGrant(granted=["carrier:quote"])
        token = set_grant(grant)
        try:
            require_scope("carrier:quote")
            with pytest.raises(ScopeDenied):
                require_scope("payments:write")
        finally:
            reset_grant(token)

        assert grant.used == ["carrier:quote", "payments:write"]

    def test_outside_an_execution_nothing_is_checked(self):
        """A process with no grant is not one an attacker reached through the bus.

        Refusing here would break every test, script and local run to protect
        nothing.
        """
        assert current_grant() is None
        require_scope("payments:write")  # must not raise

    async def test_concurrent_sessions_cannot_see_each_others_grant(self):
        """asyncio gives each task its own value, and that is load-bearing."""
        seen: dict[str, list[str]] = {}

        async def run(name: str, granted: list[str]):
            grant = ScopeGrant(session_id=name, granted=granted)
            token = set_grant(grant)
            try:
                await asyncio.sleep(0.01)  # force interleaving
                seen[name] = list(current_grant().granted)
            finally:
                reset_grant(token)

        await asyncio.gather(
            run("a", ["carrier:quote"]),
            run("b", ["payments:write"]),
        )

        assert seen == {"a": ["carrier:quote"], "b": ["payments:write"]}


class TestScopeIsHeld:
    def test_reports_without_raising(self):
        grant = ScopeGrant(granted=["carrier:quote"])
        token = set_grant(grant)
        try:
            assert scope_is_held("carrier:quote")
            assert not scope_is_held("payments:write")
        finally:
            reset_grant(token)

    def test_the_use_is_still_recorded(self):
        """Choosing a narrower path is still a decision the grant shaped."""
        grant = ScopeGrant(granted=["carrier:quote"])
        token = set_grant(grant)
        try:
            scope_is_held("payments:write")
        finally:
            reset_grant(token)

        assert "payments:write" in grant.used


class TestAScopedResource:
    """Binding the scope to the credential rather than to a remembered call.

    The weakness these cover is not that ``require_scope`` is wrong — it is
    that omitting it produces working, unguarded code, and an empty usage
    report is indistinguishable from an execution that needed nothing. Here
    omitting the check leaves nothing to call instead.
    """

    def _resource(self, scope="crm:read"):
        calls = []

        def factory():
            calls.append(1)
            return {"client": "crm"}

        return ScopedResource(scope, factory), calls

    def test_a_held_scope_hands_out_the_client(self):
        resource, _ = self._resource()
        token = set_grant(ScopeGrant(granted=["crm:read"]))
        try:
            assert resource.get() == {"client": "crm"}
        finally:
            reset_grant(token)

    def test_a_scope_not_held_refuses_the_client(self):
        """The whole point: no client, not an unchecked one."""
        resource, _ = self._resource()
        token = set_grant(ScopeGrant(granted=["crm:write"]))
        try:
            with pytest.raises(ScopeDenied):
                resource.get()
        finally:
            reset_grant(token)

    def test_a_scope_never_granted_is_a_connection_never_opened(self):
        """The factory must not run on the refused path.

        Constructing the client is what opens the socket and presents the
        credential; doing that before the check would leak the very thing the
        check exists to gate.
        """
        resource, calls = self._resource()
        token = set_grant(ScopeGrant(granted=[]))
        try:
            with pytest.raises(ScopeDenied):
                resource.get()
        finally:
            reset_grant(token)

        assert calls == []
        assert resource.is_built is False

    def test_the_refusal_is_recorded_as_use(self):
        """So reconciliation sees the attempt, not just the absence of one."""
        resource, _ = self._resource()
        grant = ScopeGrant(granted=["crm:write"])
        token = set_grant(grant)
        try:
            with pytest.raises(ScopeDenied):
                resource.get()
        finally:
            reset_grant(token)

        assert grant.used == ["crm:read"]
        assert grant.denied == ["crm:read"]

    def test_the_factory_runs_once_across_calls(self):
        resource, calls = self._resource()
        token = set_grant(ScopeGrant(granted=["crm:read"]))
        try:
            first, second = resource.get(), resource.get()
        finally:
            reset_grant(token)

        assert first is second
        assert calls == [1]

    def test_a_cached_client_is_still_refused_once_the_grant_stops_covering(self):
        """Caching the value must not cache the decision.

        An execution that held the scope earlier does not entitle a later one
        that does not — the client is per-agent, the authority is per-execution.
        """
        resource, _ = self._resource()

        token = set_grant(ScopeGrant(granted=["crm:read"]))
        try:
            resource.get()
        finally:
            reset_grant(token)

        token = set_grant(ScopeGrant(granted=["unrelated:scope"]))
        try:
            with pytest.raises(ScopeDenied):
                resource.get()
        finally:
            reset_grant(token)

    def test_a_wildcard_grant_covers_it(self):
        resource, _ = self._resource("crm:read")
        token = set_grant(ScopeGrant(granted=["crm:*"]))
        try:
            assert resource.get() == {"client": "crm"}
        finally:
            reset_grant(token)

    def test_outside_an_execution_it_hands_the_client_over(self):
        """Consistent with require_scope: a process with no grant is not one
        an attacker reached through the bus."""
        resource, _ = self._resource()

        assert current_grant() is None
        assert resource.get() == {"client": "crm"}

    def test_the_scope_is_readable_and_not_settable(self):
        resource, _ = self._resource("payments:refund")

        assert resource.scope == "payments:refund"
        with pytest.raises(AttributeError):
            resource.scope = "payments:*"  # type: ignore[misc]
