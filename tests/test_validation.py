"""Tests for agent-based answer validation with IBAC-driven renegotiation.

Covers:
- ValidationResult data class
- AnswerValidationEngine – single round validation (approve/reject)
- AnswerValidationEngine – validation with IBAC rules summary
- ManagedAgentServer.validate_answer – LLM-based validation
- BaseAgent.validate_answer – default approval
- Session validation state tracking
- CoordinatorRuntime._run_validation_loop – happy path (approved)
- CoordinatorRuntime._run_validation_loop – rejection → renegotiation
- CoordinatorRuntime._run_validation_loop – max rounds → final rejection
- IntentPayload.assigned_agent_id propagation
- Validation history is fed back into renegotiation context
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from app.core.protocol.envelope import (
    IntentPayload,
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
    CompletePayload,
    RejectPayload,
    build_envelope,
)
from app.core.session.manager import (
    SessionManager,
    SessionPhase,
    SessionState,
)
from app.core.ibac.engine import (
    IBACEngine,
    IBACRequest,
    IBACResult,
    IBACDecision,
    IBACEvaluationPoint,
)
from app.coordinator.validation.engine import (
    AnswerValidationEngine,
    ValidationResult,
)
from app.agents.base.agent import BaseAgent
from app.agents.managed_server import ManagedAgentServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(
    sm: SessionManager,
    intent_text: str = "test intent",
    assigned_agent_id: str = "",
) -> SessionState:
    """Create a session with an intent and optional assigned validator."""
    session = sm.create(requester_id="test-user")
    session.intent = IntentPayload(
        intent_text=intent_text,
        assigned_agent_id=assigned_agent_id,
    )
    session.assigned_agent_id = assigned_agent_id
    session.composition_plan = {
        "steps": [{"agent_id": "agent-a", "capability_id": "cap-1"}],
        "viable": True,
    }
    return session


def _make_complete_envelope(
    session_id: str,
    status: str = "success",
    output: str = "The answer is 42",
    output_summary: str = "Computed successfully",
) -> AgBusEnvelope:
    """Build a complete envelope mimicking supervisor output."""
    return build_envelope(
        MessageType.COMPLETE,
        SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
        session_id,
        CompletePayload(
            status=status,
            artifacts=[{"agent-a": {"output": output}}],
            metadata={
                "output": output,
                "output_summary": output_summary,
                "agent_metrics": [{"agent_id": "agent-a", "quality_score": 8, "latency_ms": 100, "retries": 0}],
            },
        ),
    )


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_approved_result(self):
        vr = ValidationResult(
            approved=True,
            reason="Looks good",
            suggestions=[],
            round_num=1,
            validator_agent_id="validator-1",
        )
        assert vr.approved is True
        assert vr.round_num == 1
        d = vr.to_dict()
        assert d["approved"] is True
        assert d["validator_agent_id"] == "validator-1"

    def test_rejected_result_with_suggestions(self):
        vr = ValidationResult(
            approved=False,
            reason="Missing cost breakdown",
            suggestions=["Add cost per leg", "Include currency"],
            round_num=2,
            validator_agent_id="validator-1",
        )
        assert vr.approved is False
        assert len(vr.suggestions) == 2
        d = vr.to_dict()
        assert "Missing cost breakdown" in d["reason"]


# ---------------------------------------------------------------------------
# IntentPayload – assigned_agent_id
# ---------------------------------------------------------------------------

class TestIntentPayloadAssignedAgent:
    def test_default_empty(self):
        payload = IntentPayload(intent_text="test")
        assert payload.assigned_agent_id == ""

    def test_with_assigned_agent(self):
        payload = IntentPayload(
            intent_text="test",
            assigned_agent_id="logistics-validator",
        )
        assert payload.assigned_agent_id == "logistics-validator"

    def test_serialization_roundtrip(self):
        payload = IntentPayload(
            intent_text="Optimize route",
            assigned_agent_id="route-expert",
        )
        data = payload.model_dump()
        restored = IntentPayload.model_validate(data)
        assert restored.assigned_agent_id == "route-expert"


# ---------------------------------------------------------------------------
# SessionState – validation fields
# ---------------------------------------------------------------------------

class TestSessionValidationState:
    def test_default_validation_fields(self):
        sm = SessionManager()
        session = sm.create(requester_id="user")
        assert session.assigned_agent_id == ""
        assert session.validation_rounds == 0
        assert session.max_validation_rounds == 3
        assert session.validation_history == []

    def test_assigned_agent_set(self):
        sm = SessionManager()
        session = _make_session(sm, assigned_agent_id="my-validator")
        assert session.assigned_agent_id == "my-validator"

    def test_validation_history_accumulates(self):
        sm = SessionManager()
        session = sm.create(requester_id="user")
        session.validation_history.append({
            "approved": False,
            "reason": "Incomplete",
            "round_num": 1,
            "validator_agent_id": "v1",
            "suggestions": ["Add details"],
        })
        assert len(session.validation_history) == 1
        assert session.validation_history[0]["reason"] == "Incomplete"


# ---------------------------------------------------------------------------
# BaseAgent.validate_answer – default implementation
# ---------------------------------------------------------------------------

class TestBaseAgentValidateAnswer:
    @pytest.mark.asyncio
    async def test_default_approves_everything(self):
        """The default BaseAgent.validate_answer should approve."""

        class DummyAgent(BaseAgent):
            def capabilities(self):
                return []

            async def execute_task(self, payload, context):
                return {}

        agent = DummyAgent(agent_id="dummy")
        result = await agent.validate_answer(
            answer={"output": "Hello"},
            intent_text="Say hello",
            context={},
        )
        assert result["approved"] is True
        assert "Default validation" in result["reason"]


# ---------------------------------------------------------------------------
# AnswerValidationEngine
# ---------------------------------------------------------------------------

class TestAnswerValidationEngine:
    @pytest.mark.asyncio
    async def test_validation_approved(self):
        """Engine should record approval when validator approves."""
        ibac = IBACEngine()
        engine = AnswerValidationEngine(ibac_engine=ibac)

        sm = SessionManager()
        session = _make_session(sm, assigned_agent_id="validator-1")

        async def _approve(**kwargs):
            return {"approved": True, "reason": "All good", "suggestions": []}

        vr = await engine.validate(session, {"output": "42"}, _approve)

        assert vr.approved is True
        assert vr.round_num == 1
        assert session.validation_rounds == 1
        assert len(session.validation_history) == 1
        assert session.validation_history[0]["approved"] is True

    @pytest.mark.asyncio
    async def test_validation_rejected(self):
        """Engine should record rejection with reason and suggestions."""
        ibac = IBACEngine()
        engine = AnswerValidationEngine(ibac_engine=ibac)

        sm = SessionManager()
        session = _make_session(sm, assigned_agent_id="validator-1")

        async def _reject(**kwargs):
            return {
                "approved": False,
                "reason": "Missing data",
                "suggestions": ["Include costs"],
            }

        vr = await engine.validate(session, {"output": "partial"}, _reject)

        assert vr.approved is False
        assert "Missing data" in vr.reason
        assert "Include costs" in vr.suggestions
        assert session.validation_rounds == 1
        assert session.validation_history[0]["approved"] is False

    @pytest.mark.asyncio
    async def test_validation_increments_rounds(self):
        """Multiple validation calls should increment round_num."""
        ibac = IBACEngine()
        engine = AnswerValidationEngine(ibac_engine=ibac)

        sm = SessionManager()
        session = _make_session(sm, assigned_agent_id="validator-1")

        async def _reject(**kwargs):
            return {"approved": False, "reason": "Nope", "suggestions": []}

        vr1 = await engine.validate(session, {"output": "v1"}, _reject)
        assert vr1.round_num == 1

        vr2 = await engine.validate(session, {"output": "v2"}, _reject)
        assert vr2.round_num == 2

        assert session.validation_rounds == 2
        assert len(session.validation_history) == 2

    @pytest.mark.asyncio
    async def test_validation_passes_ibac_rules_summary(self):
        """The engine should fetch IBAC rules and pass them to the validator."""
        ibac = IBACEngine()

        # Mock rule_repo to return a mock rule
        mock_rule = MagicMock()
        mock_rule.rule_id = "rule-1"
        mock_rule.name = "No internet access"
        mock_rule.description = "Prevent agents from accessing the internet"
        mock_rule.action = MagicMock()
        mock_rule.action.value = "deny"
        mock_rule.priority = 100
        mock_rule.evaluation_points_json = []
        mock_rule.conditions_json = {}

        mock_repo = MagicMock()
        mock_repo.list_all.return_value = [mock_rule]
        ibac._rule_repo = mock_repo

        engine = AnswerValidationEngine(ibac_engine=ibac)

        sm = SessionManager()
        session = _make_session(sm, assigned_agent_id="validator-1")

        received_rules = []

        async def _capture_rules(**kwargs):
            received_rules.append(kwargs.get("ibac_rules_summary", ""))
            return {"approved": True, "reason": "OK", "suggestions": []}

        await engine.validate(session, {"output": "test"}, _capture_rules)

        assert len(received_rules) == 1
        assert "No internet access" in received_rules[0]

    @pytest.mark.asyncio
    async def test_validation_handles_exception(self):
        """If the validator throws, the engine should return rejection."""
        ibac = IBACEngine()
        engine = AnswerValidationEngine(ibac_engine=ibac)

        sm = SessionManager()
        session = _make_session(sm, assigned_agent_id="validator-1")

        async def _explode(**kwargs):
            raise RuntimeError("Validator crashed")

        vr = await engine.validate(session, {"output": "test"}, _explode)

        assert vr.approved is False
        assert "Validator crashed" in vr.reason

    @pytest.mark.asyncio
    async def test_prior_feedback_in_context(self):
        """Validation history should be passed to the validator via context."""
        ibac = IBACEngine()
        engine = AnswerValidationEngine(ibac_engine=ibac)

        sm = SessionManager()
        session = _make_session(sm, assigned_agent_id="validator-1")

        # Simulate a prior rejection
        session.validation_history.append({
            "approved": False,
            "reason": "First attempt was bad",
            "suggestions": ["Be more specific"],
            "round_num": 1,
            "validator_agent_id": "validator-1",
        })
        session.validation_rounds = 1

        received_context = []

        async def _capture_context(**kwargs):
            received_context.append(kwargs.get("context", {}))
            return {"approved": True, "reason": "Better now", "suggestions": []}

        await engine.validate(session, {"output": "improved"}, _capture_context)

        assert len(received_context) == 1
        ctx = received_context[0]
        assert "_validation_feedback" in ctx
        assert ctx["_validation_feedback"][0]["reason"] == "First attempt was bad"


# ---------------------------------------------------------------------------
# ManagedAgentServer.validate_answer
# ---------------------------------------------------------------------------

class TestManagedAgentValidation:
    @pytest.mark.asyncio
    async def test_validate_answer_calls_llm(self):
        """ManagedAgentServer should use an LLM to validate based on role/goal."""
        # Create a mock ManagedAgent record
        ma = MagicMock()
        ma.agent_id = "managed-validator"
        ma.role = "Logistics Expert"
        ma.goal = "Validate shipping routes"
        ma.backstory = "20 years in international logistics"
        ma.verbose = False
        ma.capabilities = []

        server = ManagedAgentServer(ma)

        expected_result = {
            "approved": False,
            "reason": "Route cost is missing",
            "suggestions": ["Add per-leg cost breakdown"],
        }

        # Mock the entire LLM chain pipeline end-to-end
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(return_value=expected_result)

        with patch("app.agents.managed_server.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            mock_get_llm.return_value = mock_llm

            # Mock the chain built inside validate_answer:
            #   prompt | llm | parser  →  mock_chain
            with patch("langchain_core.prompts.ChatPromptTemplate.from_messages") as mock_from:
                mock_prompt = MagicMock()
                mock_from.return_value = mock_prompt
                # prompt | llm returns an intermediate
                intermediate = MagicMock()
                mock_prompt.__or__ = MagicMock(return_value=intermediate)
                # intermediate | parser returns the final chain
                intermediate.__or__ = MagicMock(return_value=mock_chain)

                result = await server.validate_answer(
                    answer={"output": "Route Shanghai→Rotterdam: 14 days"},
                    intent_text="Find cheapest route from Shanghai to Rotterdam",
                    context={},
                    ibac_rules_summary="No rules",
                )

        assert result["approved"] is False
        assert "cost" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_validate_answer_no_llm_auto_approves(self):
        """Without an LLM, managed agent validation should auto-approve."""
        ma = MagicMock()
        ma.agent_id = "managed-no-llm"
        ma.role = "Test Agent"
        ma.goal = "Test"
        ma.backstory = "Testing"
        ma.verbose = False
        ma.capabilities = []

        server = ManagedAgentServer(ma)

        with patch("app.agents.managed_server.get_llm", side_effect=RuntimeError("No LLM")):
            result = await server.validate_answer(
                answer={"output": "test"},
                intent_text="test",
                context={},
            )

        assert result["approved"] is True
        assert "No LLM" in result["reason"]


# ---------------------------------------------------------------------------
# CoordinatorRuntime validation integration
# ---------------------------------------------------------------------------

class TestRuntimeValidationLoop:
    """Test _run_validation_loop on the CoordinatorRuntime."""

    def _make_runtime(self):
        """Build a CoordinatorRuntime with mocked subsystems."""
        with patch("app.coordinator.runtime.WSServer"), \
             patch("app.coordinator.runtime.init_db"), \
             patch("app.coordinator.runtime.init_telemetry"):
            from app.coordinator.runtime import CoordinatorRuntime
            runtime = CoordinatorRuntime()
        return runtime

    @pytest.mark.asyncio
    async def test_no_assigned_agent_skips_validation(self):
        """Without an assigned agent, validation loop should return None."""
        runtime = self._make_runtime()
        session = _make_session(runtime.sessions)  # no assigned_agent_id

        complete_env = _make_complete_envelope(session.session_id)
        result = await runtime._run_validation_loop(session, complete_env)
        assert result is None

    @pytest.mark.asyncio
    async def test_validation_approved_returns_none(self):
        """When validation passes, the loop should return None (proceed normally)."""
        runtime = self._make_runtime()
        session = _make_session(runtime.sessions, assigned_agent_id="validator-1")

        # Register a mock validator that approves
        mock_agent = MagicMock()
        mock_agent.validate_answer = AsyncMock(return_value={
            "approved": True,
            "reason": "Perfect",
            "suggestions": [],
        })
        runtime.register_validator("validator-1", mock_agent)

        complete_env = _make_complete_envelope(session.session_id)

        # Suppress event emission
        runtime._emit_event = AsyncMock()

        result = await runtime._run_validation_loop(session, complete_env)
        assert result is None
        assert session.validation_rounds == 1

    @pytest.mark.asyncio
    async def test_validation_rejected_triggers_renegotiation(self):
        """When validation fails (and rounds remain), renegotiation should be triggered."""
        runtime = self._make_runtime()
        session = _make_session(runtime.sessions, assigned_agent_id="validator-1")

        mock_agent = MagicMock()
        mock_agent.validate_answer = AsyncMock(return_value={
            "approved": False,
            "reason": "Answer is too vague",
            "suggestions": ["Be more specific about costs"],
        })
        runtime.register_validator("validator-1", mock_agent)

        complete_env = _make_complete_envelope(session.session_id)

        # Mock subsystems to avoid real WS/LLM calls
        runtime._emit_event = AsyncMock()
        runtime._validation_renegotiate = AsyncMock()

        result = await runtime._run_validation_loop(session, complete_env)
        assert result == "renegotiated"
        assert session.validation_rounds == 1
        runtime._validation_renegotiate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validation_max_rounds_rejected(self):
        """After max rounds exhausted, should send rejection and dissolve."""
        runtime = self._make_runtime()
        session = _make_session(runtime.sessions, assigned_agent_id="validator-1")
        session.max_validation_rounds = 2
        session.validation_rounds = 2  # Already at max

        mock_agent = MagicMock()
        mock_agent.validate_answer = AsyncMock(return_value={
            "approved": False,
            "reason": "Still not good enough",
            "suggestions": [],
        })
        runtime.register_validator("validator-1", mock_agent)

        complete_env = _make_complete_envelope(session.session_id)

        runtime._emit_event = AsyncMock()
        runtime._dissolve_session = AsyncMock()
        # No requester peer
        runtime._session_requester_peers = {}

        result = await runtime._run_validation_loop(session, complete_env)
        assert result == "rejected"
        assert session.validation_rounds == 3  # incremented past max
        runtime._dissolve_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validation_max_rounds_sends_reject_to_requester(self):
        """Final rejection should send a REJECT envelope to the requester."""
        runtime = self._make_runtime()
        session = _make_session(runtime.sessions, assigned_agent_id="validator-1")
        session.max_validation_rounds = 1
        session.validation_rounds = 1

        mock_agent = MagicMock()
        mock_agent.validate_answer = AsyncMock(return_value={
            "approved": False,
            "reason": "Unacceptable",
            "suggestions": [],
        })
        runtime.register_validator("validator-1", mock_agent)

        complete_env = _make_complete_envelope(session.session_id)

        runtime._emit_event = AsyncMock()
        runtime._dissolve_session = AsyncMock()

        # Mock the requester peer
        mock_peer = AsyncMock()
        sent_envelopes = []

        async def _capture_send(env):
            sent_envelopes.append(env)

        mock_peer.send_envelope = _capture_send
        runtime._session_requester_peers[session.session_id] = "peer-123"
        runtime._server = MagicMock()
        runtime._server.get_peer.return_value = mock_peer

        await runtime._run_validation_loop(session, complete_env)

        # Should have sent a REJECT to the requester
        assert len(sent_envelopes) == 1
        assert sent_envelopes[0].message_type == MessageType.REJECT
        assert "validator-1" in sent_envelopes[0].payload["reason"]

    @pytest.mark.asyncio
    async def test_validator_not_found_skips_validation(self):
        """If the assigned validator can't be resolved, skip validation."""
        runtime = self._make_runtime()
        session = _make_session(runtime.sessions, assigned_agent_id="ghost-agent")

        # Don't register any validator — _resolve_validator should return None
        runtime.managed_repo = MagicMock()
        runtime.managed_repo.get.return_value = None
        runtime._agent_peers = {}  # no WS peer either

        complete_env = _make_complete_envelope(session.session_id)
        runtime._emit_event = AsyncMock()

        result = await runtime._run_validation_loop(session, complete_env)
        assert result is None  # Skipped


