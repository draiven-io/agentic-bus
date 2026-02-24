"""Agentic Bus Session – the ephemeral coordination context.

A session represents a single Agentic Bus lifecycle:
  intent → discovery → negotiation → execution → completion → dissolution

Per Agentic Bus Invariant II (§5.1.2), all negotiated schemas, authorization scopes, and
execution bindings are invalidated upon dissolution.  No session artifacts may
persist beyond ``dissolve``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.protocol.envelope import (
    IntentPayload,
    AgBusEnvelope,
    OfferPayload,
)


class SessionPhase(StrEnum):
    """Current phase of the session lifecycle."""

    CREATED = "created"
    INTENT_RECEIVED = "intent_received"
    DISCOVERY = "discovery"
    NEGOTIATION = "negotiation"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTION = "execution"
    COMPLETED = "completed"
    DISSOLVED = "dissolved"


class NegotiationRecord(BaseModel):
    """Snapshot of a single offer within the negotiation."""

    agent_id: str
    offer: OfferPayload
    status: str = "pending"  # pending | accepted | rejected
    rejection_reason: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class SessionState(BaseModel):
    """Full ephemeral state of an Agentic Bus session.

    This object exists only for the lifetime of the interaction window
    ``[t_start, t_ack]``.  After dissolution it MUST be garbage-collected.
    """

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    phase: SessionPhase = SessionPhase.CREATED
    requester_id: str = ""
    requester_oidc_subject: str = ""

    # Intent
    intent: IntentPayload | None = None

    # Discovery
    discovered_agents: list[str] = Field(default_factory=list)
    solicited_agents: list[str] = Field(default_factory=list)

    # Negotiation
    offers: list[NegotiationRecord] = Field(default_factory=list)
    accepted_offers: list[str] = Field(default_factory=list)
    composition_plan: dict[str, Any] = Field(default_factory=dict)

    # Execution
    execution_graph_id: str | None = None
    execution_results: list[dict[str, Any]] = Field(default_factory=list)

    # IBAC
    ibac_decisions: list[dict[str, Any]] = Field(default_factory=list)

    # Validation – agent-based answer validation (§ assigned agent validation)
    assigned_agent_id: str = Field(
        default="",
        description="Agent assigned to validate the final output.",
    )
    validation_rounds: int = Field(
        default=0,
        description="Number of validation-triggered renegotiation rounds completed.",
    )
    max_validation_rounds: int = Field(
        default=3,
        description="Maximum validation renegotiation rounds before final rejection.",
    )
    validation_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "History of validation attempts.  Each entry records the round, "
            "the validator agent, the decision, and the rejection reason."
        ),
    )

    # Timestamps
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    dissolved_at: str | None = None

    # Audit trail – every Agentic Bus envelope exchanged in the session
    audit_log: list[AgBusEnvelope] = Field(default_factory=list)


class SessionManager:
    """In-memory session store with strict dissolution semantics.

    After ``dissolve()`` the session object is removed from memory to uphold
    Agentic Bus Invariant II – Mandatory Temporal Dissolution (§5.1.2).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def create(self, requester_id: str, oidc_subject: str = "") -> SessionState:
        session = SessionState(
            requester_id=requester_id,
            requester_oidc_subject=oidc_subject,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def transition(self, session_id: str, phase: SessionPhase) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        session.phase = phase

    def dissolve(self, session_id: str) -> SessionState | None:
        """Dissolve a session – permanently remove all coordination artifacts.

        Returns the final snapshot for audit logging before destruction.
        """
        session = self._sessions.pop(session_id, None)
        if session is not None:
            session.phase = SessionPhase.DISSOLVED
            session.dissolved_at = datetime.now(timezone.utc).isoformat()
        return session

    def active_sessions(self) -> list[SessionState]:
        return [
            s for s in self._sessions.values()
            if s.phase != SessionPhase.DISSOLVED
        ]

    @property
    def count(self) -> int:
        return len(self._sessions)
