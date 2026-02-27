"""Session-scoped shared memory for inter-agent communication.

The SessionMemory provides a namespaced key-value store that lives on the
coordinator and is shared across all agents participating in a session.

Design principles:
  - Coordinator-owned: single source of truth lives on the coordinator.
  - Namespaced: keys follow ``<namespace>.<key>`` convention.
    * ``shared.*``       — readable/writable by any authorised agent.
    * ``<agent_id>.*``   — private to that agent (+ coordinator).
  - Access-controlled: read/write policies per agent, derived from the
    composition plan.
  - Audited: every read/write is logged with agent_id and timestamp.
  - Ephemeral: destroyed at session dissolution (Invariant II).

v1 uses an in-memory dict.  The interface is designed so v2 can swap in
a Redis/Valkey backend (with reference-based envelope delivery) without
changing agent or coordinator logic.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Data models
# -----------------------------------------------------------------------


class MemoryEntry(BaseModel):
    """A single entry in the session memory."""

    key: str
    value: Any
    written_by: str  # agent_id or "coordinator"
    written_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    version: int = 1


class MemoryAccessPolicy(BaseModel):
    """Read/write permissions for a specific agent within a session."""

    agent_id: str
    read_patterns: list[str] = Field(default_factory=list)
    write_patterns: list[str] = Field(default_factory=list)


class MemoryAuditEntry(BaseModel):
    """Audit trail entry for a memory operation."""

    operation: str  # "read" | "write" | "delete"
    key: str
    agent_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    allowed: bool = True
    reason: str = ""


class MemoryWriteRequest(BaseModel):
    """A write request from an agent, included in the COMPLETE payload."""

    key: str
    value: Any


# -----------------------------------------------------------------------
# Abstract backend
# -----------------------------------------------------------------------


class SessionMemoryBackend(ABC):
    """Abstract backend for session memory storage.

    v1: InMemoryBackend (dict)
    v2: RedisBackend (redis/valkey with TTL = session lifetime)
    """

    @abstractmethod
    def get(self, key: str) -> MemoryEntry | None:
        """Retrieve a single entry by exact key."""

    @abstractmethod
    def get_by_pattern(self, pattern: str) -> dict[str, MemoryEntry]:
        """Retrieve all entries matching a glob pattern (e.g. ``shared.*``)."""

    @abstractmethod
    def put(self, key: str, value: Any, written_by: str) -> MemoryEntry:
        """Write or overwrite an entry.  Returns the stored entry."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete an entry.  Returns ``True`` if it existed."""

    @abstractmethod
    def keys(self) -> list[str]:
        """Return all keys in the store."""

    @abstractmethod
    def clear(self) -> None:
        """Destroy all entries (called at dissolution)."""

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Return a plain dict snapshot of all ``key -> value`` pairs."""


class InMemoryBackend(SessionMemoryBackend):
    """Simple dict-backed implementation for v1."""

    def __init__(self) -> None:
        self._store: dict[str, MemoryEntry] = {}

    def get(self, key: str) -> MemoryEntry | None:
        return self._store.get(key)

    def get_by_pattern(self, pattern: str) -> dict[str, MemoryEntry]:
        regex = _glob_to_regex(pattern)
        return {k: v for k, v in self._store.items() if regex.match(k)}

    def put(self, key: str, value: Any, written_by: str) -> MemoryEntry:
        existing = self._store.get(key)
        version = (existing.version + 1) if existing else 1
        entry = MemoryEntry(
            key=key, value=value, written_by=written_by, version=version
        )
        self._store[key] = entry
        return entry

    def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    def keys(self) -> list[str]:
        return list(self._store.keys())

    def clear(self) -> None:
        self._store.clear()

    def snapshot(self) -> dict[str, Any]:
        return {k: v.value for k, v in self._store.items()}


# -----------------------------------------------------------------------
# SessionMemory – the coordinator-facing façade
# -----------------------------------------------------------------------


class SessionMemory:
    """Coordinator-facing façade for session-scoped shared memory.

    Wraps a backend with:
      - Per-agent access control (read/write policies)
      - Full audit trail
      - Snapshot generation for WS envelope injection (filtered by policy)
    """

    def __init__(self, backend: SessionMemoryBackend | None = None) -> None:
        self._backend = backend or InMemoryBackend()
        self._policies: dict[str, MemoryAccessPolicy] = {}  # agent_id -> policy
        self._audit: list[MemoryAuditEntry] = []

    # -- Policy management -------------------------------------------------

    def set_policy(self, policy: MemoryAccessPolicy) -> None:
        """Set the access policy for an agent.

        Called when building the composition plan (before execution begins).
        """
        self._policies[policy.agent_id] = policy
        logger.debug(
            "Memory policy set for '%s': read=%s, write=%s",
            policy.agent_id,
            policy.read_patterns,
            policy.write_patterns,
        )

    def get_policy(self, agent_id: str) -> MemoryAccessPolicy | None:
        return self._policies.get(agent_id)

    # -- Access-controlled operations -------------------------------------

    def read(self, key: str, agent_id: str) -> Any | None:
        """Read a single key, enforcing the agent's read policy.

        Returns the value if allowed, ``None`` if not found or denied.
        """
        if not self._check_read(key, agent_id):
            self._audit.append(
                MemoryAuditEntry(
                    operation="read",
                    key=key,
                    agent_id=agent_id,
                    allowed=False,
                    reason="denied by read policy",
                )
            )
            logger.debug(
                "Memory read DENIED: agent='%s', key='%s'", agent_id, key
            )
            return None

        entry = self._backend.get(key)
        self._audit.append(
            MemoryAuditEntry(
                operation="read", key=key, agent_id=agent_id, allowed=True
            )
        )
        return entry.value if entry else None

    def write(self, key: str, value: Any, agent_id: str) -> bool:
        """Write a key-value pair, enforcing the agent's write policy.

        Returns ``True`` if the write was accepted, ``False`` if denied.
        """
        if not self._check_write(key, agent_id):
            self._audit.append(
                MemoryAuditEntry(
                    operation="write",
                    key=key,
                    agent_id=agent_id,
                    allowed=False,
                    reason="denied by write policy",
                )
            )
            logger.warning(
                "Memory write DENIED: agent='%s', key='%s'", agent_id, key
            )
            return False

        self._backend.put(key, value, written_by=agent_id)
        self._audit.append(
            MemoryAuditEntry(
                operation="write", key=key, agent_id=agent_id, allowed=True
            )
        )
        logger.debug("Memory write: agent='%s', key='%s'", agent_id, key)
        return True

    def write_batch(
        self, writes: list[MemoryWriteRequest], agent_id: str
    ) -> list[bool]:
        """Apply a batch of writes (from an agent's COMPLETE response).

        Returns a list of booleans indicating which writes were accepted.
        """
        return [self.write(w.key, w.value, agent_id) for w in writes]

    # -- Snapshot for WS envelope ------------------------------------------

    def snapshot_for_agent(self, agent_id: str) -> dict[str, Any]:
        """Build a filtered snapshot containing only keys the agent can read.

        This is what gets serialised into the ``EXECUTE`` envelope's
        ``memory_snapshot`` field — only the relevant slice, not the
        entire store.
        """
        policy = self._policies.get(agent_id)
        if not policy:
            return {}

        result: dict[str, Any] = {}
        for pattern in policy.read_patterns:
            entries = self._backend.get_by_pattern(pattern)
            for key, entry in entries.items():
                if key not in result:
                    result[key] = entry.value
                    self._audit.append(
                        MemoryAuditEntry(
                            operation="read",
                            key=key,
                            agent_id=agent_id,
                            allowed=True,
                        )
                    )

        return result

    # -- Coordinator-level access (bypass IBAC) ----------------------------

    def coordinator_write(self, key: str, value: Any) -> None:
        """Direct write from the coordinator (no policy check)."""
        self._backend.put(key, value, written_by="coordinator")
        self._audit.append(
            MemoryAuditEntry(
                operation="write",
                key=key,
                agent_id="coordinator",
                allowed=True,
            )
        )

    def coordinator_read(self, key: str) -> Any | None:
        """Direct read by the coordinator (no policy check)."""
        entry = self._backend.get(key)
        return entry.value if entry else None

    def full_snapshot(self) -> dict[str, Any]:
        """Full unfiltered snapshot (for archival / debugging)."""
        return self._backend.snapshot()

    # -- Lifecycle ---------------------------------------------------------

    def clear(self) -> None:
        """Destroy all memory entries and audit trail (dissolution)."""
        key_count = len(self._backend.keys())
        self._backend.clear()
        self._policies.clear()
        logger.debug("Session memory cleared (%d keys destroyed)", key_count)

    # -- Audit -------------------------------------------------------------

    @property
    def audit_trail(self) -> list[MemoryAuditEntry]:
        return list(self._audit)

    def audit_summary(self) -> dict[str, Any]:
        """Return a summary of memory operations for archival."""
        return {
            "total_operations": len(self._audit),
            "writes": sum(
                1 for a in self._audit if a.operation == "write" and a.allowed
            ),
            "reads": sum(
                1 for a in self._audit if a.operation == "read" and a.allowed
            ),
            "denied": sum(1 for a in self._audit if not a.allowed),
            "keys_at_dissolution": self._backend.keys(),
        }

    # -- Internal helpers --------------------------------------------------

    def _check_read(self, key: str, agent_id: str) -> bool:
        if agent_id == "coordinator":
            return True
        policy = self._policies.get(agent_id)
        if not policy:
            return False
        return any(
            _matches_pattern(key, pattern) for pattern in policy.read_patterns
        )

    def _check_write(self, key: str, agent_id: str) -> bool:
        if agent_id == "coordinator":
            return True
        policy = self._policies.get(agent_id)
        if not policy:
            return False
        return any(
            _matches_pattern(key, pattern) for pattern in policy.write_patterns
        )


# -----------------------------------------------------------------------
# Module-level helpers
# -----------------------------------------------------------------------


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a simple glob pattern (with ``*``) to a compiled regex."""
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.compile(f"^{escaped}$")


def _matches_pattern(key: str, pattern: str) -> bool:
    """Check if a key matches a glob-style pattern."""
    regex = re.escape(pattern).replace(r"\*", ".*")
    return bool(re.match(f"^{regex}$", key))
