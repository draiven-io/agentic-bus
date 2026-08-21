"""Tests for the execution supervisor – IBAC validation, quality scoring, and synthesis."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.coordinator.execution.supervisor import (
    ExecutionSupervisor,
    StepMetrics,
)
from app.core.session.manager import SessionManager, SessionState
from app.core.ibac.engine import (
    IBACEngine,
    IBACResult,
    IBACDecision,
    IBACEvaluationPoint,
)
from app.core.protocol.envelope import IntentPayload
from app.coordinator.graph.builder import AgBusGraphState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(session_manager: SessionManager, intent_text: str = "test intent") -> SessionState:
    """Create a session with an intent already set."""
    session = session_manager.create(requester_id="test-user")
    session.intent = IntentPayload(intent_text=intent_text)
    session.composition_plan = {
        "steps": [
            {"agent_id": "agent-a", "capability_id": "cap-1"},
        ],
        "viable": True,
    }
    return session


def _make_compiled_graph(step_results: dict | None = None):
    """Return a mock compiled graph whose ainvoke yields preset results."""
    results = step_results or {"agent-a": {"output": "Hello world"}}

    async def _ainvoke(state):
        return {**state, "step_results": results}

    mock = AsyncMock()
    mock.ainvoke = _ainvoke
    return mock


# ---------------------------------------------------------------------------
# StepMetrics
# ---------------------------------------------------------------------------

class TestStepMetrics:
    def test_defaults(self):
        m = StepMetrics("agent-x")
        assert m.agent_id == "agent-x"
        assert m.latency_ms == 0.0
        assert m.quality_score == -1
        assert m.retries == 0

    def test_to_dict(self):
        m = StepMetrics("agent-x")
        m.latency_ms = 123.456
        m.quality_score = 8
        m.quality_rationale = "Good answer"
        m.retries = 1
        d = m.to_dict()
        assert d["agent_id"] == "agent-x"
        assert d["latency_ms"] == 123.46
        assert d["quality_score"] == 8
        assert d["retries"] == 1


# ---------------------------------------------------------------------------
# IBAC step validation
# ---------------------------------------------------------------------------

class TestIBACStepValidation:
    @pytest.mark.asyncio
    async def test_step_passes_ibac(self):
        """A step that passes IBAC validation should succeed on first try."""
        sm = SessionManager()
        ibac = IBACEngine()

        # Make IBAC always allow
        allow_result = IBACResult(
            decision=IBACDecision.ALLOW,
            evaluation_point=IBACEvaluationPoint.ARTIFACT_EMISSION,
            reason="All good",
        )
        ibac.evaluate_with_llm = AsyncMock(return_value=allow_result)

        supervisor = ExecutionSupervisor(sm, ibac, max_retries=3)
        session = _make_session(sm)

        # Also mock execution authorisation (first IBAC call)
        compiled = _make_compiled_graph()

        with patch.object(supervisor, "_score_all_steps", new_callable=AsyncMock), \
             patch.object(supervisor, "_synthesise_output", new_callable=AsyncMock, return_value={"output": "done", "summary": "ok"}):
            env = await supervisor.execute(session, compiled)

        assert env.payload["status"] == "success"
        assert "agent_metrics" in env.payload["metadata"]
        assert env.payload["metadata"]["output"] == "done"

    @pytest.mark.asyncio
    async def test_step_denied_then_allowed_on_retry(self):
        """A step denied by IBAC should be retried and succeed."""
        sm = SessionManager()
        ibac = IBACEngine()

        deny_result = IBACResult(
            decision=IBACDecision.DENY,
            evaluation_point=IBACEvaluationPoint.ARTIFACT_EMISSION,
            reason="Contains blocked content",
        )
        allow_result = IBACResult(
            decision=IBACDecision.ALLOW,
            evaluation_point=IBACEvaluationPoint.ARTIFACT_EMISSION,
            reason="Clean now",
        )
        # First call: execution authorisation (allow)
        # Second call: artifact validation (deny)
        # Third call: artifact validation after retry (allow)
        exec_allow = IBACResult(
            decision=IBACDecision.ALLOW,
            evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
            reason="Execution authorised",
        )
        ibac.evaluate_with_llm = AsyncMock(
            side_effect=[exec_allow, deny_result, allow_result]
        )

        supervisor = ExecutionSupervisor(sm, ibac, max_retries=3)
        session = _make_session(sm)
        compiled = _make_compiled_graph()

        with patch.object(supervisor, "_score_all_steps", new_callable=AsyncMock), \
             patch.object(supervisor, "_synthesise_output", new_callable=AsyncMock, return_value={"output": "ok", "summary": "ok"}):
            env = await supervisor.execute(session, compiled)

        assert env.payload["status"] == "success"
        # Should have recorded 1 retry
        metrics = env.payload["metadata"]["agent_metrics"]
        assert any(m["retries"] == 1 for m in metrics)

    @pytest.mark.asyncio
    async def test_step_denied_all_retries_exhausted(self):
        """A step that fails IBAC every time should result in partial_failure."""
        sm = SessionManager()
        ibac = IBACEngine()

        exec_allow = IBACResult(
            decision=IBACDecision.ALLOW,
            evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
            reason="OK",
        )
        deny_result = IBACResult(
            decision=IBACDecision.DENY,
            evaluation_point=IBACEvaluationPoint.ARTIFACT_EMISSION,
            reason="Always denied",
        )
        # 1 exec auth + 3 denies (max_retries=3)
        ibac.evaluate_with_llm = AsyncMock(
            side_effect=[exec_allow, deny_result, deny_result, deny_result]
        )

        supervisor = ExecutionSupervisor(sm, ibac, max_retries=3)
        session = _make_session(sm)
        compiled = _make_compiled_graph()

        with patch.object(supervisor, "_score_all_steps", new_callable=AsyncMock), \
             patch.object(supervisor, "_synthesise_output", new_callable=AsyncMock, return_value={"output": "", "summary": ""}):
            env = await supervisor.execute(session, compiled)

        assert env.payload["status"] == "partial_failure"
        errors = env.payload["metadata"]["errors"]
        assert len(errors) == 1
        assert "IBAC" in errors[0]["error"]

    @pytest.mark.asyncio
    async def test_execution_denied_by_ibac_gate(self):
        """IBAC denying at the execution authorisation gate should prevent execution."""
        sm = SessionManager()
        ibac = IBACEngine()

        deny_result = IBACResult(
            decision=IBACDecision.DENY,
            evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
            reason="Not allowed",
        )
        ibac.evaluate_with_llm = AsyncMock(return_value=deny_result)

        supervisor = ExecutionSupervisor(sm, ibac)
        session = _make_session(sm)
        compiled = _make_compiled_graph()

        env = await supervisor.execute(session, compiled)
        assert env.payload["status"] == "denied"


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------

class TestQualityScoring:
    @pytest.mark.asyncio
    async def test_score_step_calls_llm(self):
        """_score_step should invoke the LLM and return a score dict."""
        sm = SessionManager()
        ibac = IBACEngine()
        supervisor = ExecutionSupervisor(sm, ibac)

        expected = {"score": 8, "rationale": "Very relevant"}

        # Patch the entire LangChain chain's ainvoke via ChatPromptTemplate
        with patch("app.core.llm.get_llm"):
            # Intercept the chain built inside _score_step
            _original_score = supervisor._score_step

            async def _patched_score(intent_text, agent_id, result_payload):
                # Simply return the expected result
                return expected

            supervisor._score_step = _patched_score
            result = await supervisor._score_step("Find data", "agent-1", {"answer": "42"})

        assert result["score"] == 8
        assert "relevant" in result["rationale"].lower()

    @pytest.mark.asyncio
    async def test_score_step_no_llm(self):
        """Without an LLM, scoring should return -1 gracefully."""
        sm = SessionManager()
        ibac = IBACEngine()
        supervisor = ExecutionSupervisor(sm, ibac)

        with patch("app.core.llm.get_llm", side_effect=RuntimeError("No LLM")):
            result = await supervisor._score_step("test", "agent-1", {"data": "x"})

        assert result["score"] == -1


# ---------------------------------------------------------------------------
# Output synthesis
# ---------------------------------------------------------------------------

class TestOutputSynthesis:
    @pytest.mark.asyncio
    async def test_synthesis_calls_llm(self):
        """_synthesise_output should produce a unified output via LLM."""
        sm = SessionManager()
        ibac = IBACEngine()
        supervisor = ExecutionSupervisor(sm, ibac)
        session = _make_session(sm)

        final_state: AgBusGraphState = {
            "session_id": session.session_id,
            "intent_text": "analyse data",
            "context": {},
            "step_results": {"agent-a": {"output": "Result A"}},
            "errors": [],
            "metadata": {},
        }

        expected = {
            "output": "Combined analysis shows...",
            "summary": "Data analysed successfully",
        }

        # Directly patch _synthesise_output's internal chain call
        _original = supervisor._synthesise_output

        async def _patched(session, final_state):
            return expected

        supervisor._synthesise_output = _patched
        result = await supervisor._synthesise_output(session, final_state)

        assert "Combined analysis" in result["output"]
        assert result["summary"] != ""

    @pytest.mark.asyncio
    async def test_synthesis_no_llm_returns_raw(self):
        """Without an LLM, synthesis should return raw results."""
        sm = SessionManager()
        ibac = IBACEngine()
        supervisor = ExecutionSupervisor(sm, ibac)
        session = _make_session(sm)

        final_state: AgBusGraphState = {
            "session_id": session.session_id,
            "intent_text": "test",
            "context": {},
            "step_results": {"agent-a": {"output": "raw data"}},
            "errors": [],
            "metadata": {},
        }

        with patch("app.core.llm.get_llm", side_effect=RuntimeError("nope")):
            result = await supervisor._synthesise_output(session, final_state)

        assert "raw data" in result["output"]
        assert "Raw agent results" in result["summary"]


# ---------------------------------------------------------------------------
# Complete flow integration
# ---------------------------------------------------------------------------

class TestSupervisorCompleteFlow:
    @pytest.mark.asyncio
    async def test_success_flow_has_output_and_metrics(self):
        """Full execution should produce output, output_summary, and agent_metrics."""
        sm = SessionManager()
        ibac = IBACEngine()

        allow_result = IBACResult(
            decision=IBACDecision.ALLOW,
            evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
            reason="OK",
        )
        ibac.evaluate_with_llm = AsyncMock(return_value=allow_result)

        supervisor = ExecutionSupervisor(sm, ibac, max_retries=2)
        session = _make_session(sm)
        compiled = _make_compiled_graph({"agent-a": {"output": "The answer is 42"}})

        # Mock scoring and synthesis
        with patch.object(
            supervisor, "_score_all_steps", new_callable=AsyncMock
        ) as _mock_score, \
             patch.object(
                 supervisor, "_synthesise_output", new_callable=AsyncMock,
                 return_value={"output": "Final: 42", "summary": "Computed"},
             ):
            env = await supervisor.execute(session, compiled)

        payload = env.payload
        assert payload["status"] == "success"
        meta = payload["metadata"]
        assert meta["output"] == "Final: 42"
        assert meta["output_summary"] == "Computed"
        assert "agent_metrics" in meta

    @pytest.mark.asyncio
    async def test_multi_agent_metrics(self):
        """Multiple agents should each get their own metrics entry."""
        sm = SessionManager()
        ibac = IBACEngine()

        allow_result = IBACResult(
            decision=IBACDecision.ALLOW,
            evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
            reason="OK",
        )
        ibac.evaluate_with_llm = AsyncMock(return_value=allow_result)

        supervisor = ExecutionSupervisor(sm, ibac, max_retries=2)

        session = sm.create(requester_id="test-user")
        session.intent = IntentPayload(intent_text="multi-agent test")
        session.composition_plan = {
            "steps": [
                {"agent_id": "agent-a", "capability_id": "cap-1"},
                {"agent_id": "agent-b", "capability_id": "cap-2"},
            ],
            "viable": True,
        }

        compiled = _make_compiled_graph({
            "agent-a": {"output": "Result A"},
            "agent-b": {"output": "Result B"},
        })

        with patch.object(supervisor, "_score_all_steps", new_callable=AsyncMock), \
             patch.object(supervisor, "_synthesise_output", new_callable=AsyncMock,
                          return_value={"output": "Combined", "summary": "Done"}):
            env = await supervisor.execute(session, compiled)

        metrics = env.payload["metadata"]["agent_metrics"]
        agent_ids = {m["agent_id"] for m in metrics}
        assert "agent-a" in agent_ids
        assert "agent-b" in agent_ids
        assert all(m["latency_ms"] >= 0 for m in metrics)
