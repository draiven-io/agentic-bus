"""Tests for negotiation engine."""


from agentic_bus.core.protocol.envelope import OfferPayload
from agentic_bus.core.session.manager import NegotiationRecord
from agentic_bus.coordinator.negotiation.engine import (
    NegotiationEngine,
    CandidateScore,
)


def _make_record(agent_id: str, status: str = "pending") -> NegotiationRecord:
    return NegotiationRecord(
        agent_id=agent_id,
        offer=OfferPayload(
            capability_id=f"{agent_id}-cap",
            capability_description=f"Cap of {agent_id}",
        ),
        status=status,
    )


class TestCandidateScore:
    def test_combined_score_formula(self):
        """Verify equation 8: s'_i = α · s_i + (1 - α) · ρ_i"""
        cs = CandidateScore(
            agent_id="a",
            capability_id="c",
            semantic_score=0.8,
            outcome_prior=0.6,
            alpha=0.7,
        )
        expected = 0.7 * 0.8 + 0.3 * 0.6
        assert abs(cs.combined_score - expected) < 1e-9


class TestNegotiationEngine:
    def test_entropy_all_pending(self):
        """All same status → entropy = 0."""
        engine = NegotiationEngine()
        offers = [_make_record("a"), _make_record("b"), _make_record("c")]
        entropy = engine.compute_semantic_entropy(offers)
        assert entropy == 0.0

    def test_entropy_mixed(self):
        """Mixed statuses → entropy > 0."""
        engine = NegotiationEngine()
        offers = [
            _make_record("a", "accepted"),
            _make_record("b", "rejected"),
            _make_record("c", "pending"),
        ]
        entropy = engine.compute_semantic_entropy(offers)
        assert entropy > 0.0

    def test_entropy_empty(self):
        engine = NegotiationEngine()
        assert engine.compute_semantic_entropy([]) == 1.0

    def test_convergence_with_all_accepted(self):
        """All accepted → entropy = 0 which is below any threshold."""
        engine = NegotiationEngine(tau=0.5)
        offers = [
            _make_record("a", "accepted"),
            _make_record("b", "accepted"),
        ]
        # Initial entropy (when all were pending)
        initial = 1.0
        assert engine.check_convergence(offers, initial) is True

    def test_compose_offers(self):
        engine = NegotiationEngine()
        offers = [
            _make_record("a", "accepted"),
            _make_record("b", "rejected"),
            _make_record("c", "accepted"),
        ]
        plan = engine.compose_offers(offers)
        assert plan["viable"] is True
        assert len(plan["steps"]) == 2
        agent_ids = [s["agent_id"] for s in plan["steps"]]
        assert "a" in agent_ids
        assert "c" in agent_ids
        assert "b" not in agent_ids
        # Each step should carry an output_schema key
        for step in plan["steps"]:
            assert "output_schema" in step

    def test_compose_no_accepted(self):
        engine = NegotiationEngine()
        offers = [_make_record("a", "rejected")]
        plan = engine.compose_offers(offers)
        assert plan["viable"] is False

    def test_fallback_not_needed(self):
        engine = NegotiationEngine(max_rounds=5)
        assert engine.needs_fallback(2, [], 1.0) is None

    def test_fallback_recursive_simplification(self):
        engine = NegotiationEngine(max_rounds=3, tau=0.9)
        offers = [
            _make_record("a", "pending"),
            _make_record("b", "rejected"),
        ]
        result = engine.needs_fallback(3, offers, 1.0)
        assert result == "recursive_simplification"

    def test_fallback_solidification(self):
        engine = NegotiationEngine(max_rounds=3, tau=0.99)
        # Mixed statuses produce non-zero entropy → negotiation hasn't converged
        offers = [
            _make_record("a", "pending"),
            _make_record("b", "rejected"),
            _make_record("c", "accepted"),
        ]
        result = engine.needs_fallback(4, offers, 1.0)
        assert result == "solidification"


class TestOutputSchemaPropagation:
    """Verify that output_schema flows through negotiation (§ output format)."""

    def test_compose_offers_carries_output_schema(self):
        schema = {"title": "RouteOutput", "type": "object", "properties": {"distance": {"type": "number"}}}
        record = NegotiationRecord(
            agent_id="agent-typed",
            offer=OfferPayload(
                capability_id="route_opt",
                capability_description="Optimise routes",
                output_schema=schema,
            ),
            status="accepted",
        )
        engine = NegotiationEngine()
        plan = engine.compose_offers([record])
        assert plan["viable"] is True
        assert plan["steps"][0]["output_schema"] == schema

    def test_compose_offers_default_empty_schema(self):
        record = NegotiationRecord(
            agent_id="agent-untyped",
            offer=OfferPayload(
                capability_id="generic",
                capability_description="Generic capability",
            ),
            status="accepted",
        )
        engine = NegotiationEngine()
        plan = engine.compose_offers([record])
        assert plan["steps"][0]["output_schema"] == {}
