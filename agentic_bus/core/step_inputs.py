"""Composing each step's parameters from the intent.

A plan used to say *who* runs and never *what they run with*. The requester's
``context`` travelled to every step unchanged, so whoever wrote the intent had
to know that step two would be a document agent expecting ``descricao`` — a
contract, written in a JSON blob instead of an OpenAPI document, but a
contract. The thing this protocol exists to dissolve had moved rather than
gone.

The missing half is symmetry. A capability declares ``output_schema`` and is
held to it at emission (RFC 0002); it declares nothing about what it needs to
be *told*. Declaring that lets the coordinator fill it — which is where the
work belongs, because the coordinator is the only party holding the intent,
every capability's description, and no credential at all.

That last clause is the argument. Somebody has to turn prose into parameters.
Done in the agent it puts a model next to a credential, reading text an
attacker may have influenced. Done here it puts a model where there is nothing
to steal.

What is composed is validated before it is sent. A parameter set that does not
match the schema the agent published is a composition error, not something to
discover mid-execution — the same reasoning that validates an artifact against
the schema its offer promised, applied to the other direction.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_PROMPT = """You are composing the parameters for one step of an execution plan.

THE REQUESTER'S INTENT:
{intent_text}

THE STEP:
  agent: {agent_id}
  capability: {capability_id}
  what it does: {description}

THE PARAMETERS IT DECLARED IT NEEDS (JSON Schema):
{input_schema}

WHAT EARLIER STEPS ALREADY PRODUCED:
{prior}

Return ONLY a JSON object matching that schema, filled from the intent.

Rules:
- Use the intent's own words for free-text fields. Do not embellish, and do
  not invent a value the intent does not support.
- Omit an optional field you cannot fill rather than guessing.
- Return the object alone. No prose, no markdown fence, no explanation."""


@dataclass
class ComposedInputs:
    """One step's parameters, and whether they can be trusted to be sent."""

    agent_id: str = ""
    capability_id: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    #: True when the capability declared no ``input_schema``. Distinct from
    #: composing successfully and finding nothing to fill: an agent that
    #: publishes no shape is not one whose parameters we failed to compose.
    unchecked: bool = False
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        if self.unchecked:
            return "no input_schema declared; nothing to compose"
        if self.ok:
            return f"composed {len(self.inputs)} parameter(s)"
        return "; ".join(self.violations)


def validate_inputs(
    inputs: dict[str, Any],
    input_schema: dict[str, Any] | None,
    *,
    agent_id: str = "",
    capability_id: str = "",
) -> ComposedInputs:
    """Check composed parameters against the schema the agent published.

    An absent schema returns an *unchecked* result rather than a passing one,
    for the same reason artifact validation does: "we verified this" and
    "nobody published a shape" are different facts.
    """
    result = ComposedInputs(
        agent_id=agent_id, capability_id=capability_id, inputs=dict(inputs)
    )

    if not input_schema:
        result.unchecked = True
        return result

    try:
        import jsonschema
    except ImportError:  # pragma: no cover - jsonschema is a base dependency
        logger.warning("jsonschema is unavailable; inputs cannot be validated")
        result.unchecked = True
        return result

    try:
        validator_cls = jsonschema.validators.validator_for(input_schema)
        validator_cls.check_schema(input_schema)
        validator = validator_cls(input_schema)
    except Exception as exc:
        # An unusable schema is the offering agent's defect; calling it a
        # composition failure would blame the wrong party.
        logger.warning(
            "Agent %s published an unusable input_schema for %s: %s",
            agent_id,
            capability_id,
            exc,
        )
        result.unchecked = True
        return result

    for error in validator.iter_errors(inputs):
        path = "/".join(str(p) for p in error.absolute_path)
        result.violations.append(f"{path or '<root>'}: {error.message}")

    return result


async def compose_step_inputs(
    *,
    intent_text: str,
    step: dict[str, Any],
    prior_results: dict[str, Any] | None = None,
    llm: Any = None,
) -> ComposedInputs:
    """Fill one step's declared parameters from the intent.

    Falls back to an empty parameter set rather than raising. A step whose
    parameters could not be composed is reported through
    :attr:`ComposedInputs.violations` so the caller decides what that means —
    refusing to execute on a half-filled request belongs to the caller, not
    here.
    """
    schema = step.get("input_schema") or {}
    agent_id = step.get("agent_id", "")
    capability_id = step.get("capability_id", "")

    if not schema:
        return ComposedInputs(
            agent_id=agent_id, capability_id=capability_id, unchecked=True
        )

    if llm is None:
        from agentic_bus.core.llm import get_llm

        try:
            llm = get_llm()
        except Exception as exc:
            # `get_llm()` raises when nothing is configured rather than
            # returning None, and a deployment without a model still runs —
            # it just composes nothing, and the requester's context reaches
            # the agent as it did before this existed. Letting this propagate
            # would take plan composition down over an optional feature.
            logger.info(
                "No LLM available; %s:%s receives no composed parameters (%s)",
                agent_id,
                capability_id,
                type(exc).__name__,
            )
            return ComposedInputs(
                agent_id=agent_id,
                capability_id=capability_id,
                violations=["no LLM available to compose parameters"],
            )

    prompt = _PROMPT.format(
        intent_text=intent_text,
        agent_id=agent_id,
        capability_id=capability_id,
        description=step.get("description", ""),
        input_schema=json.dumps(schema, indent=2, ensure_ascii=False),
        prior=json.dumps(prior_results or {}, indent=2, default=str)[:2000] or "{}",
    )

    try:
        response = await llm.ainvoke(prompt)
        raw = getattr(response, "content", response)
        inputs = _parse(raw)
    except Exception as exc:
        logger.warning(
            "Composing parameters for %s:%s failed: %s", agent_id, capability_id, exc
        )
        return ComposedInputs(
            agent_id=agent_id,
            capability_id=capability_id,
            violations=[f"composition failed: {type(exc).__name__}: {exc}"],
        )

    if not isinstance(inputs, dict):
        return ComposedInputs(
            agent_id=agent_id,
            capability_id=capability_id,
            violations=[f"composition returned {type(inputs).__name__}, not an object"],
        )

    return validate_inputs(
        inputs, schema, agent_id=agent_id, capability_id=capability_id
    )


def _parse(raw: Any) -> Any:
    """Read the object out of a model's answer, fence and all."""
    if isinstance(raw, dict):
        return raw
    text = str(raw).strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return json.loads(text)
