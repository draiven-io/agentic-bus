"""Holding a plan to the terms the intent stated.

LIP negotiates *how* an intent is fulfilled — which agents, at what cost, in
what order — and not *what it is*. The specification relies on that
distinction everywhere and, until RFC 0004, had no field in which to express
it: an 18% discount was prose in ``intent_text`` or an unlabelled key in
``context``, so an agent offering 16% had proposed a different objective and
nothing could tell that from proposing a means.

A term gives the quantity a name, in the requester's vocabulary. An offer that
wants to constrain the same quantity names it the same way, and this module
compares the two. **Equality is the whole of the semantics.** Anything richer —
that ``max_discount: 0.16`` *narrows* ``discount: 0.18``, that three days
*satisfies* a target of five — requires knowing what the term means, and a
coordinator does not. A comparator vocabulary is a small language, and a small
language invented without implementations to check it against is how a
specification acquires a section nobody uses correctly. So: same name,
different value, that is a divergence; a divergence from a term marked
``fixed`` is a contradiction, and a contradiction stops the plan.

What this is not
----------------
Both sides of the comparison are *declared*. This catches an honest divergence
and a misconfiguration — an agent whose operational constraints say 16% while
the intent fixes 18%. It does not catch an agent that changes a term without
saying so; that is caught, if at all, at artifact emission, where the coupon
that comes out says ``0.16`` and that is the deed rather than the claim.
Describing this as more would be worse than not having it.

No model reads any of this. The check is deterministic, so no wording of the
intent text changes its outcome — which is the property that makes it a
control rather than a heuristic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "TermDivergence",
    "TermsReport",
    "apply_fixed_terms",
    "compare_terms",
    "describe_terms",
    "normalise_terms",
    "show_value",
    "values_differ",
]


@dataclass
class TermDivergence:
    """One offer constraint that names a term and does not equal it."""

    name: str
    stated: Any
    proposed: Any
    fixed: bool = False
    agent_id: str = ""
    capability_id: str = ""

    @property
    def contradiction(self) -> bool:
        """A divergence from a fixed term. The one kind that stops a plan."""
        return self.fixed

    def who(self) -> str:
        if self.agent_id and self.capability_id:
            return f"{self.agent_id}:{self.capability_id}"
        return self.agent_id or self.capability_id or "an offer"

    def __str__(self) -> str:
        verb = "fixes it at" if self.fixed else "states"
        return (
            f"{self.who()} proposes {self.name} {show_value(self.proposed)}; "
            f"the intent {verb} {show_value(self.stated)}"
        )

    def as_dict(self) -> dict[str, Any]:
        """The wire shape, carried on the composed plan and in events."""
        return {
            "name": self.name,
            "stated": self.stated,
            "proposed": self.proposed,
            "fixed": self.fixed,
            "agent_id": self.agent_id,
            "capability_id": self.capability_id,
        }


@dataclass
class TermsReport:
    """The outcome of comparing one or more offers against the intent's terms."""

    divergences: list[TermDivergence] = field(default_factory=list)

    @property
    def contradictions(self) -> list[TermDivergence]:
        """Divergences from fixed terms — what a coordinator MUST refuse."""
        return [d for d in self.divergences if d.fixed]

    @property
    def tolerated(self) -> list[TermDivergence]:
        """Divergences from non-fixed terms — permitted, and to be shown.

        A divergence a requester may accept is still one they should see:
        under equality semantics a coordinator cannot tell that three days
        *beats* a target of five, only that it differs.
        """
        return [d for d in self.divergences if not d.fixed]

    @property
    def ok(self) -> bool:
        return not self.contradictions

    def summary(self) -> str:
        if not self.divergences:
            return "every offer meets the stated terms"
        return "; ".join(str(d) for d in self.divergences)

    def extend(self, other: "TermsReport") -> None:
        self.divergences.extend(other.divergences)


