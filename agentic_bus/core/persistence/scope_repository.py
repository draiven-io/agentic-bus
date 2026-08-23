"""Storage for the scope vocabulary: catalogue, bindings, requests.

Three things, kept apart because they answer different questions:

``catalogue``
    What names this coordinator recognises. A property of the deployment.

``bindings``
    Which of those names a particular agent's capability has been granted.
    The binding is the authority; an agent's declaration never is.

``requests``
    What agents asked for that the catalogue did not have. Recorded because
    it is an agent telling an operator what it needs, and that used to be
    thrown away.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from agentic_bus.core.persistence.database import get_session
from agentic_bus.core.persistence.models import (
    CapabilityScopeBinding,
    ScopeCatalogueEntry,
    ScopeRequest,
)
from agentic_bus.core.scopes import covered_by_any, is_well_formed, normalise

logger = logging.getLogger(__name__)


class ScopeRepository:
    """CRUD for the scope catalogue and its bindings."""

    # -- catalogue ------------------------------------------------------

    def catalogue(self) -> list[str]:
        """Every recognised scope name, sorted for stable display."""
        with get_session() as session:
            rows = session.query(ScopeCatalogueEntry).all()
            return sorted(row.name for row in rows)

    def catalogue_entries(self) -> list[ScopeCatalogueEntry]:
        with get_session() as session:
            rows = session.query(ScopeCatalogueEntry).all()
            for row in rows:
                session.expunge(row)
            return sorted(rows, key=lambda r: r.name)

    def add_scope(
        self, name: str, description: str = "", created_by: str = "admin"
    ) -> bool:
        """Add a name to the catalogue. Returns ``False`` if already present.

        Rejects a malformed name rather than storing something that can never
        match: a catalogue entry nothing can match is worse than a missing one,
        because it looks like coverage.
        """
        name = normalise(name)
        if not is_well_formed(name):
            raise ValueError(f"{name!r} is not a usable scope name")

        with get_session() as session:
            if session.get(ScopeCatalogueEntry, name) is not None:
                return False
            session.add(
                ScopeCatalogueEntry(
                    name=name, description=description, created_by=created_by
                )
            )
            session.commit()
        logger.info("Scope %r catalogued by %s", name, created_by)
        return True

    def remove_scope(self, name: str) -> bool:
        """Remove a name, and every binding that granted it.

        A binding to a name the catalogue no longer has would be a grant of
        something undefined, which is worse than no grant.
        """
        name = normalise(name)
        with get_session() as session:
            entry = session.get(ScopeCatalogueEntry, name)
            if entry is None:
                return False
            orphaned = (
                session.query(CapabilityScopeBinding)
                .filter(CapabilityScopeBinding.scope == name)
                .delete()
            )
            session.delete(entry)
            session.commit()
        if orphaned:
            logger.warning(
                "Removing scope %r also removed %d binding(s) that granted it",
                name,
                orphaned,
            )
        return True

    def recognises(self, scope: str) -> bool:
        return covered_by_any(self.catalogue(), scope)

    # -- bindings -------------------------------------------------------

    def bind(
        self,
        agent_id: str,
        capability_id: str,
        scopes: list[str],
        bound_by: str = "admin",
    ) -> list[str]:
        """Grant *scopes* to one capability. Returns what was newly bound.

        Refuses to bind a name the catalogue does not recognise: binding is
        how a decision is recorded, and a decision about a name nobody defined
        is not one.
        """
        catalogue = self.catalogue()
        newly: list[str] = []

        with get_session() as session:
            for raw in scopes:
                scope = normalise(raw)
                if not covered_by_any(catalogue, scope):
                    raise ValueError(
                        f"{scope!r} is not in the catalogue; add it before binding"
                    )
                exists = (
                    session.query(CapabilityScopeBinding)
                    .filter(
                        CapabilityScopeBinding.agent_id == agent_id,
                        CapabilityScopeBinding.capability_id == capability_id,
                        CapabilityScopeBinding.scope == scope,
                    )
                    .first()
                )
                if exists is not None:
                    continue
                session.add(
                    CapabilityScopeBinding(
                        agent_id=agent_id,
                        capability_id=capability_id,
                        scope=scope,
                        bound_by=bound_by,
                    )
                )
                newly.append(scope)
            session.commit()

        if newly:
            logger.info(
                "Bound %s to %s:%s by %s",
                ", ".join(newly),
                agent_id,
                capability_id,
                bound_by,
            )
        return newly

    def unbind(self, agent_id: str, capability_id: str, scope: str) -> bool:
        with get_session() as session:
            removed = (
                session.query(CapabilityScopeBinding)
                .filter(
                    CapabilityScopeBinding.agent_id == agent_id,
                    CapabilityScopeBinding.capability_id == capability_id,
                    CapabilityScopeBinding.scope == normalise(scope),
                )
                .delete()
            )
            session.commit()
        return bool(removed)

    def granted(self, agent_id: str, capability_id: str) -> list[str]:
        """What this capability holds. Empty when unbound, which is the point."""
        with get_session() as session:
            rows = (
                session.query(CapabilityScopeBinding)
                .filter(
                    CapabilityScopeBinding.agent_id == agent_id,
                    CapabilityScopeBinding.capability_id == capability_id,
                )
                .all()
            )
            return sorted(row.scope for row in rows)

    def granted_for_agent(self, agent_id: str) -> dict[str, list[str]]:
        """Every binding for an agent, by capability."""
        with get_session() as session:
            rows = (
                session.query(CapabilityScopeBinding)
                .filter(CapabilityScopeBinding.agent_id == agent_id)
                .all()
            )
        out: dict[str, list[str]] = {}
        for row in rows:
            out.setdefault(row.capability_id, []).append(row.scope)
        return {k: sorted(v) for k, v in out.items()}

    def unbind_agent(self, agent_id: str) -> int:
        """Drop every binding for an agent. Used when it is deleted."""
        with get_session() as session:
            removed = (
                session.query(CapabilityScopeBinding)
                .filter(CapabilityScopeBinding.agent_id == agent_id)
                .delete()
            )
            session.commit()
        return int(removed)

    # -- requests -------------------------------------------------------

    def record_request(
        self, agent_id: str, scope: str, capability_id: str = ""
    ) -> None:
        """Note that an agent asked for a scope the catalogue does not have.

        Idempotent per (agent, capability, scope): repeated registrations
        increment a counter rather than filling a queue with the same line.
        """
        scope = normalise(scope)
        now = datetime.now(timezone.utc)

        with get_session() as session:
            existing = (
                session.query(ScopeRequest)
                .filter(
                    ScopeRequest.agent_id == agent_id,
                    ScopeRequest.capability_id == capability_id,
                    ScopeRequest.scope == scope,
                )
                .first()
            )
            if existing is not None:
                existing.request_count += 1
                existing.last_requested_at = now
            else:
                session.add(
                    ScopeRequest(
                        agent_id=agent_id,
                        capability_id=capability_id,
                        scope=scope,
                        first_requested_at=now,
                        last_requested_at=now,
                    )
                )
            session.commit()

    def pending_requests(self) -> list[ScopeRequest]:
        """Scopes agents have asked for and nobody has catalogued.

        Entries whose scope has since been catalogued are filtered out rather
        than deleted, so the record of who asked survives.
        """
        catalogue = self.catalogue()
        with get_session() as session:
            rows = session.query(ScopeRequest).all()
            for row in rows:
                session.expunge(row)
        pending = [r for r in rows if not covered_by_any(catalogue, r.scope)]
        return sorted(pending, key=lambda r: (-r.request_count, r.scope))

    def clear_request(self, agent_id: str, scope: str, capability_id: str = "") -> bool:
        with get_session() as session:
            removed = (
                session.query(ScopeRequest)
                .filter(
                    ScopeRequest.agent_id == agent_id,
                    ScopeRequest.capability_id == capability_id,
                    ScopeRequest.scope == normalise(scope),
                )
                .delete()
            )
            session.commit()
        return bool(removed)
