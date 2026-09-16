"""Typed access to what an execution was told, and validation at the boundary.

The context reached ``execute_task`` as a plain dict even when the capability
had published an ``input_model`` — the declared type used by the coordinator
and dropped at the agent. The tests that carry the claim are the boundary
ones: a context that does not match the executing capability's model is
refused with ``invalid_input`` *before* ``execute_task`` runs, whether or not
the author ever calls ``inputs()``. That is the only check on the path where
composition failed and the requester's raw context fell through.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from agentic_bus.agents.inputs import (
    InvalidInput,
    inputs,
    reset_context,
    set_context,
)
from agentic_bus.core.protocol.envelope import (
    CompletePayload,
    MessageType,
    SenderInfo,
    SenderKind,
    build_envelope,
)
from agentic_bus.core.registry.capability_registry import AgentCapability


class Envio(BaseModel):
    destinatarios: list[str]
    assunto: str
    corpo: str = Field(default="")


class Opcional(BaseModel):
    filtro: str | None = None


class TestTheAccessor:
    def test_it_builds_the_declared_model_from_the_context(self):
        token = set_context({"destinatarios": ["a@x"], "assunto": "Oi"})
        try:
            req = inputs(Envio)
        finally:
            reset_context(token)

        assert req.destinatarios == ["a@x"]
        assert req.corpo == ""

    def test_extra_fields_are_ignored(self):
        """The context still carries whatever the requester put in it; the
        model picks its own fields out of it."""
        token = set_context({"destinatarios": [], "assunto": "x", "purpose": "onboarding"})
        try:
            assert inputs(Envio).assunto == "x"
        finally:
            reset_context(token)

    def test_an_explicit_context_wins_over_the_installed_one(self):
        token = set_context({"destinatarios": [], "assunto": "installed"})
        try:
            assert inputs(Envio, {"destinatarios": [], "assunto": "explicit"}).assunto == "explicit"
        finally:
            reset_context(token)

    def test_a_missing_required_field_raises_invalid_input(self):
        token = set_context({"assunto": "x"})
        try:
            with pytest.raises(InvalidInput) as info:
                inputs(Envio)
        finally:
            reset_context(token)

        assert info.value.model == "Envio"
        assert any(e["field"] == "destinatarios" for e in info.value.errors)

    def test_invalid_input_is_a_value_error(self):
        with pytest.raises(ValueError):
            inputs(Envio, {})

    def test_outside_an_execution_an_all_default_model_builds(self):
        assert inputs(Opcional).filtro is None

    def test_outside_an_execution_a_required_field_is_truthfully_missing(self):
        with pytest.raises(InvalidInput):
            inputs(Envio)


# ---------------------------------------------------------------------------
# Through BaseAgent
# ---------------------------------------------------------------------------


class _Peer:
    peer_id = "p1"

    def __init__(self) -> None:
        self.sent: list = []

    async def send_envelope(self, envelope) -> None:
        self.sent.append(envelope)


def _agent(*, input_model, work, capability_id="cap.one", extra_capabilities=()):
    from agentic_bus.agents.base.agent import BaseAgent

    class Agent(BaseAgent):
        def capabilities(self):
            caps = [AgentCapability(capability_id=capability_id, input_model=input_model)]
            caps += [AgentCapability(capability_id=c) for c in extra_capabilities]
            return caps

        async def execute_task(self, payload, context):
            return await work(context)

    agent = Agent(agent_id="typed")
    agent._peer = _Peer()
    return agent


async def _execute(agent, context, *, agent_capability_id="cap.one"):
    envelope = build_envelope(
        MessageType.EXECUTE,
        SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
        "s1",
        {
            "execution_plan": {"context": context},
            "authorized_scopes": [],
            # The IBAC capability, as the coordinator has always sent it.
            "capability_id": "cap-ibac-1234",
            # The agent's own capability, so it can find its input_model.
            "agent_capability_id": agent_capability_id,
        },
    )
    await agent._handle_execute(envelope)
    completes = [e for e in agent._peer.sent if e.message_type == MessageType.COMPLETE]
    assert completes
    return CompletePayload(**completes[-1].payload)


class TestValidationAtTheBoundary:
    async def test_a_matching_context_runs_and_inputs_hands_it_over(self):
        seen = {}

        async def work(context):
            seen["req"] = inputs(Envio)
            return {"ok": True}

        payload = await _execute(
            _agent(input_model=Envio, work=work),
            {"destinatarios": ["a@x"], "assunto": "Oi"},
        )

        assert payload.status == "success"
        assert seen["req"].destinatarios == ["a@x"]

    async def test_a_mismatching_context_is_refused_before_execute_task_runs(self):
        """Whether or not the author ever calls inputs()."""
        ran = []

        async def work(context):
            ran.append(1)
            return {"ok": True}

        payload = await _execute(
            _agent(input_model=Envio, work=work), {"assunto": "sem destinatários"}
        )

        assert payload.status == "invalid_input"
        assert ran == []
        assert payload.artifacts[0]["model"] == "Envio"
        assert any(e["field"] == "destinatarios" for e in payload.artifacts[0]["errors"])

    async def test_invalid_input_raised_inside_execute_task_is_the_same_refusal(self):
        class Other(BaseModel):
            precisa: int

        async def work(context):
            inputs(Other)  # a stricter shape than the capability published
            return {"ok": True}

        payload = await _execute(
            _agent(input_model=Envio, work=work),
            {"destinatarios": [], "assunto": "x"},
        )

        assert payload.status == "invalid_input"
        assert payload.artifacts[0]["model"] == "Other"

    async def test_an_agent_that_publishes_no_input_model_is_untouched(self):
        async def work(context):
            return {"got": context}

        payload = await _execute(
            _agent(input_model=None, work=work), {"anything": 1}
        )

        assert payload.status == "success"
        assert payload.artifacts[0]["got"] == {"anything": 1}

    async def test_the_capability_is_found_by_the_agent_capability_id(self):
        """One agent can publish several capabilities with different shapes;
        the wire carries the IBAC capability id, so the agent's own id must
        travel too, or there is nothing to look the model up by."""
        ran = []

        async def work(context):
            ran.append(1)
            return {}

        agent = _agent(
            input_model=Envio, work=work, capability_id="cap.strict",
            extra_capabilities=("cap.loose",),
        )

        loose = await _execute(agent, {"unrelated": 1}, agent_capability_id="cap.loose")
        strict = await _execute(agent, {"unrelated": 1}, agent_capability_id="cap.strict")

        assert loose.status == "success"
        assert strict.status == "invalid_input"

    async def test_a_single_capability_is_used_when_the_wire_names_none(self):
        """An older coordinator sends no agent_capability_id. With exactly one
        capability published there is no ambiguity, so it is still checked."""
        async def work(context):
            return {}

        agent = _agent(input_model=Envio, work=work)
        envelope = build_envelope(
            MessageType.EXECUTE,
            SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            "s1",
            {"execution_plan": {"context": {}}, "authorized_scopes": []},
        )
        await agent._handle_execute(envelope)
        payload = CompletePayload(**agent._peer.sent[-1].payload)

        assert payload.status == "invalid_input"

    async def test_the_context_is_cleared_between_executions(self):
        seen = []

        async def work(context):
            seen.append(inputs(Opcional).filtro)
            return {}

        agent = _agent(input_model=Opcional, work=work)
        await _execute(agent, {"filtro": "primeiro"})
        await _execute(agent, {})

        assert seen == ["primeiro", None]


class TestThePayloadDeclaresTheField:
    def test_execute_carries_the_agent_capability_id(self):
        from agentic_bus.core.protocol.envelope import ExecutePayload

        assert "agent_capability_id" in ExecutePayload.model_fields
