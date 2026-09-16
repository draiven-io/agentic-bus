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


async def _execute(agent, *, scopes: list[str], context=None, prior=None):
    peer = _Peer()
    agent._peer = peer
    envelope = build_envelope(
        MessageType.EXECUTE,
        SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
        "session-1",
        {
            "execution_plan": {
                "context": context or {},
                "prior_results": prior or {},
            },
            "authorized_scopes": scopes,
        },
    )
    await agent._handle_execute(envelope)
    completes = [e for e in peer.sent if e.message_type == MessageType.COMPLETE]
    assert completes, "the agent sent no complete"
    return CompletePayload(**completes[-1].payload)


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
        # The rows travel through memory; the artifact is the summary.
        rows = payload.memory_writes["crm-reader.clientes"]
        assert len(rows) == payload.artifacts[0]["row_count"]
        assert "email" in payload.artifacts[0]["columns"]

    async def test_the_document_carries_its_classification(self):
        """Sensitivity, not destination — and a welcome template is public,
        which is why the invariant refusing restricted material leaving the
        tenant does not fire on this plan."""
        payload = await _execute(SharePointAgent(), scopes=["doc:read"])

        assert payload.artifacts[0]["classificacao"] == "Publico"

    async def test_the_sender_writes_to_every_recipient(self):
        crm = await _execute(CRMAgent(), scopes=["crm:read"])
        doc = await _execute(SharePointAgent(), scopes=["doc:read"])

        payload = await _execute(
            EmailAgent(),
            scopes=["email:send"],
            prior={"step_1": crm.artifacts[0], "step_2": doc.artifacts[0]},
        )

        assert payload.status == "success"
        assert payload.artifacts[0]["enviados"] == crm.artifacts[0]["row_count"]

    async def test_the_sender_stages_nothing(self):
        """It is the egress point, not a producer of working data."""
        payload = await _execute(EmailAgent(), scopes=["email:send"])

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

        agent = factory()
        schema = agent.capabilities()[0].output_schema
        payload = await _execute(agent, scopes=[scope])

        report = validate_artifacts(
            payload.artifacts,
            schema,
            agent_id=agent.agent_id,
            capability_id=agent.capabilities()[0].capability_id,
        )

        assert not report.violations
