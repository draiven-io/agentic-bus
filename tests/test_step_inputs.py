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


class TestTheCoordinatorComposesAtDispatch:
    """Composition moved from plan time to dispatch time.

    At plan time no step has run, so nothing produced by an earlier step can
    reach a later one — and a consumer that cannot be parameterised from a
    producer ends up reaching into the producer's memory by name. Composing
    at dispatch, with prior artifacts and this step's memory snapshot in hand,
    is what lets the mapping between two agents' ontologies be computed for
    the interaction instead of hard-coded in the consumer.
    """

    def _runtime(self):
        from agentic_bus.coordinator.runtime import CoordinatorRuntime
        from agentic_bus.core.transport.local import LocalTransport

        return CoordinatorRuntime(transport=LocalTransport())

    def _session(self, steps):
        return type(
            "S",
            (),
            {
                "session_id": "s1",
                "intent": type("I", (), {"intent_text": "envie boas-vindas"})(),
                "composition_plan": {"steps": steps},
            },
        )()

    def test_the_step_is_matched_on_agent_and_capability(self):
        """One agent can hold several accepted capabilities in a session, and
        matching on the agent alone would hand a step the parameters composed
        for a different one."""
        session = self._session(
            [
                {"agent_id": "a", "capability_id": "cap.one"},
                {"agent_id": "a", "capability_id": "cap.two"},
            ]
        )

        step = self._runtime()._plan_step_for(session, "a", "cap.two")

        assert step["capability_id"] == "cap.two"

    def test_an_unknown_step_is_none(self):
        assert self._runtime()._plan_step_for(None, "a", "cap") is None

    async def test_a_step_without_a_schema_composes_nothing_and_calls_no_model(self):
        step = {"agent_id": "a", "capability_id": "c", "input_schema": {}}

        inputs = await self._runtime()._compose_inputs_for_dispatch(
            self._session([step]), step, prior_results={}, memory={}
        )

        assert inputs == {}

    async def test_composed_inputs_are_kept_on_the_plan_step(self, monkeypatch):
        """What each step was told is part of what happened, so it goes to
        the archive with the rest of the plan."""
        import agentic_bus.core.step_inputs as si

        async def fake(**kwargs):
            return si.ComposedInputs(inputs={"descricao": "x"})

        monkeypatch.setattr(si, "compose_step_inputs", fake)
        step = {"agent_id": "a", "capability_id": "c", "input_schema": SCHEMA}

        inputs = await self._runtime()._compose_inputs_for_dispatch(
            self._session([step]), step, prior_results={}, memory={}
        )

        assert inputs == {"descricao": "x"}
        assert step["inputs"] == {"descricao": "x"}

    async def test_a_violation_yields_nothing_rather_than_a_half_filled_request(
        self, monkeypatch
    ):
        import agentic_bus.core.step_inputs as si

        async def fake(**kwargs):
            return si.ComposedInputs(inputs={"limite": 1}, violations=["descricao missing"])

        monkeypatch.setattr(si, "compose_step_inputs", fake)
        step = {"agent_id": "a", "capability_id": "c", "input_schema": SCHEMA}
        runtime = self._runtime()
        events = []

        async def capture(*args, **kwargs):
            events.append((args, kwargs))

        monkeypatch.setattr(runtime, "_emit_event", capture)

        inputs = await runtime._compose_inputs_for_dispatch(
            self._session([step]), step, prior_results={}, memory={}
        )

        assert inputs == {}
        assert "inputs" not in step
        assert events and "Could not compose" in events[0][0][2]

    async def test_prior_results_and_memory_reach_the_composer(self, monkeypatch):
        """The whole point of composing at dispatch."""
        import agentic_bus.core.step_inputs as si

        seen = {}

        async def fake(**kwargs):
            seen.update(kwargs)
            return si.ComposedInputs(inputs={"descricao": "x"})

        monkeypatch.setattr(si, "compose_step_inputs", fake)
        step = {"agent_id": "a", "capability_id": "c", "input_schema": SCHEMA}

        await self._runtime()._compose_inputs_for_dispatch(
            self._session([step]),
            step,
            prior_results={"crm": {"row_count": 4}},
            memory={"crm.clientes": [{"email": "a@x"}]},
        )

        assert seen["prior_results"] == {"crm": {"row_count": 4}}
        assert seen["memory"] == {"crm.clientes": [{"email": "a@x"}]}
        assert seen["intent_text"] == "envie boas-vindas"