def normalise_terms(terms: Iterable[Any] | None) -> list[dict[str, Any]]:
    """Read terms from models or dicts into one shape.

    The coordinator holds them as :class:`~agentic_bus.core.protocol.envelope.IntentTerm`
    models; the composed plan and the archive carry them as dicts. A term
    without a name is dropped — there is nothing to compare it against.
    """
    out: list[dict[str, Any]] = []
    for term in terms or ():
        if hasattr(term, "model_dump"):
            term = term.model_dump()
        if not isinstance(term, Mapping):
            continue
        name = term.get("name")
        if not name:
            continue
        out.append(
            {
                "name": str(name),
                "value": term.get("value"),
                "fixed": bool(term.get("fixed", False)),
            }
        )
    return out


def values_differ(stated: Any, proposed: Any) -> bool:
    """Whether two term values are different, under equality.

    Plain ``!=`` with one correction: Python reads ``True == 1`` and a term
    of ``enabled: true`` answered with ``enabled: 1`` is a different claim,
    not the same one. Numbers compare as numbers (``5 == 5.0``), because
    a requester writing ``5`` and an agent answering ``5.0`` agree.
    """
    if isinstance(stated, bool) != isinstance(proposed, bool):
        return True
    try:
        return bool(stated != proposed)
    except Exception:  # noqa: BLE001 - exotic values; unequal is the safe answer
        return True


def compare_terms(
    terms: Iterable[Any] | None,
    constraints: Mapping[str, Any] | None,
    *,
    agent_id: str = "",
    capability_id: str = "",
) -> TermsReport:
    """Compare one offer's constraints against the intent's terms.

    An offer contradicts a term when its constraints carry the same ``name``
    with a different value; that is the required semantics and all of it. A
    constraint naming no term, or a term no constraint names, is not a
    divergence — an offer is not obliged to answer every term, only not to
    alter the ones it answers.
    """
    report = TermsReport()
    if not constraints:
        return report
    for term in normalise_terms(terms):
        name = term["name"]
        if name not in constraints:
            continue
        proposed = constraints[name]
        if values_differ(term["value"], proposed):
            report.divergences.append(
                TermDivergence(
                    name=name,
                    stated=term["value"],
                    proposed=proposed,
                    fixed=term["fixed"],
                    agent_id=agent_id,
                    capability_id=capability_id,
                )
            )
    return report


def apply_fixed_terms(
    inputs: Mapping[str, Any],
    terms: Iterable[Any] | None,
) -> tuple[dict[str, Any], list[TermDivergence]]:
    """Hold composed step parameters to the intent's fixed terms.

    RFC 0005 composes a step's parameters from the intent with a model, and
    RFC 0004 says of that: *composition proposes; a fixed term is not a
    proposal.* A composed parameter that names a fixed term and disagrees
    with it is replaced by the stated value. This is not the reconciliation
    the coordinator is forbidden between an offer and a term — those are two
    parties' declarations — it is the coordinator correcting its *own*
    derivation against the one thing in the interaction that is not derived.

    Only keys the composition produced are touched. A fixed term the schema
    has no field for is not injected: the term governs a field, it does not
    add one.
    """
    fixed = {t["name"]: t["value"] for t in normalise_terms(terms) if t["fixed"]}
    if not fixed:
        return dict(inputs), []
    corrected = dict(inputs)
    overridden: list[TermDivergence] = []
    for name, stated in fixed.items():
        if name in corrected and values_differ(stated, corrected[name]):
            overridden.append(
                TermDivergence(
                    name=name, stated=stated, proposed=corrected[name], fixed=True
                )
            )
            corrected[name] = stated
    return corrected, overridden


def describe_terms(terms: Iterable[Any] | None) -> str:
    """The terms as a model should see them: values with their fixity spelt out.

    Used where a prompt is shown the intent — discovery, decomposition, step
    composition — so a model reading ``discount: 0.18 (fixed)`` does not
    treat the number as one it may improve on.
    """
    lines = []
    for term in normalise_terms(terms):
        fixity = "fixed — no plan may change it" if term["fixed"] else "a target"
        lines.append(f"  {term['name']}: {show_value(term['value'])} ({fixity})")
    return "\n".join(lines) if lines else "  (none stated)"


def show_value(value: Any) -> str:
    """A term value as it reads in a message: JSON, so ``0.18`` and ``"0.18"`` differ."""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return repr(value)
