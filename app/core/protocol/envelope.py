"""Agentic Bus protocol envelope and message types.

All protocol messages are structured JSON documents categorised by ``message_type``.
Message types are performative acts that collectively define the lifecycle of a
Agentic Bus (§4.1.1 of the Agentic Bus paper).

Core message types
------------------
- **intent**   – articulates a high-level objective; instantiates a new interaction context.
- **offer**    – declares capability relevant to the expressed intention.
- **accept**   – signals negotiated agreement.
- **reject**   – signals refusal with structured reason.
- **execute**  – authorises coordinated execution under negotiated terms.
- **complete** – signals termination of execution.
- **dissolve** – invalidates the interaction context; triggers mandatory cleanup.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class MessageType(StrEnum):
    """Performative message types defined by Agentic Bus §4.1.1."""

    INTENT = "intent"
    OFFER = "offer"
    ACCEPT = "accept"
    REJECT = "reject"
    EXECUTE = "execute"
    COMPLETE = "complete"
    DISSOLVE = "dissolve"
    EVENT = "event"


class SenderKind(StrEnum):
    """Runtime role of the message sender."""

    REQUESTER = "requester"
    COORDINATOR = "coordinator"
    AGENT = "agent"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class SenderInfo(BaseModel):
    """Identity of the message sender."""

    kind: SenderKind
    id: str
    oidc_subject: str = ""


class TraceContext(BaseModel):
    """Distributed-trace propagation context (W3C Trace-Context compatible)."""

    trace_id: str = ""
    span_id: str = ""


# ---------------------------------------------------------------------------
# Common envelope
# ---------------------------------------------------------------------------

class AgBusEnvelope(BaseModel):
    """Common message envelope for every Agentic Bus message (§8 of AGENTS.md).

    Every message that flows over the transport layer MUST be wrapped in this
    envelope.  The ``payload`` dict carries type-specific content defined by
    the individual message schemas below.
    """

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    message_type: MessageType
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sender: SenderInfo
    trace: TraceContext = Field(default_factory=TraceContext)
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Typed payloads
# ---------------------------------------------------------------------------

class IntentPayload(BaseModel):
    """Payload for ``message_type='intent'`` (§9 of AGENTS.md)."""

    intent_text: str
    context: dict[str, Any] = Field(default_factory=dict)
    requested_outputs: list[str] = Field(default_factory=list)
    ibac_claims_requested: list[str] = Field(default_factory=list)
    assigned_agent_id: str = Field(
        default="",
        description=(
            "Optional agent ID assigned as the validator for this intent. "
            "When set, the assigned agent must validate the execution output "
            "before the session completes.  If validation fails, a "
            "renegotiation loop is triggered with the rejection reason."
        ),
    )


class OfferPayload(BaseModel):
    """Payload for ``message_type='offer'`` (§10 of AGENTS.md).

    When sent by an individual agent, this describes a single capability.
    When sent by the coordinator to the requester, it describes the full
    composed execution plan (multiple agents) for the requester to approve,
    reject, or renegotiate before execution begins.
    """

    capability_id: str
    capability_description: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict)
    expected_artifacts: list[str] = Field(default_factory=list)
    estimated_cost: float | None = None
    estimated_latency: float | None = None
    required_scopes: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "JSON Schema (from ``Model.model_json_schema()``) describing the "
            "structured output the agent will produce.  Propagated to the "
            "requester via the accept message so it can deserialise results."
        ),
    )
    # Coordinator-to-requester fields: the full execution flow
    composition_plan: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "When sent by the coordinator, carries the full composed "
            "execution plan (steps, agents, topology) for the requester "
            "to review before approving or rejecting."
        ),
    )
    participating_agents: list[str] = Field(
        default_factory=list,
        description="List of agent IDs participating in the proposed flow.",
    )


class AcceptPayload(BaseModel):
    """Payload for ``message_type='accept'``.

    When sent by the coordinator: confirms negotiation is complete.
    When sent by the requester: approves the proposed execution plan.
    """

    accepted_offers: list[str] = Field(default_factory=list)
    composition_plan: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Merged JSON Schema describing the combined output that the "
            "requester will receive upon completion.  Built from the "
            "individual output schemas of all accepted offers."
        ),
    )
    # When sent by requester, may include feedback on the plan
    approval_note: str = Field(
        default="",
        description="Optional note from the requester explaining the approval.",
    )


class RejectPayload(BaseModel):
    """Payload for ``message_type='reject'``.

    When sent by the coordinator: intent or negotiation failed.
    When sent by the requester: rejects the proposed plan.  If
    ``renegotiation_hint`` is provided, the coordinator SHOULD attempt
    a new discovery/negotiation cycle incorporating the feedback.
    """

    rejected_offers: list[str] = Field(default_factory=list)
    reason: str = ""
    renegotiation_hint: dict[str, Any] = Field(default_factory=dict)
    renegotiate: bool = Field(
        default=False,
        description=(
            "When True, the requester is requesting renegotiation rather "
            "than outright termination.  The coordinator should attempt a "
            "new negotiation round incorporating renegotiation_hint."
        ),
    )


class ExecutePayload(BaseModel):
    """Payload for ``message_type='execute'``."""

    execution_plan: dict[str, Any] = Field(default_factory=dict)
    authorized_scopes: list[str] = Field(default_factory=list)


class CompletePayload(BaseModel):
    """Payload for ``message_type='complete'``."""

    status: str = "success"
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DissolvePayload(BaseModel):
    """Payload for ``message_type='dissolve'``."""

    reason: str = "session_complete"


class EventPayload(BaseModel):
    """Payload for ``message_type='event'`` — progress / status notifications.

    Events are informational messages emitted by the coordinator or agents to
    provide real-time visibility into the session lifecycle.  They carry no
    performative semantics and do not alter session state.

    Categories:
    - ``phase``       – coordinator phase transitions (e.g. discovery, negotiation)
    - ``agent``       – agent-emitted progress updates during execution
    - ``ibac``        – IBAC evaluation results
    - ``discovery``   – agent discovery events
    - ``negotiation`` – offer evaluation / convergence signals
    - ``execution``   – graph build / node execution progress
    - ``info``        – general informational messages
    - ``warning``     – non-fatal issues
    - ``error``       – error details (non-terminal)
    """

    category: str = "info"
    phase: str = ""
    summary: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    agent_id: str = ""
    progress: float | None = Field(
        default=None,
        description="Optional progress indicator between 0.0 and 1.0",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PAYLOAD_TYPES: dict[MessageType, type[BaseModel]] = {
    MessageType.INTENT: IntentPayload,
    MessageType.OFFER: OfferPayload,
    MessageType.ACCEPT: AcceptPayload,
    MessageType.REJECT: RejectPayload,
    MessageType.EXECUTE: ExecutePayload,
    MessageType.COMPLETE: CompletePayload,
    MessageType.DISSOLVE: DissolvePayload,
    MessageType.EVENT: EventPayload,
}


def build_envelope(
    message_type: MessageType,
    sender: SenderInfo,
    session_id: str,
    payload: BaseModel | dict[str, Any],
    trace: TraceContext | None = None,
) -> AgBusEnvelope:
    """Convenience factory that builds a fully populated ``AgBusEnvelope``."""

    if isinstance(payload, BaseModel):
        payload_dict = payload.model_dump()
    else:
        payload_dict = payload

    return AgBusEnvelope(
        session_id=session_id,
        message_type=message_type,
        sender=sender,
        trace=trace or TraceContext(),
        payload=payload_dict,
    )