class TestReferencesAndShapes:
    """The model sees shapes and answers with references; code resolves them.

    This is what keeps forty thousand rows out of a prompt while still letting
    a later step be parameterised from them — the same split that keeps a
    dataset out of an agent's model context.
    """

    def test_a_shape_carries_structure_and_never_a_value(self):
        from agentic_bus.core.step_inputs import describe_shape

        rows = [{"id": 1, "nome": "Marta", "email": "marta@acme.example"}]

        shape = describe_shape(rows)

        assert shape == "list[1] of {id, nome, email}"
        assert "Marta" not in shape and "acme" not in shape

    def test_a_string_shape_is_only_its_length(self):
        from agentic_bus.core.step_inputs import describe_shape

        assert describe_shape("segredo") == "string[7]"

    def test_a_sparse_first_row_does_not_hide_later_fields(self):
        from agentic_bus.core.step_inputs import describe_shape

        assert describe_shape([{"a": 1}, {"a": 1, "b": 2}]) == "list[2] of {a, b}"

    def test_a_whole_value_reference_resolves(self):
        from agentic_bus.core.step_inputs import resolve_refs

        assert resolve_refs({"$from": "k"}, {"k": [1, 2]}) == [1, 2]

    def test_a_path_reference_resolves(self):
        from agentic_bus.core.step_inputs import resolve_refs

        assert resolve_refs({"$from": "k", "$path": "a.b"}, {"k": {"a": {"b": 7}}}) == 7

    def test_a_fields_reference_projects_and_renames_each_row(self):
        from agentic_bus.core.step_inputs import resolve_refs

        rows = [{"id": 1, "nome": "A", "email": "a@x", "criado_em": "ontem"}]
        out = resolve_refs(
            {"$from": "k", "$fields": {"name": "nome", "email": "email"}}, {"k": rows}
        )

        assert out == [{"name": "A", "email": "a@x"}]

    def test_references_resolve_inside_nested_objects_and_lists(self):
        from agentic_bus.core.step_inputs import resolve_refs

        out = resolve_refs(
            {"outer": [{"$from": "k", "$path": "x"}], "lit": 1}, {"k": {"x": "v"}}
        )

        assert out == {"outer": ["v"], "lit": 1}

    def test_a_reference_to_memory_this_step_cannot_read_raises(self):
        """The model named something the plan never granted this step."""
        from agentic_bus.core.step_inputs import resolve_refs

        import pytest

        with pytest.raises(KeyError):
            resolve_refs({"$from": "rh.salarios"}, {"crm.clientes": []})

    async def test_composition_resolves_references_before_validating(self):
        """What the schema checks is what the agent will receive."""
        model = _Model(
            '{"descricao": {"$from": "sp.modelo", "$path": "titulo"}}'
        )

        composed = await compose_step_inputs(
            intent_text="i",
            step=_step(),
            memory={"sp.modelo": {"titulo": "Bem-vindo"}},
            llm=model,
        )

        assert composed.ok
        assert composed.inputs == {"descricao": "Bem-vindo"}

    async def test_a_reference_outside_this_step_s_memory_is_a_violation(self):
        model = _Model('{"descricao": {"$from": "rh.salarios"}}')

        composed = await compose_step_inputs(
            intent_text="i", step=_step(), memory={"sp.modelo": {}}, llm=model
        )

        assert not composed.ok
        assert "cannot read" in composed.summary()

    async def test_the_prompt_shows_memory_shapes_and_not_values(self):
        model = _Model('{"descricao": "x"}')

        await compose_step_inputs(
            intent_text="i",
            step=_step(),
            memory={"crm.clientes": [{"nome": "Marta", "email": "marta@acme.example"}]},
            llm=model,
        )

        prompt = model.prompts[0]
        assert "crm.clientes: list[1] of {nome, email}" in prompt
        assert "Marta" not in prompt
        assert "acme" not in prompt


class TestTheReport:
    def test_it_says_which_case_it_is(self):
        assert "nothing to compose" in ComposedInputs(unchecked=True).summary()
        assert "0 parameter" in ComposedInputs().summary()
        assert "boom" in ComposedInputs(violations=["boom"]).summary()
