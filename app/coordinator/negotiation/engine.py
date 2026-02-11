"""Semantic capability matching and negotiation orchestration.

Implements:
- LLM-based semantic adjudication (§4.1.2)
- Outcome-informed ranking (equation 8)
- Offer composition and scoring
- Negotiation loop with renegotiation support (§4.1.3)
- Entropy threshold and fallback modes (§5.3)
"""

from __future__ import annotations

import logging
import math
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from app.core.llm import get_llm
from app.core.protocol.envelope import IntentPayload, OfferPayload
from app.core.registry.capability_registry import CapabilityRegistry
from app.core.session.manager import NegotiationRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Semantic adjudicator prompt
# ---------------------------------------------------------------------------

_ADJUDICATOR_SYSTEM = """\
You are the semantic adjudicator of the Agentic Bus Protocol.
Given an intention Φ, contextual state C, and a set of declared agent
capabilities, determine which agents are semantically and operationally
compatible with the intended objective.

For each candidate produce:
- suitability_score (0.0 – 1.0): estimated fitness for the intention.
- justification: structured rationale for the score.
- acceptable: boolean – whether the agent should enter negotiation.

Return JSON:
{{
  "candidates": [
    {{
      "agent_id": "<id>",
      "capability_id": "<id>",
      "suitability_score": 0.0,
      "justification": "<reason>",
      "acceptable": true
    }}
  ]
}}

Rank candidates by descending suitability_score.
Only mark as acceptable those whose capabilities genuinely advance the intent.
"""


class CandidateScore(object):
    """Scored agent capability candidate."""

    __slots__ = ("agent_id", "capability_id", "semantic_score", "outcome_prior",
                 "combined_score", "justification", "acceptable")

    def __init__(
        self,
        agent_id: str,
        capability_id: str,
        semantic_score: float = 0.0,
        outcome_prior: float = 0.5,
        justification: str = "",
        acceptable: bool = False,
        alpha: float = 0.7,
    ):
        self.agent_id = agent_id
        self.capability_id = capability_id
        self.semantic_score = semantic_score
        self.outcome_prior = outcome_prior
        # Equation 8: s'_i = α · s_i + (1 - α) · ρ_i
        self.combined_score = alpha * semantic_score + (1 - alpha) * outcome_prior
        self.justification = justification
        self.acceptable = acceptable