# ---------------------------------------------------------------------------
# Validation renegotiation context injection
# ---------------------------------------------------------------------------

class TestValidationRenegotiation:
    def _make_runtime(self):
        with patch("app.coordinator.runtime.WSServer"), \
             patch("app.coordinator.runtime.init_db"), \
             patch("app.coordinator.runtime.init_telemetry"):
            from app.coordinator.runtime import CoordinatorRuntime
            runtime = CoordinatorRuntime()
        return runtime

    @pytest.mark.asyncio
    async def test_renegotiation_injects_feedback_into_context(self):
        """Validation rejection should inject feedback into intent context."""
        runtime = self._make_runtime()
        session = _make_session(runtime.sessions, assigned_agent_id="validator-1")
        session.validation_history = [
            {
                "approved": False,
                "reason": "Too vague",
                "suggestions": ["Add specifics"],
                "round_num": 1,
                "validator_agent_id": "validator-1",
            }
        ]

        vr = ValidationResult(
            approved=False,
            reason="Too vague",
            suggestions=["Add specifics"],
            round_num=1,
            validator_agent_id="validator-1",
        )

        # Mock discovery to return no candidates (simplifies the test)
        runtime._adjudicator = MagicMock()
        runtime._adjudicator.discover = AsyncMock(return_value=[])
        runtime._dissolve_session = AsyncMock()
        runtime._session_requester_peers = {}
        runtime._server = MagicMock()
        runtime._server.get_peer.return_value = None

        await runtime._validation_renegotiate(session, vr)

        # Context should have validation feedback
        assert "_validation_feedback" in session.intent.context
        assert "_validation_rejection_reason" in session.intent.context
        assert session.intent.context["_validation_rejection_reason"] == "Too vague"
        assert "_validation_suggestions" in session.intent.context

    @pytest.mark.asyncio
    async def test_renegotiation_resets_offers(self):
        """Renegotiation should clear offers and execution results."""
        runtime = self._make_runtime()
        session = _make_session(runtime.sessions, assigned_agent_id="validator-1")
        session.offers.append(MagicMock())
        session.accepted_offers.append("agent-a")
        session.execution_results.append({"status": "success"})

        vr = ValidationResult(
            approved=False,
            reason="Bad",
            suggestions=[],
            round_num=1,
            validator_agent_id="validator-1",
        )

        runtime._adjudicator = MagicMock()
        runtime._adjudicator.discover = AsyncMock(return_value=[])
        runtime._dissolve_session = AsyncMock()
        runtime._session_requester_peers = {}
        runtime._server = MagicMock()
        runtime._server.get_peer.return_value = None

        await runtime._validation_renegotiate(session, vr)

        assert len(session.offers) == 0
        assert len(session.accepted_offers) == 0
        assert len(session.execution_results) == 0


