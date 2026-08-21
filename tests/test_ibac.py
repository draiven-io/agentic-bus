"""Tests for the IBAC engine."""

from agentic_bus.core.ibac.engine import (
    IBACEngine,
    IBACPolicy,
    IBACRequest,
    IBACDecision,
    IBACEvaluationPoint,
)


class TestIBACEngine:
    """Verify IBAC governance at all evaluation points (§6 of AGENTS.md)."""

    def test_default_allow(self):
        """No policies → default allow."""
        engine = IBACEngine()
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            requester_id="user-1",
            intent_text="ship container",
        )
        result = engine.evaluate(req)
        assert result.decision == IBACDecision.ALLOW

    def test_deny_by_scope(self):
        engine = IBACEngine()
        engine.add_policy(
            IBACPolicy(
                policy_id="no-admin",
                denied_scopes=["admin:write"],
            )
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
            requester_id="user-1",
            requested_scopes=["admin:write"],
        )
        result = engine.evaluate(req)
        assert result.decision == IBACDecision.DENY
        assert "admin:write" in result.reason

    def test_deny_by_data_domain(self):
        engine = IBACEngine()
        engine.add_policy(
            IBACPolicy(
                policy_id="no-pii",
                denied_data_domains=["pii"],
            )
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY,
            data_domains=["pii"],
        )
        result = engine.evaluate(req)
        assert result.decision == IBACDecision.DENY

    def test_allow_list_enforcement(self):
        engine = IBACEngine()
        engine.add_policy(
            IBACPolicy(
                policy_id="logistics-only",
                allowed_scopes=["logistics:read", "logistics:route"],
            )
        )
        # Request with an allowed scope
        req_ok = IBACRequest(
            evaluation_point=IBACEvaluationPoint.NEGOTIATION_ACCEPTANCE,
            requested_scopes=["logistics:read"],
        )
        assert engine.evaluate(req_ok).decision == IBACDecision.ALLOW

        # Request with a disallowed scope
        req_bad = IBACRequest(
            evaluation_point=IBACEvaluationPoint.NEGOTIATION_ACCEPTANCE,
            requested_scopes=["finance:write"],
        )
        assert engine.evaluate(req_bad).decision == IBACDecision.DENY

    def test_evaluation_point_filtering(self):
        """Policies scoped to specific evaluation points."""
        engine = IBACEngine()
        engine.add_policy(
            IBACPolicy(
                policy_id="exec-only",
                evaluation_points=[IBACEvaluationPoint.EXECUTION_AUTHORIZATION],
                denied_scopes=["dangerous:action"],
            )
        )
        # Should not apply at intent admission
        req1 = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            requested_scopes=["dangerous:action"],
        )
        assert engine.evaluate(req1).decision == IBACDecision.ALLOW

        # Should apply at execution
        req2 = IBACRequest(
            evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
            requested_scopes=["dangerous:action"],
        )
        assert engine.evaluate(req2).decision == IBACDecision.DENY

    def test_remove_policy(self):
        engine = IBACEngine()
        engine.add_policy(IBACPolicy(policy_id="p1", denied_scopes=["x"]))
        engine.remove_policy("p1")
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            requested_scopes=["x"],
        )
        assert engine.evaluate(req).decision == IBACDecision.ALLOW

    def test_all_evaluation_points_defined(self):
        """Verify all 5 evaluation points from §6 exist."""
        expected = {
            "intent_admission",
            "offer_eligibility",
            "negotiation_acceptance",
            "execution_authorization",
            "artifact_emission",
        }
        actual = {e.value for e in IBACEvaluationPoint}
        assert actual == expected
