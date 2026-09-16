"""The onboarding example, exercised without a coordinator.

The example exists to show a shape, so these assert the shape rather than the
happy path. The ones that carry the claim are the agent refusing and building
nothing without its scope, and each agent holding exactly one — because an
agent that could read the template *and* send the mail would rebuild, inside
one process, the composition the whole protocol exists to keep visible.
"""

from __future__ import annotations

import pytest

from agentic_bus.agents.examples.onboarding.agents import (
    CRMAgent,
    EmailAgent,
    SharePointAgent,
)
from agentic_bus.core.protocol.envelope import (
    CompletePayload,
    MessageType,
    SenderInfo,
    SenderKind,
    build_envelope,
)


class _Peer:
    peer_id = "peer-1"

    def __init__(self) -> None:
        self.sent: list = []

    async def send_envelope(self, envelope) -> None:
        self.sent.append(envelope)


async def _execute(agent, *, scopes: list[str], context=None, memory=None):
    peer = _Peer()
    agent._peer = peer
    envelope = build_envelope(
        MessageType.EXECUTE,
        SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
        "session-1",
        {
            "execution_plan": {"context": context or {}},
            "authorized_scopes": scopes,
            "memory_snapshot": memory or {},
        },
    )
    await agent._handle_execute(envelope)
    completes = [e for e in peer.sent if e.message_type == MessageType.COMPLETE]
    assert completes, "the agent sent no complete"
    return CompletePayload(**completes[-1].payload)


def _compose_for_sender(crm, doc) -> dict:
    """What the coordinator composes for the sender at dispatch.

    Built the way the coordinator builds it: the model returns references
    into the producers' memory, and `resolve_refs` substitutes the data.
    Neither the references nor this helper name a field the sender did not
    declare.
    """
    from agentic_bus.core.step_inputs import resolve_refs

    memory = {**crm.memory_writes, **doc.memory_writes}
    crm_key = crm.artifacts[0]["memory_key"]
    doc_key = doc.artifacts[0]["memory_key"]
    return resolve_refs(
        {
            "destinatarios": {"$from": crm_key, "$fields": {"nome": "nome", "email": "email"}},
            "assunto": {"$from": doc_key, "$path": "titulo"},
            "corpo": {"$from": doc_key, "$path": "corpo"},
        },
        memory,
    )


class TestOneCredentialEach:
    """The property the example is built to demonstrate."""

    @pytest.mark.parametrize(
        "factory,scope",
        [(CRMAgent, "crm:read"), (SharePointAgent, "doc:read"), (EmailAgent, "email:send")],
    )
    def test_an_agent_declares_exactly_one_scope(self, factory, scope):
        capabilities = factory().capabilities()

        assert len(capabilities) == 1
        assert capabilities[0].required_scopes == [scope]

    def test_the_sender_can_neither_read_the_crm_nor_the_documents(self):
        """The reason there are three agents and not two.

        An agent holding `doc:read` and `email:send` would be the composition
        this protocol governs, rebuilt where no coordinator can see it.
        """
        declared = EmailAgent().capabilities()[0].required_scopes

        assert "crm:read" not in declared
        assert "doc:read" not in declared

    def test_no_two_agents_share_a_scope(self):
        held = [
            a().capabilities()[0].required_scopes[0]
            for a in (CRMAgent, SharePointAgent, EmailAgent)
        ]

        assert len(set(held)) == 3


class TestRefusal:
    @pytest.mark.parametrize(
        "factory,granted",
        [(CRMAgent, "doc:read"), (SharePointAgent, "email:send"), (EmailAgent, "crm:read")],
    )
    async def test_the_wrong_scope_is_refused(self, factory, granted):
        payload = await _execute(factory(), scopes=[granted])

        assert payload.status == "denied"

    async def test_nothing_is_staged_on_the_refused_path(self):
        payload = await _execute(CRMAgent(), scopes=["doc:read"])

        assert payload.memory_writes == {}

    async def test_the_credential_is_not_built_on_the_refused_path(self):
        """A scope never granted is a connection never opened."""
        agent = CRMAgent()

        await _execute(agent, scopes=["doc:read"])

        assert agent.crm.is_built is False

    async def test_the_refused_scope_is_reported(self):
        payload = await _execute(EmailAgent(), scopes=["crm:read"])

        assert payload.metadata["denied_scopes"] == ["email:send"]


