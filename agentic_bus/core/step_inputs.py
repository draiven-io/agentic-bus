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

WHAT EARLIER STEPS REPORTED (their artifacts):
{prior}

WHAT EARLIER STEPS LEFT IN SHARED MEMORY (key: shape — the data itself is
not shown to you and must not be copied):
{memory}

Return ONLY a JSON object matching that schema.

Rules:
- Fill a field from the intent when the intent supports it. Use its own
  words; do not embellish; do not invent.
- Fill a field from shared memory by REFERENCE, never by value. A reference
  is an object in one of these forms, and the coordinator resolves it:
    {{"$from": "<memory key>"}}                          the whole value
    {{"$from": "<memory key>", "$path": "a.b"}}          a sub-value
    {{"$from": "<memory key>", "$fields": {{"dest": "src"}}}}
                                                        for a list of objects,
                                                        keep/rename fields
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
    memory: dict[str, Any] | None = None,
    llm: Any = None,
) -> ComposedInputs:
    """Fill one step's declared parameters from the intent and prior steps.

    *memory* is what this step may read from the session's shared store, as
    the coordinator filtered it. **The model never sees its contents.** It is
    shown each key with a description of the value's *shape* — a list of so
    many objects with these fields, say — and fills a parameter from memory by
    returning a reference, which :func:`resolve_refs` substitutes
    deterministically afterwards. The model writes the mapping; code applies
    it to the data. That is what keeps forty thousand customer rows out of a
    prompt while still letting a later step be parameterised from them.

    This is also where two agents that never met get joined. The producer
    published the shape of what it made; the consumer published the shape of
    what it needs; neither named the other. The mapping between the two is
    computed here, for this interaction, and does not outlive it.

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

    memory = memory or {}
    shapes = "\n".join(f"  {k}: {describe_shape(v)}" for k, v in memory.items())
    prompt = _PROMPT.format(
        intent_text=intent_text,
        agent_id=agent_id,
        capability_id=capability_id,
        description=step.get("description", ""),
        input_schema=json.dumps(schema, indent=2, ensure_ascii=False),
        prior=json.dumps(prior_results or {}, indent=2, default=str)[:2000] or "{}",
        memory=shapes or "  (nothing)",
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

    # References are resolved *before* validation, so what the schema checks
    # is what the agent will actually receive. A reference to a key that is
    # not in this step's memory is a composition error like any other — the
    # model named something the plan never granted this step.
    try:
        inputs = resolve_refs(inputs, memory)
    except KeyError as exc:
        return ComposedInputs(
            agent_id=agent_id,
            capability_id=capability_id,
            violations=[f"reference to memory this step cannot read: {exc}"],
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


# ---------------------------------------------------------------------------
# Shapes and references
#
# The model composing a step's parameters is shown what earlier steps left in
# memory as *shapes*, never as values. It fills a parameter from memory by
# returning a reference; code resolves the reference against the data. The
# split is the same one that keeps a dataset out of an agent's model context:
# the model decides the operation, deterministic code performs it.
# ---------------------------------------------------------------------------

_SHAPE_SAMPLE = 3
_SHAPE_KEYS = 12


def describe_shape(value: Any, *, depth: int = 0) -> str:
    """A short, data-free description of *value*'s structure.

    ``[{"id": 1, "nome": "A"}, ...]`` becomes ``list[2] of {id, nome}``. No
    value is ever included: a key name is structure, a cell is data.
    """
    if isinstance(value, dict):
        keys = list(value)[:_SHAPE_KEYS]
        more = "" if len(value) <= _SHAPE_KEYS else ", …"
        return "{" + ", ".join(str(k) for k in keys) + more + "}"
    if isinstance(value, list):
        if not value:
            return "list[0]"
        head = value[0]
        if isinstance(head, dict):
            # Union of keys over a small sample, so a sparse first row does
            # not hide a field the rest of the list carries.
            keys: dict[str, None] = {}
            for item in value[:_SHAPE_SAMPLE]:
                if isinstance(item, dict):
                    keys.update(dict.fromkeys(item))
            inner = "{" + ", ".join(list(keys)[:_SHAPE_KEYS]) + "}"
        elif depth < 1:
            inner = describe_shape(head, depth=depth + 1)
        else:
            inner = type(head).__name__
        return f"list[{len(value)}] of {inner}"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return f"string[{len(value)}]"
    if isinstance(value, (int, float)):
        return type(value).__name__
    if value is None:
        return "null"
    return type(value).__name__


def _is_ref(obj: Any) -> bool:
    return isinstance(obj, dict) and "$from" in obj


def _walk_path(value: Any, path: str) -> Any:
    for part in [p for p in path.split(".") if p]:
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        else:
            raise KeyError(path)
    return value


def _project(value: Any, fields: dict[str, str]) -> Any:
    """Keep/rename *fields* (``dest -> src``) on an object, or on each object
    of a list. A source field missing from a row is simply absent from the
    result rather than an error: rows are allowed to be sparse."""

    def one(obj: Any) -> Any:
        if not isinstance(obj, dict):
            return obj
        return {dest: obj[src] for dest, src in fields.items() if src in obj}

    if isinstance(value, list):
        return [one(item) for item in value]
    return one(value)


def resolve_refs(inputs: Any, memory: dict[str, Any] | None) -> Any:
    """Substitute every ``{"$from": ...}`` in *inputs* with data from *memory*.

    Recurses through objects and lists. A reference to a key not in *memory*
    raises ``KeyError`` — the caller reports it as a composition violation,
    because the model asked for something this step was never granted.
    """
    memory = memory or {}
    if _is_ref(inputs):
        key = inputs["$from"]
        if key not in memory:
            raise KeyError(key)
        value = memory[key]
        if "$path" in inputs:
            value = _walk_path(value, str(inputs["$path"]))
        if isinstance(inputs.get("$fields"), dict):
            value = _project(value, {str(k): str(v) for k, v in inputs["$fields"].items()})
        return value
    if isinstance(inputs, dict):
        return {k: resolve_refs(v, memory) for k, v in inputs.items()}
    if isinstance(inputs, list):
        return [resolve_refs(v, memory) for v in inputs]
    return inputs
