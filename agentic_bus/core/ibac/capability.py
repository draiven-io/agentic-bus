"""Capabilities: what an IBAC approval actually grants.

An approval is not permission to do anything the agent later thinks of. It is
permission for a stated purpose, over named resources, for a bounded time —
and something has to hold the agent to that afterwards, or the approval only
governs whether work *starts*.

That gap is the reason this exists. IBAC previously returned constraints that
were written to the audit log and dropped, and the execute message carried
``authorized_scopes: []``. An intention approved for "analyse sales" and one
approved for "export everything" produced byte-identical authority.

    Semantic authorization → Capability → Deterministic execution

A capability is deliberately dumb: it holds no policy and makes no judgements.
Every check on it is a comparison, so an expired or out-of-scope operation is
refused the same way every time, regardless of how the request was worded.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

#: How long an approval stays good for by default. Short enough that a
#: long-running flow has to be re-authorised rather than drifting past the
#: intention it was granted for, long enough not to interrupt normal work.
DEFAULT_TTL_SECONDS = 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CapabilityViolation(BaseModel):
    """Why an operation was refused."""

    reason: str
    capability_id: str = ""


class Capability(BaseModel):
    """Bounded authority produced by an IBAC approval."""

    capability_id: str = Field(default_factory=lambda: f"cap-{uuid.uuid4().hex[:12]}")
    session_id: str = ""

    #: Who the grant is for. An empty list grants to any participant in the
    #: session, which is the case where the approval was for the intention
    #: rather than for a particular agent.
    principals: list[str] = Field(default_factory=list)

    purpose: str = ""
    resources: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)

    #: Carried through from the IBAC decision. ``external_disclosure: false``
    #: and similar live here.
    constraints: dict[str, Any] = Field(default_factory=dict)

    issued_at: str = Field(default_factory=lambda: _now().isoformat())
    expires_at: str = ""

    @classmethod
    def issue(
        cls,
        *,
        session_id: str,
        principals: list[str] | None = None,
        purpose: str = "",
        scopes: list[str] | None = None,
        resources: list[str] | None = None,
        actions: list[str] | None = None,
        constraints: dict[str, Any] | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> "Capability":
        """Mint a capability that expires."""
        return cls(
            session_id=session_id,
            principals=list(principals or []),
            purpose=purpose,
            scopes=list(scopes or []),
            resources=list(resources or []),
            actions=list(actions or []),
            constraints=dict(constraints or {}),
            expires_at=(_now() + timedelta(seconds=ttl_seconds)).isoformat(),
        )

    # -- checks -------------------------------------------------------------

    def is_expired(self, now: datetime | None = None) -> bool:
        if not self.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at)
        except ValueError:
            # An unparseable expiry is treated as expired: a capability whose
            # lifetime cannot be established has no lifetime.
            return True
        return (now or _now()) >= expiry

    def permits_principal(self, principal: str) -> bool:
        return not self.principals or principal in self.principals

    def permits_scope(self, scope: str) -> bool:
        return not self.scopes or scope in self.scopes

    def check(
        self,
        *,
        principal: str = "",
        scopes: list[str] | None = None,
        now: datetime | None = None,
    ) -> CapabilityViolation | None:
        """Return the first violation, or ``None`` when the operation fits.

        Returning the violation rather than a boolean means the refusal can be
        reported to the requester and written to the audit trail, instead of
        surfacing as an unexplained failure.
        """
        if self.is_expired(now):
            return CapabilityViolation(
                reason=f"capability expired at {self.expires_at}",
                capability_id=self.capability_id,
            )

        if principal and not self.permits_principal(principal):
            return CapabilityViolation(
                reason=(
                    f"{principal!r} is not authorised by this capability "
                    f"(granted to: {', '.join(self.principals)})"
                ),
                capability_id=self.capability_id,
            )

        for scope in scopes or []:
            if not self.permits_scope(scope):
                return CapabilityViolation(
                    reason=(
                        f"scope {scope!r} was not authorised "
                        f"(granted: {', '.join(self.scopes) or 'none'})"
                    ),
                    capability_id=self.capability_id,
                )

        return None

    def forbids_external_disclosure(self) -> bool:
        return self.constraints.get("external_disclosure") is False

    def audit_summary(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "purpose": self.purpose,
            "principals": self.principals,
            "scopes": self.scopes,
            "constraints": self.constraints,
            "expires_at": self.expires_at,
        }
