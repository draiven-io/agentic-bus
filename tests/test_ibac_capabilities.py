"""An IBAC approval becomes bounded authority, and something checks it.

Before this, an ALLOW governed only whether execution *started*: the returned
constraints went to the audit log and were dropped, and the execute message
carried ``authorized_scopes: []``. An intention approved for "analyse sales"
and one approved for "export everything" produced identical authority.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentic_bus.core.ibac.capability import DEFAULT_TTL_SECONDS, Capability
from agentic_bus.core.session.manager import SessionManager


def _at(seconds_from_now: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)


class TestIssuing:
    def test_a_capability_expires(self):
        cap = Capability.issue(session_id="s1")
        assert cap.expires_at, "a grant with no expiry is not bounded authority"
        assert not cap.is_expired()

    def test_default_lifetime_is_bounded(self):
        cap = Capability.issue(session_id="s1")
        assert cap.is_expired(_at(DEFAULT_TTL_SECONDS + 60))

    def test_constraints_carry_through_from_the_decision(self):
        cap = Capability.issue(
            session_id="s1", constraints={"external_disclosure": False}
        )
        assert cap.forbids_external_disclosure()


class TestExpiry:
    def test_an_expired_capability_refuses(self):
        cap = Capability.issue(session_id="s1", ttl_seconds=1)
        violation = cap.check(now=_at(120))

        assert violation is not None
        assert "expired" in violation.reason

    def test_a_long_flow_can_outlive_its_approval(self):
        """The case the per-dispatch check exists for.

        A multi-step plan authorised once at the start can still be running
        long afterwards; the approval should not stretch to cover it.
        """
        cap = Capability.issue(session_id="s1", ttl_seconds=60)
        assert cap.check(now=_at(30)) is None      # step 1, still valid
        assert cap.check(now=_at(600)) is not None  # step 7, no longer

    def test_an_unparseable_expiry_is_treated_as_expired(self):
        """A capability whose lifetime cannot be established has none."""
        cap = Capability(session_id="s1", expires_at="not-a-timestamp")
        assert cap.is_expired()


class TestPrincipals:
    def test_an_agent_outside_the_grant_is_refused(self):
        cap = Capability.issue(session_id="s1", principals=["router", "warehouse"])
        violation = cap.check(principal="exfiltrator")

        assert violation is not None
        assert "exfiltrator" in violation.reason
        assert "router" in violation.reason, "the refusal should say who *is* covered"

    def test_a_named_agent_is_permitted(self):
        cap = Capability.issue(session_id="s1", principals=["router"])
        assert cap.check(principal="router") is None

    def test_an_empty_principal_list_covers_any_participant(self):
        """The approval was for the intention, not for a particular agent."""
        cap = Capability.issue(session_id="s1", principals=[])
        assert cap.check(principal="anyone") is None


class TestScopes:
    def test_a_scope_outside_the_grant_is_refused(self):
        cap = Capability.issue(session_id="s1", scopes=["sales.read"])
        violation = cap.check(scopes=["hr.read"])

        assert violation is not None
        assert "hr.read" in violation.reason

    def test_granted_scopes_pass(self):
        cap = Capability.issue(session_id="s1", scopes=["sales.read", "sales.analyze"])
        assert cap.check(scopes=["sales.read", "sales.analyze"]) is None

    def test_one_bad_scope_among_good_ones_still_refuses(self):
        cap = Capability.issue(session_id="s1", scopes=["sales.read"])
        assert cap.check(scopes=["sales.read", "hr.read"]) is not None


class TestViolationsAreExplained:
    def test_a_refusal_carries_a_reason_and_the_capability_id(self):
        """A refusal that cannot be explained surfaces as an unexplained
        failure, and cannot be audited."""
        cap = Capability.issue(session_id="s1", scopes=["a"])
        violation = cap.check(scopes=["b"])

        assert violation.reason
        assert violation.capability_id == cap.capability_id


class TestSessionIntegration:
    def test_a_session_starts_without_a_capability(self):
        session = SessionManager().create("requester-1")
        assert session.capability is None, (
            "authority should exist only once something has approved it"
        )

    def test_a_capability_can_be_attached_to_a_session(self):
        manager = SessionManager()
        session = manager.create("requester-1")
        session.capability = Capability.issue(
            session_id=session.session_id, scopes=["sales.read"]
        )

        assert manager.get(session.session_id).capability.scopes == ["sales.read"]


class TestAuditSummary:
    def test_the_summary_records_the_bounds(self):
        cap = Capability.issue(
            session_id="s1",
            purpose="customer_retention",
            principals=["retention-agent"],
            scopes=["customer.profile"],
            constraints={"external_disclosure": False},
        )
        summary = cap.audit_summary()

        assert summary["purpose"] == "customer_retention"
        assert summary["scopes"] == ["customer.profile"]
        assert summary["constraints"]["external_disclosure"] is False
        assert summary["expires_at"]
