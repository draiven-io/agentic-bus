"""Holding an agent to the shape its offer promised.

An offer carries an ``output_schema``. Every implementation of this protocol
sends one; none has ever checked one. So an agent could promise
``{"routes": [...]}`` and deliver ``{"result": "ok"}``, and the interaction
would proceed — until the next step, which consumes the artifact and assumes a
field that is not there.

That is the expensive part: the failure surfaces one or two hops from its
cause. Checking at the boundary costs a schema validation and turns a
mysterious downstream error into a named agent and a named promise.

What this is not
----------------
It does not make an artifact *correct*. An agent whose schema matches what it
produces, where both are wrong for the intent, passes. This guarantees
coherence between an offer and its artifact — nothing about the truth of
either — and describing it as more would be worse than not having it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ArtifactViolation:
    """One artifact that did not match the schema its offer declared."""

    agent_id: str
    capability_id: str
    index: int
    reason: str
    #: The property path that failed, when the validator reports one.
    path: str = ""

    def __str__(self) -> str:
        where = f" at {self.path}" if self.path else ""
        return (
            f"artifact {self.index} from {self.agent_id}:{self.capability_id} "
            f"does not match its declared schema{where}: {self.reason}"
        )


@dataclass
class ValidationReport:
    """The outcome of checking one completion's artifacts."""

    agent_id: str = ""
    capability_id: str = ""
    checked: int = 0
    violations: list[ArtifactViolation] = field(default_factory=list)
    #: True when no schema was declared, so nothing could be checked. Distinct
    #: from "checked and found nothing wrong", and the specification is
    #: explicit that it is not a failure: an agent that cannot describe its
    #: output is still useful, and demanding a schema from every agent would
    #: exclude the exploratory ones this protocol exists to accommodate.
    unchecked: bool = False

    @property
    def ok(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        if self.unchecked:
            return "no output_schema declared; nothing to check"
        if self.ok:
            return f"{self.checked} artifact(s) matched the declared schema"
        return "; ".join(str(v) for v in self.violations)


def validate_artifacts(
    artifacts: list[Any],
    output_schema: dict[str, Any] | None,
    *,
    agent_id: str = "",
    capability_id: str = "",
) -> ValidationReport:
    """Check artifacts against the schema an offer declared.

    An absent or empty schema returns an *unchecked* report rather than a
    passing one. The distinction matters when reading an audit trail: "we
    verified this" and "nobody promised anything" are different facts, and
    collapsing them makes the log say more than it knows.
    """
    report = ValidationReport(agent_id=agent_id, capability_id=capability_id)

    if not output_schema:
        report.unchecked = True
        return report

    try:
        import jsonschema
    except ImportError:  # pragma: no cover - jsonschema is a base dependency
        logger.warning("jsonschema is unavailable; artifacts cannot be validated")
        report.unchecked = True
        return report

    try:
        validator_cls = jsonschema.validators.validator_for(output_schema)
        validator_cls.check_schema(output_schema)
        validator = validator_cls(output_schema)
    except Exception as exc:
        # A schema that will not compile is the offering agent's defect, and
        # reporting it as an artifact violation would blame the wrong thing.
        logger.warning(
            "Agent %s declared an unusable output_schema for %s: %s",
            agent_id,
            capability_id,
            exc,
        )
        report.unchecked = True
        return report

    for index, artifact in enumerate(artifacts):
        report.checked += 1
        for error in validator.iter_errors(artifact):
            report.violations.append(
                ArtifactViolation(
                    agent_id=agent_id,
                    capability_id=capability_id,
                    index=index,
                    reason=error.message,
                    path="/".join(str(p) for p in error.absolute_path),
                )
            )

    return report
