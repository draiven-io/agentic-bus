"""IBAC – Intention-Based Access Control (§6.1 of the Liquid Interfaces paper, lip.md).

Unlike RBAC/ABAC which authorise discrete operations against predefined
resources, IBAC evaluates governance decisions against the *expressed intent*,
contextual constraints, and organisational policies.

IBAC evaluation points (from AGENTS.md §6):
  1. Intent admission
  2. Offer eligibility
  3. Negotiation acceptance
  4. Execution authorisation
  5. Artifact emission

Every decision is auditable and traced (§6.2 – Semantic Auditability).

Implementation
--------------
The primary evaluation path is **LLM-based**: the engine loads all active
IBAC rules from the database, presents them together with the request
context to the coordinator's LLM, and lets the model *semantically* reason
about whether any rule should block the request.  This allows natural-
language rules such as "Prevent agents from accessing internet websites"
to be enforced even when no explicit keyword or regex condition is set.

A secondary **programmatic** path (``evaluate()``) is retained for fast,
deterministic checks in tests and as a fallback when no LLM is configured.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from agentic_bus.core.llm import get_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class IBACDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class IBACEvaluationPoint(StrEnum):
    INTENT_ADMISSION = "intent_admission"
    OFFER_ELIGIBILITY = "offer_eligibility"
    NEGOTIATION_ACCEPTANCE = "negotiation_acceptance"
    EXECUTION_AUTHORIZATION = "execution_authorization"
    ARTIFACT_EMISSION = "artifact_emission"


class IBACRequest(BaseModel):
    """Input to the IBAC engine."""

    evaluation_point: IBACEvaluationPoint

    # Identities
    requester_id: str = ""
    requester_oidc_subject: str = ""
    agent_id: str = ""

    # Intent
    intent_text: str = ""
    intent_context: dict[str, Any] = Field(default_factory=dict)

    # Scopes & capabilities
    requested_scopes: list[str] = Field(default_factory=list)
    proposed_capabilities: list[str] = Field(default_factory=list)

    # Negotiation
    negotiated_constraints: dict[str, Any] = Field(default_factory=dict)
    data_domains: list[str] = Field(default_factory=list)


class IBACResult(BaseModel):
    """Output from the IBAC engine."""

    decision: IBACDecision
    evaluation_point: IBACEvaluationPoint
    constraints: dict[str, Any] = Field(default_factory=dict)
    redactions: list[str] = Field(default_factory=list)
    negotiation_requirements: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    evaluated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class IBACPolicy(BaseModel):
    """A declarative IBAC policy rule."""

    policy_id: str
    description: str = ""
    evaluation_points: list[IBACEvaluationPoint] = Field(default_factory=list)
    allowed_scopes: list[str] = Field(default_factory=list)
    denied_scopes: list[str] = Field(default_factory=list)
    allowed_data_domains: list[str] = Field(default_factory=list)
    denied_data_domains: list[str] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class IBACEngine:
    """Intention-Based Access Control engine.

    The **primary** evaluation path is ``evaluate_with_llm()`` which presents
    active IBAC rules and the request context to the coordinator's LLM.
    The LLM semantically reasons about whether the request violates any rule
    and returns a structured governance decision.  This means rules written
    in natural language (e.g. "Prevent agents from accessing the internet")
    are enforced even without explicit keyword or regex conditions.

    A secondary **programmatic** path (``evaluate()``) is available for
    fast deterministic checks in tests and as a fallback when the LLM is
    not yet configured.

    Evaluation layers:
    1. **In-memory policies** – ``IBACPolicy`` objects added via ``add_policy``.
    2. **Persisted rules** – ``IBACRule`` rows created by admins via CLI or UI.
    """

    # -- LLM prompt for semantic IBAC evaluation --------------------------

    _IBAC_SYSTEM_PROMPT = """\
You are the IBAC (Intention-Based Access Control) governance engine of the
Agentic Bus Protocol.  Your sole purpose is to evaluate whether a request
should be ALLOWED or DENIED based on the organisation's governance rules.

## Active IBAC Rules
{rules_block}

