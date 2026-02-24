"""Agent-based answer validation engine.

When an intent has an ``assigned_agent_id``, the execution output must be
validated by that agent before the session completes.  The validation loop:

1. Execute the graph (normal flow).
2. Call the assigned agent's ``validate_answer`` method.
3. If validation passes → complete the session.
4. If validation fails → feed the rejection reason back as context and
   trigger a renegotiation cycle (re-discover, re-negotiate, re-execute).
5. Repeat up to ``max_validation_rounds``.
6. If no viable output after all rounds → reject the session.

For **managed agents** (CrewAI-backed), ``validate_answer`` uses an LLM prompt
built from the agent's role, goal, backstory, and the active IBAC rules.

For **external agents**, ``validate_answer`` is delegated over WebSocket — the
agent implements its own domain-specific validation logic.

The validation is IBAC-aware: the engine fetches applicable IBAC rules and
includes them in the validation context so the validating agent can check
governance compliance alongside domain correctness.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.ibac.engine import IBACEngine
from app.core.session.manager import SessionState
from app.core.telemetry.tracing import agbus_span

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of an agent-based validation round."""

    __slots__ = ("approved", "reason", "suggestions", "round_num", "validator_agent_id")

    def __init__(
        self,
        approved: bool,
        reason: str,
        suggestions: list[str],
        round_num: int,
        validator_agent_id: str,
    ):
        self.approved = approved
        self.reason = reason
        self.suggestions = suggestions
        self.round_num = round_num
        self.validator_agent_id = validator_agent_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "suggestions": self.suggestions,
            "round_num": self.round_num,
            "validator_agent_id": self.validator_agent_id,
        }


class AnswerValidationEngine:
    """Orchestrates agent-based answer validation with renegotiation loops.

    The engine is invoked by the coordinator runtime after execution completes
    when the session has an ``assigned_agent_id``.  It:

    1. Gathers applicable IBAC rules for the validation context.
    2. Calls the assigned agent's ``validate_answer`` method.
    3. Returns a ``ValidationResult`` that the runtime uses to decide whether
       to accept the output or trigger renegotiation.
    """

    def __init__(self, ibac_engine: IBACEngine):
        self._ibac = ibac_engine

    def get_ibac_rules_summary(self) -> str:
        """Build a human-readable summary of active IBAC rules for the validator.

        The validator agent receives this summary so it can check whether the
        answer complies with governance policies.
        """
        try:
            rules = self._ibac.rule_repo.list_all(enabled_only=True)
        except Exception:
            rules = []

        if not rules:
            return "(No active IBAC rules configured.)"

        return self._ibac._format_rules_for_llm(rules)

    async def validate(
        self,
        session: SessionState,
        answer: dict[str, Any],
        agent_validate_fn: Any,
    ) -> ValidationResult:
        """Run one validation round.

        Args:
            session: The current session state.
            answer: The execution output to validate (typically the
                synthesised output or raw step results).
            agent_validate_fn: An async callable with the signature
                ``(answer, intent_text, context, ibac_rules_summary) -> dict``.
                This is the assigned agent's ``validate_answer`` method.

        Returns:
            A ``ValidationResult`` describing the outcome.
        """
        round_num = session.validation_rounds + 1

        with agbus_span(
            "agbus.validation",
            attributes={
                "session_id": session.session_id,
                "validator": session.assigned_agent_id,
                "round": round_num,
            },
        ):
            ibac_summary = self.get_ibac_rules_summary()

            # Build validation context including prior feedback
            validation_context = dict(session.intent.context) if session.intent else {}
            if session.validation_history:
                validation_context["_validation_feedback"] = session.validation_history

            intent_text = session.intent.intent_text if session.intent else ""

            try:
                result = await agent_validate_fn(
                    answer=answer,
                    intent_text=intent_text,
                    context=validation_context,
                    ibac_rules_summary=ibac_summary,
                )
            except Exception as exc:
                logger.exception(
                    "Validation call failed for session %s (round %d)",
                    session.session_id,
                    round_num,
                )
                result = {
                    "approved": False,
                    "reason": f"Validation call failed: {exc}",
                    "suggestions": ["Retry the execution."],
                }

            vr = ValidationResult(
                approved=bool(result.get("approved", False)),
                reason=result.get("reason", ""),
                suggestions=result.get("suggestions", []),
                round_num=round_num,
                validator_agent_id=session.assigned_agent_id,
            )

            # Record in session history
            session.validation_rounds = round_num
            session.validation_history.append(vr.to_dict())

            if vr.approved:
                logger.info(
                    "Validation APPROVED for session %s (round %d): %s",
                    session.session_id,
                    round_num,
                    vr.reason,
                )
            else:
                logger.warning(
                    "Validation REJECTED for session %s (round %d): %s — suggestions: %s",
                    session.session_id,
                    round_num,
                    vr.reason,
                    vr.suggestions,
                )

            return vr
