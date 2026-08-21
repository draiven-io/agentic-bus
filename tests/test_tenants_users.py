"""Tests for multi-tenant user management – models, repositories, API scoping."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.persistence.models import (
    Base,
    UserRole,
)
from app.core.persistence.tenant_repository import TenantRepository
from app.core.persistence.user_repository import UserRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite:///:memory:", echo=False, future=True)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture()
def tenant_repo(session_factory, monkeypatch):
    monkeypatch.setattr(
        "app.core.persistence.tenant_repository.get_session",
        lambda: session_factory(),
    )
    return TenantRepository()


@pytest.fixture()
def user_repo(session_factory, monkeypatch):
    monkeypatch.setattr(
        "app.core.persistence.user_repository.get_session",
        lambda: session_factory(),
    )
    return UserRepository()


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------


class TestTenantCRUD:
    def test_create_tenant(self, tenant_repo):
        t = tenant_repo.create("acme", "Acme Corp")
        assert t.slug == "acme"
        assert t.name == "Acme Corp"
        assert t.enabled is True

    def test_create_duplicate_slug_raises(self, tenant_repo):
        tenant_repo.create("dup", "Dup Inc")
        with pytest.raises(ValueError, match="already exists"):
            tenant_repo.create("dup", "Dup Again")

    def test_get_by_slug(self, tenant_repo):
        tenant_repo.create("slug1", "Slug One")
        found = tenant_repo.get_by_slug("slug1")
        assert found is not None
        assert found.name == "Slug One"

    def test_get_by_slug_not_found(self, tenant_repo):
        assert tenant_repo.get_by_slug("nonexistent") is None

    def test_list_all(self, tenant_repo):
        tenant_repo.create("a", "Alpha")
        tenant_repo.create("b", "Bravo")
        all_tenants = tenant_repo.list_all()
        assert len(all_tenants) == 2

    def test_list_enabled_only(self, tenant_repo):
        tenant_repo.create("active", "Active", enabled=True)
        t2 = tenant_repo.create("disabled", "Disabled", enabled=True)
        tenant_repo.update(t2.id, enabled=False)
        enabled = tenant_repo.list_all(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0].slug == "active"

    def test_update_tenant(self, tenant_repo):
        t = tenant_repo.create("upd", "Original")
        updated = tenant_repo.update(t.id, name="Updated", enabled=False)
        assert updated.name == "Updated"
        assert updated.enabled is False

    def test_update_nonexistent_raises(self, tenant_repo):
        with pytest.raises(ValueError, match="not found"):
            tenant_repo.update(9999, name="Nope")

    def test_delete_tenant(self, tenant_repo):
        t = tenant_repo.create("del", "Delete Me")
        assert tenant_repo.delete(t.id) is True
        assert tenant_repo.get(t.id) is None

    def test_delete_nonexistent(self, tenant_repo):
        assert tenant_repo.delete(9999) is False


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------


class TestUserCRUD:
    def test_create_user(self, user_repo):
        u = user_repo.create(
            "auth0|123",
            email="jane@example.com",
            display_name="Jane Doe",
            role=UserRole.USER,
        )
        assert u.subject == "auth0|123"
        assert u.email == "jane@example.com"
        assert u.role == UserRole.USER

    def test_create_admin_user(self, user_repo):
        u = user_repo.create("admin|1", role=UserRole.ADMIN)
        assert u.role == UserRole.ADMIN

    def test_create_duplicate_subject_raises(self, user_repo):
        user_repo.create("dup-sub")
        with pytest.raises(ValueError, match="already exists"):
            user_repo.create("dup-sub")

    def test_get_by_subject(self, user_repo):
        user_repo.create("sub1", display_name="Sub One")
        found = user_repo.get_by_subject("sub1")
        assert found is not None
        assert found.display_name == "Sub One"

    def test_list_all(self, user_repo):
        user_repo.create("u1", display_name="A")
        user_repo.create("u2", display_name="B")
        users = user_repo.list_all()
        assert len(users) == 2

    def test_list_by_role(self, user_repo):
        user_repo.create("u1", role=UserRole.ADMIN)
        user_repo.create("u2", role=UserRole.USER)
        admins = user_repo.list_all(role=UserRole.ADMIN)
        assert len(admins) == 1
        assert admins[0].subject == "u1"

    def test_update_user(self, user_repo):
        u = user_repo.create("upd-u", display_name="Old")
        updated = user_repo.update(u.id, display_name="New", role=UserRole.ADMIN)
        assert updated.display_name == "New"
        assert updated.role == UserRole.ADMIN

    def test_update_nonexistent_raises(self, user_repo):
        with pytest.raises(ValueError, match="not found"):
            user_repo.update(9999, email="x")

    def test_delete_user(self, user_repo):
        u = user_repo.create("del-u")
        assert user_repo.delete(u.id) is True
        assert user_repo.get(u.id) is None

    def test_delete_nonexistent(self, user_repo):
        assert user_repo.delete(9999) is False


# ---------------------------------------------------------------------------
# User ↔ Tenant assignments
# ---------------------------------------------------------------------------


class TestUserTenantAssignment:
    def test_assign_and_list(self, user_repo, tenant_repo):
        t = tenant_repo.create("t1", "Tenant 1")
        u = user_repo.create("u1")
        user_repo.assign_tenant(u.id, t.id)
        tids = user_repo.get_user_tenant_ids(u.id)
        assert tids == [t.id]

    def test_assign_idempotent(self, user_repo, tenant_repo):
        t = tenant_repo.create("t-idem", "Idempotent")
        u = user_repo.create("u-idem")
        user_repo.assign_tenant(u.id, t.id)
        user_repo.assign_tenant(u.id, t.id)  # second call should be no-op
        tids = user_repo.get_user_tenant_ids(u.id)
        assert tids == [t.id]

    def test_unassign(self, user_repo, tenant_repo):
        t = tenant_repo.create("t-un", "Unassign")
        u = user_repo.create("u-un")
        user_repo.assign_tenant(u.id, t.id)
        assert user_repo.unassign_tenant(u.id, t.id) is True
        assert user_repo.get_user_tenant_ids(u.id) == []

    def test_unassign_nonexistent(self, user_repo):
        assert user_repo.unassign_tenant(999, 999) is False

    def test_multiple_tenants(self, user_repo, tenant_repo):
        t1 = tenant_repo.create("mt1", "Multi 1")
        t2 = tenant_repo.create("mt2", "Multi 2")
        u = user_repo.create("multi-u")
        user_repo.assign_tenant(u.id, t1.id)
        user_repo.assign_tenant(u.id, t2.id)
        tids = sorted(user_repo.get_user_tenant_ids(u.id))
        assert tids == sorted([t1.id, t2.id])


# ---------------------------------------------------------------------------
# Agent ↔ Tenant assignments
# ---------------------------------------------------------------------------


class TestAgentTenantAssignment:
    def test_assign_agent(self, tenant_repo):
        t = tenant_repo.create("at1", "Agent Tenant")
        tenant_repo.assign_agent("agent-1", t.id)
        assert tenant_repo.get_agent_tenant_ids("agent-1") == [t.id]

    def test_assign_agent_idempotent(self, tenant_repo):
        t = tenant_repo.create("at-idem", "Idempotent")
        tenant_repo.assign_agent("agent-idem", t.id)
        tenant_repo.assign_agent("agent-idem", t.id)
        assert len(tenant_repo.get_agent_tenant_ids("agent-idem")) == 1

    def test_unassign_agent(self, tenant_repo):
        t = tenant_repo.create("at-un", "Unassign")
        tenant_repo.assign_agent("agent-un", t.id)
        assert tenant_repo.unassign_agent("agent-un", t.id) is True
        assert tenant_repo.get_agent_tenant_ids("agent-un") == []

    def test_get_tenant_agent_ids(self, tenant_repo):
        t = tenant_repo.create("at-list", "List")
        tenant_repo.assign_agent("a1", t.id)
        tenant_repo.assign_agent("a2", t.id)
        aids = sorted(tenant_repo.get_tenant_agent_ids(t.id))
        assert aids == ["a1", "a2"]

    def test_agent_in_multiple_tenants(self, tenant_repo):
        t1 = tenant_repo.create("amt1", "Multi 1")
        t2 = tenant_repo.create("amt2", "Multi 2")
        tenant_repo.assign_agent("shared-agent", t1.id)
        tenant_repo.assign_agent("shared-agent", t2.id)
        tids = sorted(tenant_repo.get_agent_tenant_ids("shared-agent"))
        assert tids == sorted([t1.id, t2.id])
