"""Supervised execution engine (§14 of AGENTS.md / §4.1.3 of the paper).

Execution proceeds only after:
1. Negotiation is finalised.
2. IBAC authorises execution.
3. The LangGraph is built.

After each agent step the supervisor:
- Validates the agent's answer against IBAC rules.
- If the answer violates a rule, re-dispatches the task with restrictions
  (up to ``max_retries`` attempts per step).
- Measures latency per step.
- Uses the coordinator LLM to score the quality of each agent answer (0-10).
- After all steps succeed, synthesises a single ``output`` conclusion.

Failures are propagated as structured negotiation failures – not as
exceptions.  Each node execution is traced via OpenTelemetry.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph

from app.core.protocol.envelope import (
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
    CompletePayload,
    ExecutePayload,
    build_envelope,
)
from app.core.session.manager import SessionManager, SessionPhase, SessionState
from app.core.ibac.engine import (
    IBACEngine,
    IBACRequest,
    IBACEvaluationPoint,
    IBACDecision,
)
from app.core.telemetry.tracing import agbus_span, inject_trace_context
from app.coordinator.graph.builder import AgBusGraphState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM prompts used by the supervisor
# ---------------------------------------------------------------------------

_QUALITY_SCORE_SYSTEM = """\
You are the quality evaluator of the Agentic Bus Protocol coordinator.
Given an agent's response to a task, score the quality of the answer.

Evaluation criteria:
- Relevance: does the answer address the intent?
- Completeness: does it cover all requested aspects?
- Accuracy: does the information appear correct and well-formed?
- Clarity: is the response clearly structured and understandable?

Return ONLY a JSON object (no markdown fences, no commentary):
{{
  "score": <integer 0-10>,
  "rationale": "<one-sentence justification>"
}}
"""

_QUALITY_SCORE_HUMAN = """\
Intent: {intent_text}
Agent ID: {agent_id}
Agent response:
{agent_response}
"""

_SYNTHESIS_SYSTEM = """\
You are the synthesis engine of the Agentic Bus Protocol coordinator.
After all agents have completed their tasks, produce a clear, coherent
conclusion that integrates every agent's contribution into a single
unified answer for the end-user.

Guidelines:
- Reference each agent's contribution when relevant.
- Highlight key findings, numbers, or recommendations.
- Be concise but comprehensive.
- If any agent reported errors or partial results, note them.

Return ONLY a JSON object (no markdown fences, no commentary):
{{
  "output": "<the synthesised final answer>",
  "summary": "<one-sentence executive summary>"
}}
"""

_SYNTHESIS_HUMAN = """\
Original intent: {intent_text}
Context: {context}