class SemanticAdjudicator:
    """LLM-based semantic capability matching (§4.1.2).

    Implements ``f_LLM: (Φ, C_t, {c_i}) -> {(c_i, s_i, r_i)}`` from eq. 7.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        llm: BaseChatModel | None = None,
        threshold: float = 0.4,
        alpha: float = 0.7,
    ):
        self._registry = registry
        self._llm = llm or get_llm()
        self._threshold = threshold
        self._alpha = alpha
        self._outcome_priors: dict[str, float] = {}  # agent_id -> ρ_i

        self._prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _ADJUDICATOR_SYSTEM),
                (
                    "human",
                    "Intention: {intent_text}\n"
                    "Context: {context}\n\n"
                    "Available capabilities:\n{capabilities}",
                ),
            ]
        )
        self._parser = JsonOutputParser()
        self._chain = self._prompt | self._llm | self._parser

    async def discover(
        self,
        intent: IntentPayload,
    ) -> list[CandidateScore]:
        """Discover and rank agents for the given intent.

        Returns a list of ``CandidateScore`` objects sorted by combined score.
        """
        summaries = self._registry.capability_summaries()
        if not summaries:
            logger.warning("No agents registered – discovery returns empty")
            return []

        result = await self._chain.ainvoke(
            {
                "intent_text": intent.intent_text,
                "context": str(intent.context),
                "capabilities": str(summaries),
            }
        )

        candidates: list[CandidateScore] = []
        for c in result.get("candidates", []):
            prior = self._outcome_priors.get(c["agent_id"], 0.5)
            cs = CandidateScore(
                agent_id=c["agent_id"],
                capability_id=c.get("capability_id", ""),
                semantic_score=c.get("suitability_score", 0.0),
                outcome_prior=prior,
                justification=c.get("justification", ""),
                acceptable=c.get("acceptable", False),
                alpha=self._alpha,
            )
            if cs.combined_score >= self._threshold and cs.acceptable:
                candidates.append(cs)

        candidates.sort(key=lambda x: x.combined_score, reverse=True)
        logger.info("Discovery found %d eligible candidates", len(candidates))
        return candidates

    def update_outcome_prior(self, agent_id: str, success: bool) -> None:
        """Incrementally update the outcome prior for an agent (eq. 8)."""
        current = self._outcome_priors.get(agent_id, 0.5)
        delta = 0.05 if success else -0.05
        self._outcome_priors[agent_id] = max(0.0, min(1.0, current + delta))


# ---------------------------------------------------------------------------
# Negotiation engine
# ---------------------------------------------------------------------------

class NegotiationEngine:
    """Orchestrates the negotiation loop (§11 of AGENTS.md / §5.2 of the paper).

    Supports:
    - Multiple parallel offers
    - Partial composition of offers
    - Renegotiation loops
    - Entropy-based convergence check (§5.3.1)
    - Recursive simplification & solidification fallbacks (§5.3.2)
    """

    def __init__(
        self,
        tau: float = 0.5,
        max_rounds: int = 5,
    ):
        self._tau = tau  # entropy tolerance (§5.3.1)
        self._max_rounds = max_rounds

    def compute_semantic_entropy(self, offers: list[NegotiationRecord]) -> float:
        """Approximate semantic entropy H(S) from offer states.

        Uses a simple information-theoretic proxy: entropy over the distribution
        of offer statuses.  In a production system this would incorporate the
        LLM-estimated semantic alignment scores.
        """
        if not offers:
            return 1.0  # maximum uncertainty

        statuses = [o.status for o in offers]
        total = len(statuses)
        counts: dict[str, int] = {}
        for s in statuses:
            counts[s] = counts.get(s, 0) + 1

        entropy = 0.0
        for count in counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        # Normalise to [0, 1]
        max_entropy = math.log2(max(len(counts), 2))
        return entropy / max_entropy if max_entropy > 0 else 0.0

    def check_convergence(
        self,
        offers: list[NegotiationRecord],
        initial_entropy: float,
    ) -> bool:
        """Check if negotiation has converged per §5.3.1.

        Convergence: H(S)_n < (1 - τ) · H_0
        """
        current = self.compute_semantic_entropy(offers)
        h_max = (1 - self._tau) * initial_entropy
        converged = current <= h_max
        logger.debug(
            "Negotiation entropy: %.3f (threshold: %.3f) → %s",
            current,
            h_max,
            "converged" if converged else "not converged",
        )
        return converged

    def compose_offers(
        self,
        offers: list[NegotiationRecord],
    ) -> dict[str, Any]:
        """Build a composition plan from accepted offers (§5.1.4).

        Returns a plan describing the ordered execution of accepted agents.
        """
        accepted = [o for o in offers if o.status == "accepted"]
        if not accepted:
            return {"steps": [], "viable": False}

        steps = [
            {
                "agent_id": o.agent_id,
                "capability_id": o.offer.capability_id,
                "description": o.offer.capability_description,
                "constraints": o.offer.constraints,
                "output_schema": o.offer.output_schema,
            }
            for o in accepted
        ]
        return {"steps": steps, "viable": True}

    def needs_fallback(
        self,
        round_num: int,
        offers: list[NegotiationRecord],
        initial_entropy: float,
    ) -> str | None:
        """Determine if a fallback mode is needed (§5.3.2).

        Returns:
        - ``None`` if negotiation may proceed.
        - ``"recursive_simplification"`` if the intent should be simplified.
        - ``"solidification"`` if the protocol should anchor to a core ontology.
        """
        if round_num < self._max_rounds:
            return None

        if not self.check_convergence(offers, initial_entropy):
            # First attempt: recursive simplification (Φ' ⊂ Φ)
            if round_num <= self._max_rounds:
                return "recursive_simplification"
            # Beyond max rounds: solidify to Σ_core
            return "solidification"

        return None
