"""IBAC – Intention-Based Access Control (§6.1 of the Agentic Bus paper / §6 of AGENTS.md).

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
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

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

    Policies are evaluated in order; first *deny* wins.  If no policy denies,
    default is *allow*.  This keeps the system open-by-default while
    organisations add restrictive policies as needed.
    """

    def __init__(self) -> None:
        self._policies: list[IBACPolicy] = []

    def add_policy(self, policy: IBACPolicy) -> None:
        self._policies.append(policy)
        logger.info("IBAC policy added: %s", policy.policy_id)

    def remove_policy(self, policy_id: str) -> None:
        self._policies = [p for p in self._policies if p.policy_id != policy_id]

    def evaluate(self, request: IBACRequest) -> IBACResult:
        """Evaluate an IBAC request against all loaded policies.

        Returns an ``IBACResult`` with the final governance decision.
        """
        for policy in self._policies:
            # Skip policies that don't apply to this evaluation point
            if (
                policy.evaluation_points
                and request.evaluation_point not in policy.evaluation_points
            ):
                continue

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

        # Default: allow
        result = IBACResult(
            decision=IBACDecision.ALLOW,
            evaluation_point=request.evaluation_point,
            reason="No denying policy matched",
        )
        logger.debug("IBAC ALLOW: %s @ %s", request.requester_id, request.evaluation_point)
        return result