# ---------------------------------------------------------------------------
# Resolve validator
# ---------------------------------------------------------------------------

class TestResolveValidator:
    def _make_runtime(self):
        with patch("app.coordinator.runtime.WSServer"), \
             patch("app.coordinator.runtime.init_db"), \
             patch("app.coordinator.runtime.init_telemetry"):
            from app.coordinator.runtime import CoordinatorRuntime
            runtime = CoordinatorRuntime()
        return runtime

    @pytest.mark.asyncio
    async def test_resolve_registered_validator(self):
        """A registered validator should be found immediately."""
        runtime = self._make_runtime()
        mock_agent = MagicMock()
        mock_agent.validate_answer = AsyncMock()
        runtime.register_validator("my-agent", mock_agent)

        fn = await runtime._resolve_validator("my-agent")
        assert fn is not None
        assert fn == mock_agent.validate_answer

    @pytest.mark.asyncio
    async def test_resolve_managed_from_db(self):
        """If not registered, should try loading from managed agent DB."""
        runtime = self._make_runtime()

        ma = MagicMock()
        ma.agent_id = "db-agent"
        ma.role = "Tester"
        ma.goal = "Test things"
        ma.backstory = "Born to test"
        ma.verbose = False
        ma.capabilities = []

        runtime.managed_repo = MagicMock()
        runtime.managed_repo.get.return_value = ma

        fn = await runtime._resolve_validator("db-agent")
        assert fn is not None
        # Should now be cached
        assert "db-agent" in runtime._validator_agents

    @pytest.mark.asyncio
    async def test_resolve_unknown_returns_none(self):
        """Unknown agents with no WS peer should return None."""
        runtime = self._make_runtime()
        runtime.managed_repo = MagicMock()
        runtime.managed_repo.get.return_value = None
        runtime._agent_peers = {}

        fn = await runtime._resolve_validator("nonexistent")
        assert fn is None
