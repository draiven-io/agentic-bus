"""The scope catalogue, its bindings, and the request queue.

The property under test throughout is the one RFC 0003 turns on: **a binding
is the authority, and an agent's declaration never is.** So the important
assertions are about what is *not* granted.
"""

from __future__ import annotations

import pytest

from agentic_bus.core.persistence.scope_repository import ScopeRepository


@pytest.fixture
def repo():
    return ScopeRepository()


class TestCatalogue:
    def test_a_scope_can_be_added_and_listed(self, repo):
        assert repo.add_scope("carrier:quote", "Obtain freight quotes")
        assert repo.catalogue() == ["carrier:quote"]

    def test_adding_twice_is_not_an_error(self, repo):
        assert repo.add_scope("carrier:quote")
        assert repo.add_scope("carrier:quote") is False

    def test_a_malformed_name_is_refused(self, repo):
        """A catalogue entry nothing can match looks like coverage."""
        with pytest.raises(ValueError, match="not a usable scope name"):
            repo.add_scope("a::b")

    def test_names_are_normalised_on_the_way_in(self, repo):
        repo.add_scope("  Carrier:QUOTE ")
        assert repo.catalogue() == ["carrier:quote"]

    def test_recognises_matches_hierarchically(self, repo):
        repo.add_scope("logistics:*")

        assert repo.recognises("logistics:route")
        assert not repo.recognises("payments:write")

    def test_removing_a_scope_removes_the_bindings_that_granted_it(self, repo):
        repo.add_scope("payments:write")
        repo.bind("finance-agent", "pay", ["payments:write"])
        assert repo.granted("finance-agent", "pay") == ["payments:write"]

        repo.remove_scope("payments:write")

        # A binding to an undefined name would be a grant of something nobody
        # has defined, which is worse than no grant.
        assert repo.granted("finance-agent", "pay") == []


class TestBindings:
    def test_an_unbound_capability_holds_nothing(self, repo):
        """The default that makes the whole design safe."""
        assert repo.granted("some-agent", "some-capability") == []

    def test_binding_grants(self, repo):
        repo.add_scope("carrier:quote")

        newly = repo.bind("carrier-negotiator", "quote", ["carrier:quote"])

        assert newly == ["carrier:quote"]
        assert repo.granted("carrier-negotiator", "quote") == ["carrier:quote"]

    def test_binding_is_idempotent(self, repo):
        repo.add_scope("carrier:quote")
        repo.bind("a", "c", ["carrier:quote"])

        assert repo.bind("a", "c", ["carrier:quote"]) == []
        assert repo.granted("a", "c") == ["carrier:quote"]

    def test_cannot_bind_a_scope_the_catalogue_does_not_have(self, repo):
        """Binding records a decision; a decision about an undefined name is not one."""
        with pytest.raises(ValueError, match="not in the catalogue"):
            repo.bind("a", "c", ["payments:write"])

        assert repo.granted("a", "c") == []

    def test_a_catalogued_wildcard_admits_a_specific_binding(self, repo):
        repo.add_scope("logistics:*")

        repo.bind("router", "route", ["logistics:route"])

        assert repo.granted("router", "route") == ["logistics:route"]

    def test_bindings_are_per_capability_not_per_agent(self, repo):
        """An agent holding one permission does not hold its neighbours'."""
        repo.add_scope("carrier:quote")
        repo.add_scope("carrier:book")
        repo.bind("carrier-negotiator", "quote", ["carrier:quote"])
        repo.bind("carrier-negotiator", "book", ["carrier:book"])

        assert repo.granted("carrier-negotiator", "quote") == ["carrier:quote"]
        assert repo.granted("carrier-negotiator", "book") == ["carrier:book"]

    def test_unbinding(self, repo):
        repo.add_scope("carrier:quote")
        repo.bind("a", "c", ["carrier:quote"])

        assert repo.unbind("a", "c", "carrier:quote")
        assert repo.granted("a", "c") == []
        assert repo.unbind("a", "c", "carrier:quote") is False

    def test_granted_for_agent_groups_by_capability(self, repo):
        repo.add_scope("carrier:quote")
        repo.add_scope("carrier:book")
        repo.bind("neg", "quote", ["carrier:quote"])
        repo.bind("neg", "book", ["carrier:book"])

        assert repo.granted_for_agent("neg") == {
            "quote": ["carrier:quote"],
            "book": ["carrier:book"],
        }

    def test_unbind_agent_drops_everything(self, repo):
        repo.add_scope("carrier:quote")
        repo.bind("neg", "quote", ["carrier:quote"])

        assert repo.unbind_agent("neg") == 1
        assert repo.granted_for_agent("neg") == {}


class TestRequests:
    def test_a_request_is_recorded_rather_than_discarded(self, repo):
        repo.record_request("carrier-negotiator", "payments:write", "book")

        pending = repo.pending_requests()
        assert len(pending) == 1
        assert pending[0].scope == "payments:write"
        assert pending[0].agent_id == "carrier-negotiator"
        assert pending[0].request_count == 1

    def test_asking_again_increments_rather_than_duplicating(self, repo):
        for _ in range(3):
            repo.record_request("a", "payments:write", "c")

        pending = repo.pending_requests()
        assert len(pending) == 1
        assert pending[0].request_count == 3

    def test_cataloguing_a_scope_clears_it_from_pending(self, repo):
        repo.record_request("a", "payments:write", "c")
        assert len(repo.pending_requests()) == 1

        repo.add_scope("payments:write")

        # Filtered, not deleted: the record of who asked survives.
        assert repo.pending_requests() == []

    def test_most_asked_first(self, repo):
        repo.record_request("a", "rare:scope")
        for _ in range(5):
            repo.record_request("b", "common:scope")

        pending = repo.pending_requests()
        assert [p.scope for p in pending] == ["common:scope", "rare:scope"]