## Instructions
1. Read every active rule carefully.
2. For each DENY rule, determine whether the current request **semantically
   violates** the rule — even if the rule has no explicit keyword or regex
   conditions.  Use the rule's name and description to understand its intent.
3. For each ALLOW rule, determine whether the request is explicitly
   permitted by the rule.
4. A DENY rule that applies takes precedence (first deny wins).
5. If a rule sets ``require_human_approval``, return ALLOW with the
   constraint ``require_human_approval: true`` instead of DENY.
6. If no rule matches, the default decision is ALLOW.

Return ONLY a JSON object (no markdown fences, no commentary):
{{
  "decision": "allow" or "deny",
  "reason": "one-sentence explanation",
  "matching_rules": ["rule-id-1"],
  "constraints": {{}}
}}
"""

    _IBAC_HUMAN_PROMPT = """\
Evaluation point: {evaluation_point}
Intent text: {intent_text}
Requester ID: {requester_id}
Agent ID: {agent_id}
Requested scopes: {requested_scopes}
Proposed capabilities: {proposed_capabilities}
Data domains: {data_domains}
"""

    def __init__(self) -> None:
        self._policies: list[IBACPolicy] = []
        self._rule_repo: Any | None = None  # lazy import to avoid circular deps

    @property
    def rule_repo(self) -> Any:
        """Lazily import and cache the rule repository."""
        if self._rule_repo is None:
            from agentic_bus.core.persistence.ibac_repository import IBACRuleRepository
            self._rule_repo = IBACRuleRepository()
        return self._rule_repo

    def add_policy(self, policy: IBACPolicy) -> None:
        self._policies.append(policy)
        logger.info("IBAC policy added: %s", policy.policy_id)

    def remove_policy(self, policy_id: str) -> None:
        self._policies = [p for p in self._policies if p.policy_id != policy_id]

    # ------------------------------------------------------------------
    # LLM-based evaluation (primary path)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_rules_for_llm(rules: list[Any]) -> str:
        """Render persisted rules into a human-readable block for the prompt."""
        if not rules:
            return "(No active rules configured.)"

        lines: list[str] = []
        for r in rules:
            ep_str = ", ".join(r.evaluation_points_json) if r.evaluation_points_json else "ALL"
            cond = r.conditions_json or {}
            cond_str = json.dumps(cond, indent=2) if cond else "(none)"
            lines.append(
                f"- **{r.rule_id}** | {r.name}\n"
                f"  Description: {r.description or '(none)'}\n"
                f"  Action: {r.action.value if hasattr(r.action, 'value') else r.action}\n"
                f"  Priority: {r.priority}\n"
                f"  Evaluation points: {ep_str}\n"
                f"  Conditions: {cond_str}"
            )
        return "\n".join(lines)

    async def evaluate_with_llm(self, request: IBACRequest) -> IBACResult:
        """Evaluate an IBAC request using the coordinator's LLM.

        The LLM receives all active rules and the request context and
        semantically determines whether any governance rule should block
        the request.  This is the **primary** evaluation path used by the
        coordinator runtime.
        """
        # --- Layer 1: fast programmatic check (in-memory policies) -------
        for policy in self._policies:
            result = self._evaluate_policy(policy, request)
            if result is not None:
                return result

        # --- Layer 2: load persisted rules -------------------------------
        try:
            rules = self.rule_repo.list_all(enabled_only=True)
        except Exception:
            rules = []

        # Filter rules by evaluation point (skip rules that don't apply)
        applicable_rules = []
        for r in rules:
            ep_list = r.evaluation_points_json or []
            if not ep_list or request.evaluation_point in ep_list:
                applicable_rules.append(r)

        if not applicable_rules:
            return IBACResult(
                decision=IBACDecision.ALLOW,
                evaluation_point=request.evaluation_point,
                reason="No applicable IBAC rules for this evaluation point",
            )

        # --- Layer 3: LLM semantic evaluation ----------------------------
        rules_block = self._format_rules_for_llm(applicable_rules)

        prompt = ChatPromptTemplate.from_messages([
            ("system", self._IBAC_SYSTEM_PROMPT),
            ("human", self._IBAC_HUMAN_PROMPT),
        ])
        parser = JsonOutputParser()

        try:
            llm = get_llm()
        except Exception:
            # No LLM configured – fall back to programmatic evaluation.
            logger.warning("No LLM configured – falling back to programmatic IBAC evaluation")
            return self.evaluate(request)

        chain = prompt | llm | parser

        try:
            llm_response = await chain.ainvoke({
                "rules_block": rules_block,
                "evaluation_point": request.evaluation_point,
                "intent_text": request.intent_text or "(none)",
                "requester_id": request.requester_id or "(unknown)",
                "agent_id": request.agent_id or "(none)",
                "requested_scopes": ", ".join(request.requested_scopes) or "(none)",
                "proposed_capabilities": ", ".join(request.proposed_capabilities) or "(none)",
                "data_domains": ", ".join(request.data_domains) or "(none)",
            })
        except Exception:
            logger.exception("LLM IBAC evaluation failed – falling back to programmatic check")
            return self.evaluate(request)

        decision_str = llm_response.get("decision", "allow").lower()
        reason = llm_response.get("reason", "")
        matching_rules = llm_response.get("matching_rules", [])
        constraints = llm_response.get("constraints", {})

        decision = IBACDecision.DENY if decision_str == "deny" else IBACDecision.ALLOW

        result = IBACResult(
            decision=decision,
            evaluation_point=request.evaluation_point,
            reason=reason,
            constraints=constraints,
        )

        if decision == IBACDecision.DENY:
            logger.warning(
                "IBAC DENY (LLM): %s | matching rules: %s",
                reason,
                matching_rules,
            )
        else:
            logger.debug(
                "IBAC ALLOW (LLM): %s | matching rules: %s",
                reason,
                matching_rules,
            )

        return result

    # ------------------------------------------------------------------
    # Programmatic evaluation (fallback / tests)
    # ------------------------------------------------------------------

    def evaluate(self, request: IBACRequest) -> IBACResult:
        """Evaluate an IBAC request against all loaded policies and persisted rules.

        Returns an ``IBACResult`` with the final governance decision.
        """
        # --- Layer 1: in-memory policies (legacy / programmatic) ---------
        for policy in self._policies:
            result = self._evaluate_policy(policy, request)
            if result is not None:
                return result

        # --- Layer 2: persisted admin rules (from DB) --------------------
        try:
            rules = self.rule_repo.list_all(enabled_only=True)
        except Exception:
            # DB may not be initialised yet (e.g. during tests).
            rules = []

        for rule in rules:
            result = self._evaluate_rule(rule, request)
            if result is not None:
                return result

        # Default: allow
        result = IBACResult(
            decision=IBACDecision.ALLOW,
            evaluation_point=request.evaluation_point,
            reason="No denying policy matched",
        )
        logger.debug("IBAC ALLOW: %s @ %s", request.requester_id, request.evaluation_point)
        return result

    # ------------------------------------------------------------------
    # In-memory policy evaluation (original logic)
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_policy(policy: IBACPolicy, request: IBACRequest) -> IBACResult | None:
        """Evaluate a single in-memory policy.  Returns ``None`` if no deny."""
        # Skip policies that don't apply to this evaluation point
        if (
            policy.evaluation_points
            and request.evaluation_point not in policy.evaluation_points
        ):
            return None

        # Check scope denials
        for scope in request.requested_scopes:
            if scope in policy.denied_scopes:
                result = IBACResult(
                    decision=IBACDecision.DENY,
                    evaluation_point=request.evaluation_point,
                    reason=f"Scope '{scope}' denied by policy '{policy.policy_id}'",
                )
                logger.warning("IBAC DENY: %s", result.reason)
                return result

        # Check data domain denials
        for domain in request.data_domains:
            if domain in policy.denied_data_domains:
                result = IBACResult(
                    decision=IBACDecision.DENY,
                    evaluation_point=request.evaluation_point,
                    reason=f"Data domain '{domain}' denied by policy '{policy.policy_id}'",
                )
                logger.warning("IBAC DENY: %s", result.reason)
                return result

        # Check allowed scopes (if specified, scopes must be in the allow list)
        if policy.allowed_scopes and request.requested_scopes:
            disallowed = set(request.requested_scopes) - set(policy.allowed_scopes)
            if disallowed:
                result = IBACResult(
                    decision=IBACDecision.DENY,
                    evaluation_point=request.evaluation_point,
                    reason=(
                        f"Scopes {disallowed} not in allow list of "
                        f"policy '{policy.policy_id}'"
                    ),
                )
                logger.warning("IBAC DENY: %s", result.reason)
                return result

        return None

    # ------------------------------------------------------------------
    # Persisted rule evaluation (programmatic / deterministic)
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_rule(rule: Any, request: IBACRequest) -> IBACResult | None:
        """Evaluate a single persisted ``IBACRule``.

        Returns an ``IBACResult`` when the rule triggers a DENY, or
        ``None`` to continue evaluation.
        """
        from agentic_bus.core.persistence.models import IBACRuleAction

        # Skip rules that don't apply to this evaluation point
        ep_list = rule.evaluation_points_json or []
        if ep_list and request.evaluation_point not in ep_list:
            return None

        conditions: dict[str, Any] = rule.conditions_json or {}
        is_deny = rule.action == IBACRuleAction.DENY
        require_human: bool = conditions.get("require_human_approval", False)

        # --- Intent keyword matching ------------------------------------
        intent_keywords: list[str] = conditions.get("intent_keywords", [])
        if intent_keywords and request.intent_text:
            text_lower = request.intent_text.lower()
            for kw in intent_keywords:
                if kw.lower() in text_lower:
                    # When require_human_approval is set, keyword matches
                    # are handled by the human-approval section below instead
                    # of triggering an immediate DENY.
                    if is_deny and not require_human:
                        result = IBACResult(
                            decision=IBACDecision.DENY,
                            evaluation_point=request.evaluation_point,
                            reason=(
                                f"Intent contains blocked keyword '{kw}' "
                                f"(rule '{rule.rule_id}')"
                            ),
                        )
                        logger.warning("IBAC DENY: %s", result.reason)
                        return result

        # --- Intent regex patterns --------------------------------------
        intent_patterns: list[str] = conditions.get("intent_patterns", [])
        if intent_patterns and request.intent_text:
            for pattern in intent_patterns:
                try:
                    if re.search(pattern, request.intent_text, re.IGNORECASE):
                        if is_deny and not require_human:
                            result = IBACResult(
                                decision=IBACDecision.DENY,
                                evaluation_point=request.evaluation_point,
                                reason=(
                                    f"Intent matches blocked pattern '{pattern}' "
                                    f"(rule '{rule.rule_id}')"
                                ),
                            )
                            logger.warning("IBAC DENY: %s", result.reason)
                            return result
                except re.error:
                    logger.warning("Invalid regex in rule %s: %s", rule.rule_id, pattern)

        # --- Agent ID filters -------------------------------------------
        blocked_agents: list[str] = conditions.get("blocked_agents", [])
        if blocked_agents and request.agent_id:
            if request.agent_id in blocked_agents:
                if is_deny:
                    result = IBACResult(
                        decision=IBACDecision.DENY,
                        evaluation_point=request.evaluation_point,
                        reason=(
                            f"Agent '{request.agent_id}' blocked by "
                            f"rule '{rule.rule_id}'"
                        ),
                    )
                    logger.warning("IBAC DENY: %s", result.reason)
                    return result

        allowed_agents: list[str] = conditions.get("allowed_agents", [])
        if allowed_agents and request.agent_id:
            if request.agent_id not in allowed_agents:
                if is_deny:
                    result = IBACResult(
                        decision=IBACDecision.DENY,
                        evaluation_point=request.evaluation_point,
                        reason=(
                            f"Agent '{request.agent_id}' not in allowed list "
                            f"(rule '{rule.rule_id}')"
                        ),
                    )
                    logger.warning("IBAC DENY: %s", result.reason)
                    return result

        # --- Scope filters ----------------------------------------------
        blocked_scopes: list[str] = conditions.get("blocked_scopes", [])
        if blocked_scopes:
            for scope in request.requested_scopes:
                if scope in blocked_scopes:
                    if is_deny:
                        result = IBACResult(
                            decision=IBACDecision.DENY,
                            evaluation_point=request.evaluation_point,
                            reason=(
                                f"Scope '{scope}' blocked by "
                                f"rule '{rule.rule_id}'"
                            ),
                        )
                        logger.warning("IBAC DENY: %s", result.reason)
                        return result

        allowed_scopes: list[str] = conditions.get("allowed_scopes", [])
        if allowed_scopes and request.requested_scopes:
            disallowed = set(request.requested_scopes) - set(allowed_scopes)
            if disallowed:
                if is_deny:
                    result = IBACResult(
                        decision=IBACDecision.DENY,
                        evaluation_point=request.evaluation_point,
                        reason=(
                            f"Scopes {disallowed} not in allowed list "
                            f"(rule '{rule.rule_id}')"
                        ),
                    )
                    logger.warning("IBAC DENY: %s", result.reason)
                    return result

        # --- Data domain filters ----------------------------------------
        blocked_domains: list[str] = conditions.get("blocked_domains", [])
        if blocked_domains:
            for domain in request.data_domains:
                if domain in blocked_domains:
                    if is_deny:
                        result = IBACResult(
                            decision=IBACDecision.DENY,
                            evaluation_point=request.evaluation_point,
                            reason=(
                                f"Data domain '{domain}' blocked by "
                                f"rule '{rule.rule_id}'"
                            ),
                        )
                        logger.warning("IBAC DENY: %s", result.reason)
                        return result

        allowed_domains: list[str] = conditions.get("allowed_domains", [])
        if allowed_domains and request.data_domains:
            disallowed = set(request.data_domains) - set(allowed_domains)
            if disallowed:
                if is_deny:
                    result = IBACResult(
                        decision=IBACDecision.DENY,
                        evaluation_point=request.evaluation_point,
                        reason=(
                            f"Data domains {disallowed} not in allowed list "
                            f"(rule '{rule.rule_id}')"
                        ),
                    )
                    logger.warning("IBAC DENY: %s", result.reason)
                    return result

        # --- Max agents constraint --------------------------------------
        max_agents: int | None = conditions.get("max_agents")
        if max_agents is not None and request.proposed_capabilities:
            if len(request.proposed_capabilities) > max_agents:
                if is_deny:
                    result = IBACResult(
                        decision=IBACDecision.DENY,
                        evaluation_point=request.evaluation_point,
                        reason=(
                            f"Composition exceeds max_agents={max_agents} "
                            f"(rule '{rule.rule_id}')"
                        ),
                    )
                    logger.warning("IBAC DENY: %s", result.reason)
                    return result

        # --- Require human approval constraint --------------------------
        if require_human and request.intent_text:
            # For require_human_approval we return ALLOW but with a
            # constraint that the runtime must enforce (block execution
            # until a human explicitly confirms).
            # Check if *any* of the keyword/pattern conditions matched
            # (i.e. this is a "flagged" intent).  If no keyword/pattern
            # conditions are set, the rule flags all intents.
            flagged = not intent_keywords and not intent_patterns
            if not flagged and intent_keywords:
                text_lower = request.intent_text.lower()
                flagged = any(kw.lower() in text_lower for kw in intent_keywords)
            if not flagged and intent_patterns:
                for pattern in intent_patterns:
                    try:
                        if re.search(pattern, request.intent_text, re.IGNORECASE):
                            flagged = True
                            break
                    except re.error:
                        pass
            if flagged:
                result = IBACResult(
                    decision=IBACDecision.ALLOW,
                    evaluation_point=request.evaluation_point,
                    reason=f"Human approval required (rule '{rule.rule_id}')",
                    constraints={"require_human_approval": True},
                )
                logger.info("IBAC ALLOW with constraint: %s", result.reason)
                return result

        return None
