"""Repository for User CRUD and user-tenant association operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.persistence.database import get_session
from app.core.persistence.models import (
    User,
    UserRole,
    UserTenantAssociation,
)

logger = logging.getLogger(__name__)


class UserRepository:
    """CRUD operations for users and user-tenant associations."""

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        subject: str,
        *,
        email: str = "",
        display_name: str = "",
        role: UserRole = UserRole.USER,
        enabled: bool = True,
        created_by: str = "admin",
    ) -> User:
        with get_session() as session:
            existing = session.query(User).filter_by(subject=subject).first()
            if existing is not None:
                raise ValueError(f"User with subject {subject!r} already exists")
            user = User(
                subject=subject,
                email=email,
                display_name=display_name,
                role=role,
                enabled=enabled,
                created_by=created_by,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        return user

    def get(self, user_id: int) -> User | None:
        with get_session() as session:
            return session.get(User, user_id)

    def get_by_subject(self, subject: str) -> User | None:
        with get_session() as session:
            return session.query(User).filter_by(subject=subject).first()

    def list_all(self, *, role: UserRole | None = None) -> list[User]:
        with get_session() as session:
            q = session.query(User)
            if role is not None:
                q = q.filter_by(role=role)
            return list(q.order_by(User.display_name).all())

    def update(
        self,
        user_id: int,
        *,
        email: str | None = None,
        display_name: str | None = None,
        role: UserRole | None = None,
        enabled: bool | None = None,
    ) -> User:
        with get_session() as session:
            user = session.get(User, user_id)
            if user is None:
                raise ValueError(f"User {user_id} not found")
            if email is not None:
                user.email = email
            if display_name is not None:
                user.display_name = display_name
            if role is not None:
                user.role = role
            if enabled is not None:
                user.enabled = enabled
            user.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(user)
        return user

    def delete(self, user_id: int) -> bool:
        with get_session() as session:
            user = session.get(User, user_id)
            if user is None:
                return False
            session.delete(user)
            session.commit()
        return True

    # ------------------------------------------------------------------
    # User ↔ Tenant assignments
    # ------------------------------------------------------------------

    def assign_tenant(self, user_id: int, tenant_id: int) -> UserTenantAssociation:
        with get_session() as session:
            existing = (
                session.query(UserTenantAssociation)
                .filter_by(user_id=user_id, tenant_id=tenant_id)
                .first()
            )
            if existing is not None:
                return existing  # idempotent
            assoc = UserTenantAssociation(user_id=user_id, tenant_id=tenant_id)
            session.add(assoc)
            session.commit()
            session.refresh(assoc)
        return assoc

    def unassign_tenant(self, user_id: int, tenant_id: int) -> bool:
        with get_session() as session:
            assoc = (
                session.query(UserTenantAssociation)
                .filter_by(user_id=user_id, tenant_id=tenant_id)
                .first()
            )
            if assoc is None:
                return False
            session.delete(assoc)
            session.commit()
        return True

    def get_user_tenant_ids(self, user_id: int) -> list[int]:
        """Return all tenant IDs for a given user."""
        with get_session() as session:
            rows = (
                session.query(UserTenantAssociation.tenant_id)
                .filter_by(user_id=user_id)
                .all()
            )
            return [r[0] for r in rows]
