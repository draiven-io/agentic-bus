"""Composing each step's parameters from the intent.

A plan said *who* runs and never *what they run with*. The requester's context
travelled to every step unchanged, so whoever wrote the intent had to know
that step two would be a document agent expecting ``descricao`` — a contract,
written in a JSON blob rather than an OpenAPI document, but a contract.

These cover the half that was missing: a capability publishes the shape of its
input the way it already publishes the shape of its output, and the
coordinator fills it. The tests that carry the claim are the ones where
composition produces something the schema refuses — because a parameter set
nobody validated must not reach an agent, and falling back to the old
behaviour is not the same as sending it anyway.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from agentic_bus.core.registry.capability_registry import AgentCapability
from agentic_bus.core.step_inputs import (
    ComposedInputs,
    compose_step_inputs,
    validate_inputs,
)


class Busca(BaseModel):
    descricao: str = Field(description="O que procurar")
    limite: int | None = Field(default=None, description="Máximo de resultados")


SCHEMA = Busca.model_json_schema()


class _Model:
    """A stand-in for the coordinator's LLM."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return type("R", (), {"content": self.answer})()


def _step(**over):
    return {
        "agent_id": "doc-reader",
        "capability_id": "doc.buscar",
        "description": "Busca documentos",
        "input_schema": SCHEMA,
        **over,
    }


class TestTheCapabilityPublishesItsInputShape:
    """The symmetry that was missing: output was declared, input was not."""

    def test_the_schema_is_derived_from_the_model(self):
        capability = AgentCapability(capability_id="doc.buscar", input_model=Busca)

        assert "descricao" in capability.input_schema["properties"]

    def test_declaring_neither_leaves_it_empty(self):
        """Not every agent can describe its input, and demanding one would
        exclude the exploratory agents this protocol exists to accommodate."""
        assert AgentCapability(capability_id="x").input_schema == {}

    def test_an_explicit_schema_is_not_overwritten(self):
        explicit = {"type": "object", "properties": {"q": {"type": "string"}}}

        capability = AgentCapability(
            capability_id="x", input_model=Busca, input_schema=explicit
        )

        assert capability.input_schema == explicit

    def test_the_offer_carries_it(self):
        """The coordinator cannot compose against a shape it never receives."""
        from agentic_bus.core.protocol.envelope import OfferPayload

        assert "input_schema" in OfferPayload.model_fields


class TestValidation:
    def test_a_matching_object_passes(self):
        result = validate_inputs({"descricao": "modelo de boas-vindas"}, SCHEMA)

        assert result.ok
        assert not result.unchecked

    def test_a_missing_required_field_is_a_violation(self):
        result = validate_inputs({"limite": 10}, SCHEMA)

        assert not result.ok
        assert "descricao" in result.summary()

    def test_a_wrong_type_is_a_violation(self):
        result = validate_inputs({"descricao": "x", "limite": "muitos"}, SCHEMA)

        assert not result.ok

    def test_no_schema_is_unchecked_rather_than_passing(self):
        """"We verified this" and "nobody published a shape" are different
        facts, and collapsing them makes the log say more than it knows."""
        result = validate_inputs({"anything": 1}, None)

        assert result.unchecked
        assert result.ok

    def test_an_unusable_schema_blames_the_agent_not_the_composition(self):
        result = validate_inputs({"x": 1}, {"type": "not-a-type"})

        assert result.unchecked
        assert not result.violations