Agent results:
{agent_results_block}
"""


class StepMetrics:
    """Per-agent execution metrics collected by the supervisor."""

    __slots__ = ("agent_id", "latency_ms", "quality_score", "quality_rationale", "retries")

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.latency_ms: float = 0.0
        self.quality_score: int = -1  # -1 = not scored yet
        self.quality_rationale: str = ""
        self.retries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "latency_ms": round(self.latency_ms, 2),
            "quality_score": self.quality_score,
            "quality_rationale": self.quality_rationale,
            "retries": self.retries,
        }


class ExecutionSupervisor:
    """Supervises the execution phase of an Agentic Bus session.

    Responsibilities:
    - Emit ``execute`` messages
    - Run the compiled LangGraph with per-step IBAC validation
    - Re-dispatch tasks when IBAC denies a step answer (up to ``max_retries``)
    - Measure latency per agent step
    - Score each agent answer via the coordinator LLM (0-10)
    - Synthesise a unified ``output`` conclusion after all steps
    - Trace every node execution
    - Handle failures as renegotiation signals
    - Emit ``complete`` message with results
    """

    DEFAULT_MAX_RETRIES: int = 3

    def __init__(
        self,
        session_manager: SessionManager,
        ibac_engine: IBACEngine,
        max_retries: int | None = None,
    ):
        self._sessions = session_manager
        self._ibac = ibac_engine
        self._max_retries = max_retries if max_retries is not None else self.DEFAULT_MAX_RETRIES

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        session: SessionState,
        compiled_graph: Any,
    ) -> AgBusEnvelope:
        """Run the execution graph for a session.

        Returns a ``complete`` envelope.
        """
        with agbus_span("agbus.execution", attributes={"session_id": session.session_id}):
            # 1. IBAC gate – execution authorisation
            ibac_req = IBACRequest(
                evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
                requester_id=session.requester_id,
                requester_oidc_subject=session.requester_oidc_subject,
                intent_text=session.intent.intent_text if session.intent else "",
                intent_context=session.intent.context if session.intent else {},
                requested_scopes=session.intent.ibac_claims_requested if session.intent else [],
            )
            ibac_result = await self._ibac.evaluate_with_llm(ibac_req)
            session.ibac_decisions.append(ibac_result.model_dump())

            if ibac_result.decision == IBACDecision.DENY:
                logger.warning("IBAC denied execution for session %s", session.session_id)
                return self._build_complete(
                    session,
                    status="denied",
                    metadata={"ibac_reason": ibac_result.reason},
                )

            # 2. Transition to execution phase
            self._sessions.transition(session.session_id, SessionPhase.EXECUTION)

            # 3. Build initial graph state
            initial_state: AgBusGraphState = {
                "session_id": session.session_id,
                "intent_text": session.intent.intent_text if session.intent else "",
                "context": session.intent.context if session.intent else {},
                "step_results": {},
                "errors": [],
                "metadata": {},
            }

            # 4. Execute the graph with per-step IBAC validation & metrics
            step_metrics: dict[str, StepMetrics] = {}
            ibac_restrictions: dict[str, list[str]] = {}

            try:
                final_state = await self._execute_with_ibac_validation(
                    session=session,
                    compiled_graph=compiled_graph,
                    initial_state=initial_state,
                    step_metrics=step_metrics,
                    ibac_restrictions=ibac_restrictions,
                )
            except Exception as exc:
                logger.exception("Graph execution failed for session %s", session.session_id)
                return self._build_complete(
                    session,
                    status="error",
                    metadata={
                        "error": str(exc),
                        "agent_metrics": [m.to_dict() for m in step_metrics.values()],
                    },
                )

            # 5. Score quality of each agent answer
            await self._score_all_steps(session, final_state, step_metrics)

            # 6. Check for step errors
            errors = final_state.get("errors", [])
            metrics_list = [m.to_dict() for m in step_metrics.values()]

            if errors:
                logger.warning(
                    "Session %s completed with %d errors", session.session_id, len(errors)
                )
                # Still attempt synthesis for the results we have
                output = await self._synthesise_output(session, final_state)
                return self._build_complete(
                    session,
                    status="partial_failure",
                    artifacts=[final_state.get("step_results", {})],
                    metadata={
                        "errors": errors,
                        "agent_metrics": metrics_list,
                        "output": output.get("output", ""),
                        "output_summary": output.get("summary", ""),
                    },
                )

            # 7. Synthesise unified output
            output = await self._synthesise_output(session, final_state)

            # 8. Success
            return self._build_complete(
                session,
                status="success",
                artifacts=[final_state.get("step_results", {})],
                metadata={
                    "agent_metrics": metrics_list,
                    "output": output.get("output", ""),
                    "output_summary": output.get("summary", ""),
                },
            )

    # ------------------------------------------------------------------
    # Per-step IBAC validation with retry loop
    # ------------------------------------------------------------------

    async def _execute_with_ibac_validation(
        self,
        session: SessionState,
        compiled_graph: Any,
        initial_state: AgBusGraphState,
        step_metrics: dict[str, StepMetrics],
        ibac_restrictions: dict[str, list[str]],
    ) -> AgBusGraphState:
        """Run the graph and validate each step result against IBAC.

        If a step's output violates IBAC, inject the restriction into the
        context and re-invoke the full graph (the already-completed steps
        return cached results).  Retry up to ``max_retries`` per agent.
        """
        state = dict(initial_state)
        plan_steps: list[dict[str, Any]] = session.composition_plan.get("steps", [])
        agent_ids = [s["agent_id"] for s in plan_steps]

        # Initialise metrics
        for aid in agent_ids:
            step_metrics[aid] = StepMetrics(aid)

        # First full execution
        t0 = time.monotonic()
        final_state = await compiled_graph.ainvoke(state)
        elapsed = (time.monotonic() - t0) * 1000  # ms

        # Distribute total time proportionally (rough — real per-node timing
        # is captured on retry).  We'll refine per agent below.
        per_agent_time = elapsed / max(len(agent_ids), 1)
        for aid in agent_ids:
            step_metrics[aid].latency_ms = per_agent_time

        # Validate each step result against IBAC (artifact emission)
        for aid in agent_ids:
            result_payload = final_state.get("step_results", {}).get(aid)
            if result_payload is None:
                continue

            for attempt in range(1, self._max_retries + 1):
                ibac_ok = await self._validate_step_ibac(session, aid, result_payload, ibac_restrictions)
                if ibac_ok:
                    break

                step_metrics[aid].retries = attempt
                logger.warning(
                    "IBAC denied step output from %s (attempt %d/%d) for session %s",
                    aid, attempt, self._max_retries, session.session_id,
                )

                if attempt >= self._max_retries:
                    # Max retries exhausted — record error, keep partial results
                    errors = list(final_state.get("errors", []))
                    errors.append({
                        "agent_id": aid,
                        "error": (
                            f"Agent answer rejected by IBAC after {self._max_retries} retries. "
                            f"Restrictions: {ibac_restrictions.get(aid, [])}"
                        ),
                    })
                    final_state = {**final_state, "errors": errors}
                    # Clear the rejected result
                    sr = dict(final_state.get("step_results", {}))
                    sr.pop(aid, None)
                    final_state = {**final_state, "step_results": sr}
                    break

                # Re-invoke with restrictions injected into context
                retry_state = dict(initial_state)
                ctx = dict(retry_state.get("context", {}))
                ctx["_ibac_restrictions"] = {
                    aid: ibac_restrictions.get(aid, [])
                    for aid in agent_ids
                    if ibac_restrictions.get(aid)
                }
                retry_state["context"] = ctx

                t_retry = time.monotonic()
                final_state = await compiled_graph.ainvoke(retry_state)
                retry_elapsed = (time.monotonic() - t_retry) * 1000
                step_metrics[aid].latency_ms += retry_elapsed / max(len(agent_ids), 1)

                result_payload = final_state.get("step_results", {}).get(aid)
                if result_payload is None:
                    break

        return final_state

    async def _validate_step_ibac(
        self,
        session: SessionState,
        agent_id: str,
        result_payload: Any,
        ibac_restrictions: dict[str, list[str]],
    ) -> bool:
        """Validate a single step result against IBAC artifact emission rules.

        Returns ``True`` if the step is allowed, ``False`` if denied.
        On denial the restriction reason is appended to ``ibac_restrictions``.
        """
        # Serialise the result for the IBAC prompt
        result_text = ""
        if isinstance(result_payload, dict):
            # Extract textual content — try common keys
            result_text = (
                result_payload.get("output", "")
                or result_payload.get("result", "")
                or result_payload.get("answer", "")
                or json.dumps(result_payload, default=str)[:2000]
            )
        else:
            result_text = str(result_payload)[:2000]

        ibac_req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.ARTIFACT_EMISSION,
            requester_id=session.requester_id,
            requester_oidc_subject=session.requester_oidc_subject,
            agent_id=agent_id,
            intent_text=f"{session.intent.intent_text if session.intent else ''}\n\nAgent answer: {result_text}",
            intent_context=session.intent.context if session.intent else {},
            requested_scopes=session.intent.ibac_claims_requested if session.intent else [],
        )

        ibac_result = await self._ibac.evaluate_with_llm(ibac_req)
        session.ibac_decisions.append(ibac_result.model_dump())

        if ibac_result.decision == IBACDecision.DENY:
            restrictions = ibac_restrictions.setdefault(agent_id, [])
            restrictions.append(ibac_result.reason)
            logger.warning(
                "IBAC DENY artifact from %s: %s", agent_id, ibac_result.reason,
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Quality scoring
    # ------------------------------------------------------------------

    async def _score_all_steps(
        self,
        session: SessionState,
        final_state: AgBusGraphState,
        step_metrics: dict[str, StepMetrics],
    ) -> None:
        """Score the quality of every agent answer using the coordinator LLM."""
        step_results = final_state.get("step_results", {})
        intent_text = session.intent.intent_text if session.intent else ""

        for agent_id, result_payload in step_results.items():
            metrics = step_metrics.get(agent_id)
            if metrics is None:
                continue

            score_data = await self._score_step(intent_text, agent_id, result_payload)
            metrics.quality_score = score_data.get("score", -1)
            metrics.quality_rationale = score_data.get("rationale", "")

    async def _score_step(
        self,
        intent_text: str,
        agent_id: str,
        result_payload: Any,
    ) -> dict[str, Any]:
        """Use the coordinator LLM to score a single agent answer (0-10)."""
        if isinstance(result_payload, dict):
            response_str = json.dumps(result_payload, default=str, indent=2)[:3000]
        else:
            response_str = str(result_payload)[:3000]

        prompt = ChatPromptTemplate.from_messages([
            ("system", _QUALITY_SCORE_SYSTEM),
            ("human", _QUALITY_SCORE_HUMAN),
        ])
        parser = JsonOutputParser()

        try:
            from app.core.llm import get_llm
            llm = get_llm()
        except Exception:
            logger.warning("No LLM configured — skipping quality scoring for %s", agent_id)
            return {"score": -1, "rationale": "LLM not available"}

        chain = prompt | llm | parser
        try:
            result = await chain.ainvoke({
                "intent_text": intent_text,
                "agent_id": agent_id,
                "agent_response": response_str,
            })
            return result
        except Exception:
            logger.exception("Quality scoring failed for agent %s", agent_id)
            return {"score": -1, "rationale": "Scoring failed"}

    # ------------------------------------------------------------------
    # Output synthesis
    # ------------------------------------------------------------------

    async def _synthesise_output(
        self,
        session: SessionState,
        final_state: AgBusGraphState,
    ) -> dict[str, Any]:
        """Synthesise a unified conclusion from all agent results.

        Returns ``{"output": "...", "summary": "..."}``.
        """
        step_results = final_state.get("step_results", {})
        intent_text = session.intent.intent_text if session.intent else ""
        context = session.intent.context if session.intent else {}

        # Build readable block
        lines: list[str] = []
        for agent_id, payload in step_results.items():
            if isinstance(payload, dict):
                body = json.dumps(payload, default=str, indent=2)[:2000]
            else:
                body = str(payload)[:2000]
            lines.append(f"### Agent: {agent_id}\n{body}")
        agent_results_block = "\n\n".join(lines) if lines else "(No results)"

        prompt = ChatPromptTemplate.from_messages([
            ("system", _SYNTHESIS_SYSTEM),
            ("human", _SYNTHESIS_HUMAN),
        ])
        parser = JsonOutputParser()

        try:
            from app.core.llm import get_llm
            llm = get_llm()
        except Exception:
            logger.warning("No LLM configured — skipping output synthesis")
            return {"output": agent_results_block, "summary": "Raw agent results (no LLM synthesis)"}

        chain = prompt | llm | parser
        try:
            result = await chain.ainvoke({
                "intent_text": intent_text,
                "context": json.dumps(context, default=str)[:1000],
                "agent_results_block": agent_results_block,
            })
            return result
        except Exception:
            logger.exception("Output synthesis failed for session %s", session.session_id)
            return {"output": agent_results_block, "summary": "Synthesis failed — raw results returned"}

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _build_complete(
        session: SessionState,
        status: str = "success",
        artifacts: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgBusEnvelope:
        sender = SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator")
        payload = CompletePayload(
            status=status,
            artifacts=artifacts or [],
            metadata=metadata or {},
        )
        return build_envelope(
            message_type=MessageType.COMPLETE,
            sender=sender,
            session_id=session.session_id,
            payload=payload,
            trace=inject_trace_context(),
        )