class TestTheSteps:
    async def test_the_crm_stages_the_rows_and_reports_a_summary(self):
        payload = await _execute(CRMAgent(), scopes=["crm:read"])

        assert payload.status == "success"
        # The rows travel through memory; the artifact is the summary, and
        # carries no rows of its own now that the consumer can read them.
        rows = payload.memory_writes["crm-reader.clientes"]
        assert len(rows) == payload.artifacts[0]["row_count"]
        assert "rows" not in payload.artifacts[0]
        assert "email" in payload.artifacts[0]["columns"]

    async def test_the_document_carries_its_classification(self):
        """Sensitivity, not destination — and a welcome template is public,
        which is why the invariant refusing restricted material leaving the
        tenant does not fire on this plan."""
        payload = await _execute(SharePointAgent(), scopes=["doc:read"])

        assert payload.artifacts[0]["classificacao"] == "Publico"

    async def test_the_search_finds_the_template_among_others(self):
        """The library holds a refund policy and a salary table too. Finding
        the right one is the part a keyword score answers badly and a model
        answers well — which is why `choose` exists as a seam."""
        payload = await _execute(
            SharePointAgent(),
            scopes=["doc:read"],
            context={"modelo": {"descricao": "modelo de e-mail de boas-vindas"}},
        )

        assert payload.artifacts[0]["doc_id"] == "welcome-pt-br"

    async def test_the_sender_refuses_rather_than_guessing(self):
        """An egress point that improvises is one nobody can reason about."""
        payload = await _execute(EmailAgent(), scopes=["email:send"])

        assert payload.artifacts[0]["error"]
        assert payload.artifacts[0]["destinatarios_recebidos"] == 0

    async def test_the_sender_writes_to_every_recipient(self):
        crm = await _execute(CRMAgent(), scopes=["crm:read"])
        doc = await _execute(SharePointAgent(), scopes=["doc:read"])

        # Exactly what the coordinator composes at dispatch: the sender's own
        # declared shape, filled from what the earlier steps produced. The
        # sender never sees a memory key or another agent's name.
        payload = await _execute(
            EmailAgent(),
            scopes=["email:send"],
            context=_compose_for_sender(crm, doc),
        )

        assert payload.status == "success"
        assert payload.artifacts[0]["enviados"] == crm.artifacts[0]["row_count"]

    async def test_the_sender_stages_nothing(self):
        """It is the egress point, not a producer of working data."""
        crm = await _execute(CRMAgent(), scopes=["crm:read"])
        doc = await _execute(SharePointAgent(), scopes=["doc:read"])

        # Exactly what the coordinator composes at dispatch: the sender's own
        # declared shape, filled from what the earlier steps produced. The
        # sender never sees a memory key or another agent's name.
        payload = await _execute(
            EmailAgent(),
            scopes=["email:send"],
            context=_compose_for_sender(crm, doc),
        )

        assert payload.memory_writes == {}


class TestTheArtifactsMatchWhatWasPromised:
    """RFC 0002: an offer's `output_schema` is derived from `output_model`,
    and a `complete` is validated against it."""

    @pytest.mark.parametrize(
        "factory,scope",
        [(CRMAgent, "crm:read"), (SharePointAgent, "doc:read"), (EmailAgent, "email:send")],
    )
    async def test_the_artifact_validates_against_the_declared_schema(
        self, factory, scope
    ):
        from agentic_bus.core.artifacts import validate_artifacts

        context = {}
        if factory is EmailAgent:
            crm = await _execute(CRMAgent(), scopes=["crm:read"])
            doc = await _execute(SharePointAgent(), scopes=["doc:read"])
            context = _compose_for_sender(crm, doc)

        agent = factory()
        schema = agent.capabilities()[0].output_schema
        payload = await _execute(agent, scopes=[scope], context=context)

        report = validate_artifacts(
            payload.artifacts,
            schema,
            agent_id=agent.agent_id,
            capability_id=agent.capabilities()[0].capability_id,
        )

        assert not report.violations


class TestTheChoiceIsMadeOverMetadata:
    """The claim that replaced "agents with credentials hold no model".

    A model here would be fine. What must not happen is document *content*
    reaching whatever decides — and it cannot, because search returns none.
    """

    async def test_search_returns_no_bodies(self):
        from agentic_bus.agents.examples.onboarding.agents import _FakeSharePoint

        candidatos = await _FakeSharePoint().search("e-mail de boas-vindas")

        assert candidatos
        for candidate in candidatos:
            assert "corpo" not in candidate

    def test_choose_sees_only_titles_and_labels(self):
        """So an injected sentence inside a payroll file is not in its input."""
        agent = SharePointAgent()
        candidatos = [
            {"doc_id": "a", "titulo": "Modelo de boas-vindas", "classificacao": "Publico"},
            {"doc_id": "b", "titulo": "Tabela salarial 2026", "classificacao": "Confidencial"},
        ]

        assert agent.choose("modelo de boas-vindas", candidatos)["doc_id"] == "a"

    def test_a_bad_choice_is_bounded_by_the_scope(self):
        """Even steered onto the salary table, this agent can only read it.

        It holds `doc:read` and nothing else: it cannot send, cannot write,
        cannot reach the CRM. The containment is the scope, not the absence
        of a model — an agent that also held `email:send` would turn a bad
        choice into an exfiltration.
        """
        declared = SharePointAgent().capabilities()[0].required_scopes

        assert declared == ["doc:read"]


class TestTheSenderKnowsNoOtherAgent:
    """The reason deferred composition exists.

    Before, the sender did `recall("crm-reader.clientes")` — the producer's
    id, the producer's key, the producer's row layout. Three pieces of another
    agent's ontology, hard-coded in the consumer. That is the coupling the
    protocol claims to dissolve, rebuilt one layer down.
    """

    def test_the_sender_declares_its_own_input_shape(self):
        schema = EmailAgent().capabilities()[0].input_schema

        assert set(schema["required"]) == {"destinatarios", "assunto", "corpo"}

    def test_its_declared_shape_names_no_producer(self):
        import json

        text = json.dumps(EmailAgent().capabilities()[0].input_schema)

        assert "crm-reader" not in text
        assert "sharepoint-reader" not in text
        assert "memory_key" not in text

    def test_its_source_names_no_producer(self):
        import inspect

        source = inspect.getsource(EmailAgent)

        assert "crm-reader" not in source
        assert "sharepoint-reader" not in source
        assert "recall(" not in source
