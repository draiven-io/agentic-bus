"""Repository for Tenant CRUD operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from agentic_bus.core.persistence.database import get_session
from agentic_bus.core.persistence.models import (
    AgentTenantAssociation,
    Tenant,
)

logger = logging.getLogger(__name__)


class TenantRepository:
    """CRUD operations for tenants and agent-tenant associations."""

    # ------------------------------------------------------------------
    # Tenant CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        slug: str,
        name: str,
        *,
        enabled: bool = True,
    ) -> Tenant:
        with get_session() as session:
            existing = session.query(Tenant).filter_by(slug=slug).first()
            if existing is not None:
                raise ValueError(f"Tenant with slug {slug!r} already exists")
            tenant = Tenant(slug=slug, name=name, enabled=enabled)
            session.add(tenant)
            session.commit()
            session.refresh(tenant)
        return tenant

    def get(self, tenant_id: int) -> Tenant | None:
        with get_session() as session:
            return session.get(Tenant, tenant_id)

    def get_by_slug(self, slug: str) -> Tenant | None:
        with get_session() as session:
            return session.query(Tenant).filter_by(slug=slug).first()

    def list_all(self, *, enabled_only: bool = False) -> list[Tenant]:
        with get_session() as session:
            q = session.query(Tenant)
            if enabled_only:
                q = q.filter_by(enabled=True)
            return list(q.order_by(Tenant.name).all())

    def update(
        self,
        tenant_id: int,
        *,
        name: str | None = None,
        enabled: bool | None = None,
    ) -> Tenant:
        with get_session() as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                raise ValueError(f"Tenant {tenant_id} not found")
            if name is not None:
                tenant.name = name
            if enabled is not None:
                tenant.enabled = enabled
            tenant.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(tenant)
        return tenant

    def delete(self, tenant_id: int) -> bool:
        with get_session() as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return False
            session.delete(tenant)
            session.commit()
        return True

    # ------------------------------------------------------------------
    # Agent ↔ Tenant assignments
    # ------------------------------------------------------------------

    def assign_agent(self, agent_id: str, tenant_id: int) -> AgentTenantAssociation:
        with get_session() as session:
            existing = (
                session.query(AgentTenantAssociation)
                .filter_by(agent_id=agent_id, tenant_id=tenant_id)
                .first()
            )
            if existing is not None:
                return existing  # idempotent
            assoc = AgentTenantAssociation(agent_id=agent_id, tenant_id=tenant_id)
            session.add(assoc)
            session.commit()
            session.refresh(assoc)
        return assoc

    def unassign_agent(self, agent_id: str, tenant_id: int) -> bool:
        with get_session() as session:
            assoc = (
                session.query(AgentTenantAssociation)
                .filter_by(agent_id=agent_id, tenant_id=tenant_id)
                .first()
            )
            if assoc is None:
                return False
            session.delete(assoc)
            session.commit()
        return True

    def get_agent_tenant_ids(self, agent_id: str) -> list[int]:
        """Return all tenant IDs for a given agent."""
        with get_session() as session:
            rows = (
                session.query(AgentTenantAssociation.tenant_id)
                .filter_by(agent_id=agent_id)
                .all()
            )
            return [r[0] for r in rows]

    def get_tenant_agent_ids(self, tenant_id: int) -> list[str]:
        """Return all agent IDs assigned to a tenant."""
        with get_session() as session:
            rows = (
                session.query(AgentTenantAssociation.agent_id)
                .filter_by(tenant_id=tenant_id)
                .all()
            )
            return [r[0] for r in rows]