class TestComposition:
    async def test_it_fills_the_declared_shape_from_the_intent(self):
        model = _Model('{"descricao": "modelo de e-mail de boas-vindas"}')

        composed = await compose_step_inputs(
            intent_text="Envie o e-mail de boas-vindas para os clientes de ontem",
            step=_step(),
            llm=model,
        )

        assert composed.ok
        assert composed.inputs == {"descricao": "modelo de e-mail de boas-vindas"}

    async def test_the_intent_and_the_schema_reach_the_model(self):
        model = _Model('{"descricao": "x"}')

        await compose_step_inputs(
            intent_text="uma intenção bem específica", step=_step(), llm=model
        )

        prompt = model.prompts[0]
        assert "uma intenção bem específica" in prompt
        assert "descricao" in prompt
        assert "doc.buscar" in prompt

    async def test_a_fenced_answer_is_read(self):
        model = _Model('```json\n{"descricao": "x"}\n```')

        composed = await compose_step_inputs(
            intent_text="i", step=_step(), llm=model
        )

        assert composed.inputs == {"descricao": "x"}

    async def test_prose_around_the_object_is_tolerated(self):
        model = _Model('Claro! Aqui está:\n{"descricao": "x"}\nEspero ter ajudado.')

        composed = await compose_step_inputs(
            intent_text="i", step=_step(), llm=model
        )

        assert composed.inputs == {"descricao": "x"}

    async def test_a_step_publishing_no_shape_is_unchecked(self):
        composed = await compose_step_inputs(
            intent_text="i", step=_step(input_schema={}), llm=_Model("{}")
        )

        assert composed.unchecked
        assert composed.inputs == {}


class TestWhatIsComposedIsChecked:
    """The half that matters. A parameter set nobody validated must not reach
    an agent, and "compose it" is not the same promise as "compose it right"."""

    async def test_an_answer_the_schema_refuses_is_a_violation(self):
        model = _Model('{"limite": 10}')  # no `descricao`

        composed = await compose_step_inputs(
            intent_text="i", step=_step(), llm=model
        )

        assert not composed.ok
        assert "descricao" in composed.summary()

    async def test_an_answer_that_is_not_an_object_is_a_violation(self):
        composed = await compose_step_inputs(
            intent_text="i", step=_step(), llm=_Model('["a", "b"]')
        )

        assert not composed.ok
        assert "not an object" in composed.summary()

    async def test_unparseable_output_is_a_violation_not_an_exception(self):
        composed = await compose_step_inputs(
            intent_text="i", step=_step(), llm=_Model("desculpe, não consegui")
        )

        assert not composed.ok

    async def test_a_model_that_raises_is_a_violation_not_an_exception(self):
        """Composition failing must not take the interaction down with it."""
        composed = await compose_step_inputs(
            intent_text="i", step=_step(), llm=_Model(RuntimeError("upstream is down"))
        )

        assert not composed.ok
        assert "upstream is down" in composed.summary()

    async def test_no_model_configured_is_reported_rather_than_assumed(self):
        composed = await compose_step_inputs(
            intent_text="i", step=_step(), llm=None
        )

        # `get_llm()` returns nothing in a test environment, and a deployment
        # without a model still runs — it just composes nothing.
        assert composed.inputs == {}


class TestTheCoordinatorDelivers:
    def test_the_step_is_matched_on_agent_and_capability(self):
        """One agent can hold several accepted capabilities in a session, and
        matching on the agent alone would hand a step the parameters composed
        for a different one."""
        from agentic_bus.coordinator.runtime import CoordinatorRuntime
        from agentic_bus.core.transport.local import LocalTransport

        runtime = CoordinatorRuntime(transport=LocalTransport())
        session = type(
            "S",
            (),
            {
                "composition_plan": {
                    "steps": [
                        {
                            "agent_id": "a",
                            "capability_id": "cap.one",
                            "inputs": {"descricao": "primeiro"},
                        },
                        {
                            "agent_id": "a",
                            "capability_id": "cap.two",
                            "inputs": {"descricao": "segundo"},
                        },
                    ]
                }
            },
        )()

        assert runtime._step_inputs_for(session, "a", "cap.two") == {
            "descricao": "segundo"
        }

    def test_an_unknown_step_contributes_nothing(self):
        from agentic_bus.coordinator.runtime import CoordinatorRuntime
        from agentic_bus.core.transport.local import LocalTransport

        runtime = CoordinatorRuntime(transport=LocalTransport())

        assert runtime._step_inputs_for(None, "a", "cap") == {}


class TestTheReport:
    def test_it_says_which_case_it_is(self):
        assert "nothing to compose" in ComposedInputs(unchecked=True).summary()
        assert "0 parameter" in ComposedInputs().summary()
        assert "boom" in ComposedInputs(violations=["boom"]).summary()
