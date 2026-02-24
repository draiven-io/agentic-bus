"""Repository for session archive CRUD.

Provides persistence for dissolved session snapshots.  These archives
are read-only historical records — they do NOT violate Invariant II
because they are created *after* the live session is destroyed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.persistence.database import get_session
from app.core.persistence.models import SessionArchive, SessionOutcome

logger = logging.getLogger(__name__)


class SessionArchiveNotFoundError(Exception):
    """Raised when a requested session archive does not exist."""


class SessionArchiveRepository:
    """CRUD for session archives."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def archive_session(
        self,
        *,
        session_id: str,
        requester_id: str,
        requester_oidc_subject: str = "",
        intent_text: str = "",
        intent_domain: str = "",
        decomposition: dict[str, Any] | None = None,
        outcome: str = "success",
        outcome_summary: str = "",
        discovered_agents: list[str] | None = None,
        accepted_agents: list[str] | None = None,
        agents: dict[str, Any] | None = None,
        composition_plan: dict[str, Any] | None = None,
        execution_results: list[dict[str, Any]] | None = None,
        timeline_events: list[dict[str, Any]] | None = None,
        audit_trail: list[dict[str, Any]] | None = None,
        ibac_decisions: list[dict[str, Any]] | None = None,
        agent_metrics: list[dict[str, Any]] | None = None,
        output: str = "",
        output_summary: str = "",
        created_at: str | None = None,
        dissolved_at: str | None = None,
        duration_seconds: float = 0.0,
    ) -> SessionArchive:
        """Persist a session snapshot to the database."""
        # Map string outcome to enum
        try:
            outcome_enum = SessionOutcome(outcome)
        except ValueError:
            outcome_enum = SessionOutcome.SUCCESS

        # Parse timestamps
        now = datetime.now(timezone.utc)
        created_dt = now
        dissolved_dt = now
        if created_at:
            try:
                created_dt = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                pass
        if dissolved_at:
            try:
                dissolved_dt = datetime.fromisoformat(dissolved_at)
            except (ValueError, TypeError):
                pass

        archive = SessionArchive(
            session_id=session_id,
            requester_id=requester_id,
            requester_oidc_subject=requester_oidc_subject,
            intent_text=intent_text,
            intent_domain=intent_domain,
            decomposition_json=decomposition or {},
            outcome=outcome_enum,
            outcome_summary=outcome_summary,
            discovered_agents_json=discovered_agents or [],
            accepted_agents_json=accepted_agents or [],
            agents_json=agents or {},
            composition_plan_json=composition_plan or {},
            execution_results_json=execution_results or [],
            timeline_events_json=timeline_events or [],
            audit_trail_json=audit_trail or [],
            ibac_decisions_json=ibac_decisions or [],
            agent_metrics_json=agent_metrics or [],
            output=output,
            output_summary=output_summary,
            created_at=created_dt,
            dissolved_at=dissolved_dt,
            duration_seconds=duration_seconds,
        )

        with get_session() as session:
            session.add(archive)
            session.commit()
            session.refresh(archive)
            logger.info("Archived session %s (outcome=%s)", session_id, outcome)
            return archive

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, session_id: str) -> SessionArchive | None:
        """Get a single archive by session ID."""
        with get_session() as session:
            return (
                session.query(SessionArchive)
                .filter(SessionArchive.session_id == session_id)
                .first()
            )

    def list_all(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        outcome: str | None = None,
    ) -> list[SessionArchive]:
        """List archives, newest first."""
        with get_session() as session:
            q = session.query(SessionArchive).order_by(
                SessionArchive.dissolved_at.desc()
            )
            if outcome:
                try:
                    q = q.filter(SessionArchive.outcome == SessionOutcome(outcome))
                except ValueError:
                    pass
            return list(q.offset(offset).limit(limit).all())

    def count(self, *, outcome: str | None = None) -> int:
        """Count total archives."""
        with get_session() as session:
            q = session.query(SessionArchive)
            if outcome:
                try:
                    q = q.filter(SessionArchive.outcome == SessionOutcome(outcome))
                except ValueError:
                    pass
            return q.count()

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, session_id: str) -> bool:
        """Delete an archive by session ID.  Returns True if found."""
        with get_session() as session:
            archive = (
                session.query(SessionArchive)
                .filter(SessionArchive.session_id == session_id)
                .first()
            )
            if archive is None:
                return False
            session.delete(archive)
            session.commit()
            logger.info("Deleted session archive %s", session_id)
            return True

    def delete_older_than(self, before: datetime) -> int:
        """Bulk-delete archives older than *before*.  Returns count deleted."""
        with get_session() as session:
            count = (
                session.query(SessionArchive)
                .filter(SessionArchive.dissolved_at < before)
                .delete()
            )
            session.commit()
            logger.info("Purged %d session archives older than %s", count, before)
            return count
