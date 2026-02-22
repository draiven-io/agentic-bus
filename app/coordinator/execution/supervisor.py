"""Supervised execution engine (§14 of AGENTS.md / §4.1.3 of the paper).

Execution proceeds only after:
1. Negotiation is finalised.
2. IBAC authorises execution.
3. The LangGraph is built.

Failures are propagated as structured negotiation failures – not as
exceptions.  Each node execution is traced via OpenTelemetry.
"""

from __future__ import annotations

import logging
from typing import Any

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


class ExecutionSupervisor:
    """Supervises the execution phase of an Agentic Bus session.

    Responsibilities:
    - Emit ``execute`` messages
    - Run the compiled LangGraph
    - Trace every node execution
    - Handle failures as renegotiation signals
    - Emit ``complete`` message with results
    """

    def __init__(
        self,
        session_manager: SessionManager,
        ibac_engine: IBACEngine,
    ):
        self._sessions = session_manager
        self._ibac = ibac_engine

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

            # 4. Execute the graph
            try:
                final_state = await compiled_graph.ainvoke(initial_state)
            except Exception as exc:
                logger.exception("Graph execution failed for session %s", session.session_id)
                return self._build_complete(
                    session,
                    status="error",
                    metadata={"error": str(exc)},
                )

            # 5. Check for step errors
            errors = final_state.get("errors", [])
            if errors:
                logger.warning(
                    "Session %s completed with %d errors", session.session_id, len(errors)
                )
                return self._build_complete(
                    session,
                    status="partial_failure",
                    artifacts=[final_state.get("step_results", {})],
                    metadata={"errors": errors},
                )

            # 6. Success
            return self._build_complete(
                session,
                status="success",
                artifacts=[final_state.get("step_results", {})],
            )

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
