"""In-memory audit log for system-wide events.

Captures administrative and operational actions across the entire Agentic Bus
for the admin dashboard.  This is *not* the per-session audit trail stored in
``SessionState.audit_log`` — it's a coordinator-wide log of high-level events.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import datetime, timezone

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuditEntry(BaseModel):
    """A single entry in the coordinator-wide audit log."""

    id: str = Field(default_factory=lambda: f"log-{uuid.uuid4().hex[:8]}")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    action: str
    actor: str
    target: str
    target_type: str  # "agent" | "session" | "llm_config" | "system"
    details: str = ""
    severity: str = "info"  # "info" | "warning" | "error" | "critical"


class AuditLog:
    """In-memory, bounded audit log for the coordinator admin UI."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)

    def log(
        self,
        action: str,
        actor: str,
        target: str,
        target_type: str,
        details: str = "",
        severity: str = "info",
    ) -> AuditEntry:
        """Append a new audit entry and return it."""
        entry = AuditEntry(
            action=action,
            actor=actor,
            target=target,
            target_type=target_type,
            details=details,
            severity=severity,
        )
        self._entries.appendleft(entry)  # newest first
        logger.debug("Audit: %s %s -> %s (%s)", action, actor, target, severity)
        return entry

    def list_all(self) -> list[AuditEntry]:
        """Return all entries, newest first."""
        return list(self._entries)

    @property
    def count(self) -> int:
        return len(self._entries)
