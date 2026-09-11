"""Scope matching and the catalogue posture.

The bug this exists to prevent is quiet: `carrier:qoute` used to register
exactly as successfully as `carrier:quote`, and every rule written to
constrain that capability silently stopped applying. Nothing failed. So the
tests that matter are the ones asserting that a name is *not* covered.
"""

from __future__ import annotations

import pytest

from agentic_bus.core.scopes import (
    ScopePolicy,
    covered_by_any,
    covers,
    is_well_formed,
    normalise,
    parent_of,
)


class TestCovers:
    def test_a_scope_covers_itself(self):
        assert covers("payments:write", "payments:write")

    def test_a_wildcard_covers_its_children(self):
        assert covers("payments:*", "payments:write")
        assert covers("payments:*", "payments:refund:approve")

    def test_a_grant_is_not_widened_by_having_children(self):
        # The whole point: holding one permission does not confer its siblings.
        assert not covers("payments:write", "payments:refund")
        assert not covers("payments:write", "payments:write:bulk")
        assert not covers("carrier:quote", "carrier:book")

    def test_a_wildcard_does_not_reach_across_the_hierarchy(self):
        assert not covers("payments:*", "treasury:write")
        assert not covers("payments:*", "payment:write")

    def test_bare_wildcard_covers_everything(self):
        assert covers("*", "anything:at:all")

    def test_a_typo_covers_nothing(self):
        """The failure that motivated the whole RFC."""
        assert not covers("carrier:quote", "carrier:qoute")
        assert not covers("carrier:qoute", "carrier:quote")

    def test_case_and_padding_do_not_create_new_scopes(self):
        assert covers("Payments:Write", " payments:write ")
        assert normalise("  Payments:WRITE ") == "payments:write"

    def test_empty_never_covers(self):
        assert not covers("", "payments:write")
        assert not covers("payments:write", "")

    def test_covered_by_any(self):
        granted = ["carrier:quote", "logistics:*"]
        assert covered_by_any(granted, "logistics:route")
        assert covered_by_any(granted, "carrier:quote")
        assert not covered_by_any(granted, "payments:write")


class TestWellFormed:
    @pytest.mark.parametrize(
        "scope",
        ["payments", "payments:write", "payments:*", "*", "a-b.c_d:e", "x:y:z"],
    )
    def test_accepts_usable_names(self, scope):
        assert is_well_formed(scope)

    @pytest.mark.parametrize(
        "scope",
        ["", "   ", "a::b", ":a", "a:", "pay ments:write", "a:*:b", "a/b", "x" * 200],
    )
    def test_rejects_unusable_names(self, scope):
        assert not is_well_formed(scope)

    def test_a_wildcard_is_only_meaningful_last(self):
        # "a:*:b" would require deciding what a mid-hierarchy wildcard means.
        assert not is_well_formed("a:*:b")
        assert is_well_formed("a:b:*")


class TestParentOf:
    def test_walks_up_one_level(self):
        assert parent_of("payments:refund:approve") == "payments:refund"
        assert parent_of("payments:refund") == "payments"

    def test_the_root_has_no_parent(self):
        assert parent_of("payments") == ""


class TestPolicy:
    CATALOGUE = ["carrier:quote", "carrier:book", "logistics:*"]

    def test_development_catalogues_what_it_does_not_know(self, monkeypatch):
        monkeypatch.delenv("AGBUS_SCOPE_CATALOGUE_ENFORCED", raising=False)
        policy = ScopePolicy()
        assert policy.auto_catalogues

        d = policy.resolve(["carrier:quote", "something:new"], self.CATALOGUE)

        assert d.recognised == ["carrier:quote", "something:new"]
        assert d.catalogued == ["something:new"]
        assert d.unrecognised == []

    def test_enforcing_refuses_what_it_does_not_know(self, monkeypatch):
        monkeypatch.setenv("AGBUS_SCOPE_CATALOGUE_ENFORCED", "true")
        policy = ScopePolicy()
        assert not policy.auto_catalogues

        d = policy.resolve(["carrier:quote", "payments:write"], self.CATALOGUE)

        assert d.recognised == ["carrier:quote"]
        assert d.unrecognised == ["payments:write"]
        assert d.catalogued == []

    def test_a_catalogued_wildcard_recognises_its_children(self):
        d = ScopePolicy(enforced=True).resolve(["logistics:route"], self.CATALOGUE)

        assert d.recognised == ["logistics:route"]
        assert d.unrecognised == []

    def test_malformed_names_are_never_catalogued(self):
        """Development is permissive about vocabulary, not about garbage."""
        d = ScopePolicy(enforced=False).resolve(["a::b", "ok:name"], self.CATALOGUE)

        assert d.malformed == ["a::b"]
        assert "a::b" not in d.catalogued
        assert d.recognised == ["ok:name"]

    def test_duplicates_collapse(self):
        d = ScopePolicy(enforced=True).resolve(
            ["carrier:quote", "CARRIER:QUOTE", " carrier:quote "], self.CATALOGUE
        )

        assert d.recognised == ["carrier:quote"]

    def test_resolving_grants_nothing(self, monkeypatch):
        """Recognised is not granted — that distinction is the RFC.

        A name being in the catalogue means the coordinator knows what it is,
        not that this agent may have it. Granting is a binding an
        administrator authored.
        """
        monkeypatch.delenv("AGBUS_SCOPE_CATALOGUE_ENFORCED", raising=False)
        d = ScopePolicy().resolve(["payments:write"], [])

        # Catalogued in development, yes. Granted, no — there is no grant here
        # to inspect, which is the point.
        assert d.catalogued == ["payments:write"]
        assert not hasattr(d, "granted")
