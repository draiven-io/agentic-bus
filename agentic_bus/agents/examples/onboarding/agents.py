"""The three agents of the onboarding example.

One credential each. That is the whole shape of the thing, and it is a
deployment decision rather than a protocol one — LIP sees three agents and
does not know the difference.

Two of them need no intelligence at all. The third does: finding the right
template among folders is a real problem, and ``SharePointAgent.choose`` is
where a model belongs if you want one. What holds either way is narrower than
"agents with credentials hold no model", which was too broad — it is that such
an agent must not let *untrusted content* reach whatever does the deciding,
and that one scope bounds what a bad decision can cause.

Why three and not two is the part worth noticing. An agent that could both
read the template and send the mail would hold ``doc:read`` and ``email:send``
in one process, which is the composition this protocol exists to govern,
rebuilt where no coordinator can see it. Splitting them keeps the combination
in the plan, where ``negotiation_acceptance`` can judge it.

Run them with ``python -m agentic_bus.agents.examples.onboarding.run_agents``.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from agentic_bus import ScopedResource, inputs, remember
from agentic_bus.agents.base.agent import BaseAgent
from agentic_bus.core.registry.capability_registry import AgentCapability

# ---------------------------------------------------------------------------
# Stand-ins for the real systems.
#
# Each is what the agent's credential would reach. The example is about who
# may call them and when — but the document library is deliberately more than
# one file, because "find the right template" is where the interesting
# question lives.
# ---------------------------------------------------------------------------

_CUSTOMERS = [
    {"id": 1, "name": "Marta Ribeiro", "email": "marta@acme.example", "created_at": "yesterday"},
    {"id": 2, "name": "Caio Duarte", "email": "caio@globex.example", "created_at": "yesterday"},
    {"id": 3, "name": "Lia Antunes", "email": "lia@initech.example", "created_at": "yesterday"},
    {"id": 4, "name": "Rafael Souza", "email": "rafael@internal.local", "created_at": "yesterday"},
]

#: What a search comes back with. Metadata only — title, path, sensitivity.
#: No body: choosing which document to open must not require reading any of
#: them, or the choice becomes a decision made over untrusted content.
_LIBRARY = [
    {
        "doc_id": "welcome-email",
        "title": "Welcome email — new customers",
        "folder": "/Communications/Templates/Onboarding",
        # Sensitivity, not destination. A welcome template is written to be
        # read by customers, so it is public — which is exactly why the
        # invariant refusing restricted material leaving the tenant does not
        # fire on this plan.
        "classification": "Public",
    },
    {
        "doc_id": "renewal-reminder",
        "title": "Renewal reminder email — expiring subscriptions",
        "folder": "/Communications/Templates/Retention",
        "classification": "Public",
    },
    {
        "doc_id": "refund-policy",
        "title": "Refund and cancellation policy",
        "folder": "/Legal/Policies",
        "classification": "Internal",
    },
    {
        "doc_id": "salary-table",
        "title": "Salary table 2026",
        "folder": "/HR/Confidential",
        "classification": "Confidential",
    },
]

_BODIES = {
    "welcome-email": "Hi {name}, glad to have you here. Your account is live.",
    "renewal-reminder": "Hi {name}, your subscription renews in thirty days.",
}


class _FakeCRM:
    async def find(self, *, signed_up_since: str | None = None) -> list[dict]:
        await asyncio.sleep(0.05)
        return list(_CUSTOMERS)


class _FakeSharePoint:
    async def search(self, query: str) -> list[dict]:
        """Candidates for *query*. Metadata only, never a body."""
        await asyncio.sleep(0.05)
        terms = {t for t in query.lower().split() if len(t) > 3}
        scored = [(len(terms & set(d["title"].lower().split())), d) for d in _LIBRARY]
        return [dict(d) for score, d in sorted(scored, key=lambda s: -s[0]) if score]

    async def get_body(self, doc_id: str) -> str:
        await asyncio.sleep(0.02)
        return _BODIES.get(doc_id, "")


class _FakeMailer:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.sleep(0.01)
        self.sent.append({"to": to, "subject": subject})


# ---------------------------------------------------------------------------
# Artifacts.
#
# `output_model` derives the JSON Schema the coordinator validates a
# `complete` against (RFC 0002). Each agent reports a summary; the working
# data travels through session memory, which is what the next step reads.
# ---------------------------------------------------------------------------


class FindCustomers(BaseModel):
    """What the CRM step needs to be told."""

    signed_up_since: str | None = Field(
        default=None,
        description="Sign-up period, as the intent expressed it — 'yesterday', "
        "'this week', or an ISO date. Absent: yesterday.",
    )
    segment: str | None = Field(
        default=None, description="Customer segment, when the intent names one."
    )


class FindTemplate(BaseModel):
    """What the document step needs to be told."""

    description: str = Field(
        default="welcome email template",
        description="The document wanted, described in natural language — "
        "for example 'welcome email template'.",
    )


class Recipient(BaseModel):
    name: str = Field(description="How to address the person")
    email: str = Field(description="Destination address")


class SendTemplate(BaseModel):
    """What the sender needs to be told.

    Nothing here names the CRM, the document store, or any memory key. The
    sender declares the shape it consumes; the coordinator maps whatever the
    earlier steps produced onto it. That mapping is the liquid interface: it
    is computed for this interaction, from the producers' published output
    shapes and this consumer's published input shape, and it does not outlive
    the session. The producer and the consumer never learn each other's
    names, which is the property the protocol exists for.
    """

    recipients: list[Recipient] = Field(description="Who to send to")
    subject: str = Field(description="Subject line")
    body: str = Field(description="Email body; may contain {name} for personalisation")


class CustomersRef(BaseModel):
    memory_key: str = Field(description="Where the rows were staged")
    row_count: int
    columns: list[str]


class TemplateRef(BaseModel):
    memory_key: str = Field(description="Where the template was staged")
    doc_id: str
    title: str
    classification: str = Field(description="Sensitivity, per the source system")


class SendSummary(BaseModel):
    sent: int
    recipients: list[str] = Field(description="Addresses actually written to")


# ---------------------------------------------------------------------------


class CRMAgent(BaseAgent):
    """Reads the customer base. Holds ``crm:read`` and nothing else."""

    def __init__(self, coordinator_uri: str = "ws://localhost:8765") -> None:
        super().__init__(
            agent_id="crm-reader",
            coordinator_uri=coordinator_uri,
            version="1.0.0",
            semantic_description=(
                "Queries the CRM customer base: by sign-up period, by segment "
                "and by subscription status."
            ),
        )
        # The credential is reachable only through the scope check, and the
        # factory does not run until that check passes — a scope never granted
        # is a connection never opened.
        self.crm = ScopedResource("crm:read", _FakeCRM)

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="crm.find_customers",
                description=(
                    "Finds customers in the CRM by sign-up period. Leaves the "
                    "rows in session memory and returns a summary."
                ),
                required_scopes=["crm:read"],
                supported_data_domains=["crm", "customer"],
                input_model=FindCustomers,
                operational_constraints={"max_rows": 50_000},
                expected_artifacts=["customers_ref"],
                estimated_cost=0.01,
                estimated_latency=1.0,
                output_model=CustomersRef,
            ),
        ]

    async def execute_task(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        crm = self.crm.get()

        # The shape this capability declared, as an instance. BaseAgent
        # already validated the context against it before calling this —
        # there is no blob to go fishing in, and no prose here to parse.
        req = inputs(FindCustomers)
        since = req.signed_up_since or str(date.today() - timedelta(days=1))
        rows = await crm.find(signed_up_since=since)

        key = f"{self.agent_id}.customers"
        remember(key, rows)

        return CustomersRef(
            memory_key=key,
            row_count=len(rows),
            columns=list(rows[0].keys()) if rows else [],
        ).model_dump()


class SharePointAgent(BaseAgent):
    """Reads documents. Holds ``doc:read`` and nothing else."""

    def __init__(self, coordinator_uri: str = "ws://localhost:8765") -> None:
        super().__init__(
            agent_id="sharepoint-reader",
            coordinator_uri=coordinator_uri,
            version="1.0.0",
            semantic_description=(
                "Finds documents in SharePoint: email templates, internal "
                "policies and communication material, with the sensitivity "
                "classification the source system assigned."
            ),
        )
        self.sharepoint = ScopedResource("doc:read", _FakeSharePoint)

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="doc.find_template",
                description=(
                    "Finds a document template from a natural-language "
                    "description and leaves it in session memory, with the "
                    "classification the source system assigned."
                ),
                required_scopes=["doc:read"],
                supported_data_domains=["document", "communication"],
                input_model=FindTemplate,
                expected_artifacts=["template_ref"],
                estimated_cost=0.005,
                estimated_latency=0.5,
                output_model=TemplateRef,
            ),
        ]

    async def execute_task(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        sharepoint = self.sharepoint.get()

        # Two phases, and the split is the point. Search returns metadata —
        # title, folder, sensitivity — and never a body. Choosing which
        # document to open therefore never requires reading any of them.
        wanted = inputs(FindTemplate).description
        candidates = await sharepoint.search(wanted)
        if not candidates:
            return {"error": "no template found", "query": wanted}

        chosen = self.choose(wanted, candidates)

        # Only now is a body read, and it goes into memory rather than back
        # into a decision. Nothing downstream of here asks the agent to judge
        # what the document says.
        body = await sharepoint.get_body(chosen["doc_id"])
        doc = {**chosen, "body": body}

        key = f"{self.agent_id}.template"
        remember(key, doc)

        return TemplateRef(
            memory_key=key,
            doc_id=doc["doc_id"],
            title=doc["title"],
            classification=doc["classification"],
        ).model_dump()

    def choose(self, wanted: str, candidates: list[dict]) -> dict:
        """Pick one candidate. **This is where a model goes, if you need one.**

        Finding the right document among folders is a real problem and a
        keyword score is a poor answer to it. Override this with a model, or
        let a search-capable MCP server do it upstream — both are fine, and
        the claim "an agent with a credential holds no model" was too broad.

        What stays true when you put one here:

        **It reasons over the requester's words and over metadata**, never
        over document contents. An injected sentence inside a payroll
        spreadsheet is not in this method's input, and cannot be — search
        returns no bodies.

        **This agent holds one scope.** If the choice is wrong, or is steered,
        the worst outcome is the wrong document being read. It cannot send,
        cannot write, cannot reach the CRM. The containment is the scope, not
        the absence of a model — and an agent that also held ``email:send``
        would turn a bad choice into an exfiltration.
        """
        terms = {t for t in wanted.lower().split() if len(t) > 3}
        return max(
            candidates,
            key=lambda d: len(terms & set(d["title"].lower().split())),
        )


class EmailAgent(BaseAgent):
    """Sends mail. Holds ``email:send`` and nothing else — the egress point.

    It reads neither the CRM nor SharePoint, and it does not know their
    names. Everything it acts on arrives in the shape *it* declared, composed
    by the coordinator from what earlier steps produced — which is what keeps
    the combination visible to the coordinator instead of hidden inside one
    agent, and what keeps this agent ignorant of the others' ontology.
    """

    def __init__(self, coordinator_uri: str = "ws://localhost:8765") -> None:
        super().__init__(
            agent_id="email-sender",
            coordinator_uri=coordinator_uri,
            version="1.0.0",
            semantic_description=(
                "Sends transactional email from a template and a recipient "
                "list produced by earlier steps."
            ),
        )
        self.mailer = ScopedResource("email:send", _FakeMailer)

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="email.send_template",
                description=(
                    "Sends an email template to a list of recipients, "
                    "personalised per recipient."
                ),
                required_scopes=["email:send"],
                supported_data_domains=["communication"],
                input_model=SendTemplate,
                operational_constraints={"max_recipients": 5_000},
                expected_artifacts=["send_summary"],
                estimated_cost=0.02,
                estimated_latency=2.0,
                output_model=SendSummary,
            ),
        ]

    async def execute_task(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        mailer = self.mailer.get()

        # The shape this agent declared, as an instance. The coordinator
        # composed it at dispatch from what the earlier steps produced —
        # mapping the CRM agent's rows onto `recipients` and the document
        # agent's template onto `subject`/`body` — and BaseAgent validated
        # the result against `SendTemplate` before this ran. This agent knows
        # no other agent's name and no memory key. It invents nothing either:
        # a missing recipient list or template is refused as `invalid_input`
        # before this line, because an egress point that improvises is one
        # nobody can reason about.
        req = inputs(SendTemplate)

        for r in req.recipients:
            await mailer.send(
                to=r.email,
                subject=req.subject,
                body=req.body.format(name=r.name),
            )

        return SendSummary(
            sent=len(mailer.sent),
            recipients=[m["to"] for m in mailer.sent],
        ).model_dump()
