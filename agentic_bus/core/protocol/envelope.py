"""Agentic Bus protocol envelope and message types.

All protocol messages are structured JSON documents categorised by ``message_type``.
Message types are performative acts that collectively define the lifecycle of a
Liquid Interface (§4.1.1 of the Liquid Interfaces paper, lip.md).

Core message types
------------------
- **register**   – an agent declares itself and its capabilities to the coordinator.
- **registered** – the coordinator accepts or refuses that declaration.
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
# Protocol version
# ---------------------------------------------------------------------------

#: Version of the Liquid Interfaces Protocol this envelope implements.
#:
#: Carried on every message so a peer can reject or adapt to an envelope it
#: does not understand.  Semantic versioning applies to the *wire format*:
#: the patch component changes for editorial fixes, the minor component for
#: backwards-compatible additions (a new optional field, a new message type a
#: peer may ignore), and the major component for anything that would break an
#: existing implementation.
LIP_PROTOCOL_VERSION = "0.3.0"

#: Version assumed for an envelope that arrives with no ``protocol_version``.
#:
#: Pinned to the last version that predates the field. It must NOT track
#: ``LIP_PROTOCOL_VERSION``: if it did, a message from an old peer would be
#: read as whatever version this build happens to be, which is precisely the
#: misreading the field exists to prevent.
LIP_LEGACY_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class MessageType(StrEnum):
    """Performative message types defined by the Liquid Interfaces Protocol.

    See §4.1.1 of the paper (``lip.md``) for their normative semantics.
    """

    REGISTER = "register"
    REGISTERED = "registered"
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
    """Common message envelope for every Liquid Interfaces Protocol message.

    Every message that flows over the transport layer MUST be wrapped in this
    envelope.  The ``payload`` dict carries type-specific content defined by
    the individual message schemas below.
    """

    protocol_version: str = Field(
        default=LIP_PROTOCOL_VERSION,
        description=(
            "Version of the Liquid Interfaces Protocol this message conforms "
            "to.  Absent on messages from pre-versioning peers, which are "
            "treated as 0.1.0."
        ),
    )
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    message_type: MessageType
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sender: SenderInfo
    trace: TraceContext = Field(default_factory=TraceContext)
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "AgBusEnvelope":
        """Parse an envelope received from a peer.

        Use this rather than ``model_validate`` for anything arriving over
        the transport. The field's default applies to envelopes *we*
        construct, and so is the current version; an envelope that arrives
        without the field came from a peer that predates it and must be read
        as :data:`LIP_LEGACY_VERSION` instead.
        """
        if "protocol_version" not in data:
            data = {**data, "protocol_version": LIP_LEGACY_VERSION}
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Typed payloads
# ---------------------------------------------------------------------------

class RegisterPayload(BaseModel):
    """Payload for ``message_type='register'``.

    An agent's declaration of itself: who it is, and what it can be asked to
    do. Sent once per connection — the coordinator's capability registry is
    held against the live socket, so a reconnecting agent must register
    again or it is connected but undiscoverable.
    """

    agent_id: str
    version: str = "0.1.0"
    mode: str = Field(
        default="ephemeral",
        description=(
            "'ephemeral' keeps the registration in memory only, discarded "
            "when the connection ends; 'persistent' also records the agent "
            "in the coordinator's database."
        ),
    )
    capabilities: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Capability descriptors this agent is offering.",
    )
    semantic_description: str = ""
    required_scopes: list[str] = Field(
        default_factory=list,
        description=(
            "Scopes this agent believes it needs. A **request**, never a "
            "grant: under RFC 0003 the vocabulary belongs to the deployment "
            "and a scope is granted by a binding an administrator authored. "
            "An agent SHOULD describe its capabilities and leave this empty; "
            "the coordinator answers with what was actually granted."
        ),
    )
    supported_data_domains: list[str] = Field(default_factory=list)
    operational_constraints: dict[str, Any] = Field(default_factory=dict)


class RegisteredPayload(BaseModel):
    """Payload for ``message_type='registered'``.

    The coordinator's answer to ``register``. Registration can legitimately
    be refused — an agent may not be approved, or may declare a capability
    it is not permitted to offer — and without this answer the agent has no
    way to tell refusal from success, so it would keep serving nothing while
    believing it was live.
    """

    accepted: bool
    agent_id: str = ""
    reason: str = Field(
        default="",
        description="Why registration was refused. Empty when accepted.",
    )
    registered_capabilities: list[str] = Field(
        default_factory=list,
        description="Capability IDs the coordinator actually accepted.",
    )
    granted_scopes: list[str] = Field(
        default_factory=list,
        description=(
            "Scopes this agent was actually granted, which is not what it "
            "asked for. A scope is granted by a binding an administrator "
            "authored (RFC 0003), never by an agent having declared it, so "
            "an agent MUST NOT assume its request was honoured."
        ),
    )
    unrecognised_scopes: list[str] = Field(
        default_factory=list,
        description=(
            "Declared scopes this coordinator's catalogue does not contain. "
            "Recorded as a request for an administrator rather than granted."
        ),
    )
    catalogue: list[str] = Field(
        default_factory=list,
        description=(
            "Scope names this coordinator recognises, returned when a "
            "declaration named something outside it. The refusal is how the "
            "vocabulary propagates: an implementer learns the right name by "
            "being corrected, instead of from documentation that goes stale."
        ),
    )
    coordinator_protocol_version: str = Field(
        default="",
        description=(
            "The LIP version the coordinator implements, so an agent can "
            "detect a mismatch rather than inferring it from failures."
        ),
    )


class IntentPayload(BaseModel):
    """Payload for ``message_type='intent'``."""

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
    """Payload for ``message_type='offer'``.

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
    """Payload for ``message_type='execute'``.

    The coordinator authorising one step, and telling the agent what that
    step was authorised for.
    """

    execution_plan: dict[str, Any] = Field(default_factory=dict)
    authorized_scopes: list[str] = Field(
        default_factory=list,
        description=(
            "What this step may do, after every narrowing: the requester's "
            "own authority, what the interaction claimed, and what this "
            "agent's capability was bound to. An agent MUST NOT assume it "
            "holds anything not listed here."
        ),
    )
    capability_id: str = Field(
        default="",
        description=(
            "Which of the agent's capabilities is being executed. Echoed back "
            "on the completion so the coordinator can check the artifact "
            "against the offer that promised its shape — one agent can hold "
            "several accepted capabilities in a session."
        ),
    )
    memory_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Session memory this agent is permitted to read.",
    )


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
    step_index: int | None = Field(
        default=None,
        description="Index of the execution plan step (0-based). Used to distinguish multiple invocations of the same agent.",
    )
    progress: float | None = Field(
        default=None,
        description="Optional progress indicator between 0.0 and 1.0",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PAYLOAD_TYPES: dict[MessageType, type[BaseModel]] = {
    MessageType.REGISTER: RegisterPayload,
    MessageType.REGISTERED: RegisteredPayload,
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
