"""Tests for admin authorization and admin service."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.auth.admin import AdminPolicy, require_admin
from app.core.auth.oidc import OIDCIdentity
from app.core.persistence.models import Base
from app.core.persistence.repository import AgentRepository
from app.coordinator.admin.service import AdminService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _identity(
    subject: str = "user-1",
    roles: list[str] | None = None,
    **extra_claims: object,
) -> OIDCIdentity:
    claims: dict = {}
    if roles is not None:
        claims["roles"] = roles
    claims.update(extra_claims)
    return OIDCIdentity(
        subject=subject,
        issuer="dev",
        audience="agbus",
        scopes=[],
        custom_claims=claims,
    )


def _generate_public_pem() -> str:
    private = Ed25519PrivateKey.generate()
    return private.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ).decode()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(
        "app.core.persistence.repository.get_session",
        lambda: factory(),
    )
    return AgentRepository()


# ---------------------------------------------------------------------------
# AdminPolicy
# ---------------------------------------------------------------------------


class TestAdminPolicy:
    def test_subject_match(self):
        policy = AdminPolicy(subjects={"admin-sub"})
        assert policy.is_admin(_identity(subject="admin-sub")) is True

    def test_subject_no_match(self):
        policy = AdminPolicy(subjects={"admin-sub"})
        assert policy.is_admin(_identity(subject="other")) is False

    def test_role_match_list(self):
        policy = AdminPolicy(role="agbus:admin", role_claim="roles")
        ident = _identity(roles=["agbus:admin", "agbus:user"])
        assert policy.is_admin(ident) is True

    def test_role_match_string(self):
        policy = AdminPolicy(role="agbus:admin", role_claim="roles")
        ident = _identity(roles="agbus:admin")  # type: ignore[arg-type]
        # custom_claims will have roles as a string
        ident.custom_claims["roles"] = "agbus:admin"
        assert policy.is_admin(ident) is True

    def test_role_no_match(self):
        policy = AdminPolicy(role="agbus:admin", role_claim="roles")
        ident = _identity(roles=["agbus:user"])
        assert policy.is_admin(ident) is False

    def test_no_role_claim_present(self):
        policy = AdminPolicy(role="agbus:admin", role_claim="roles")
        ident = _identity()  # no roles claim
        assert policy.is_admin(ident) is False

    def test_custom_role_claim_key(self):
        policy = AdminPolicy(role="admin", role_claim="permissions")
        ident = _identity(permissions=["admin", "read"])
        assert policy.is_admin(ident) is True

    def test_either_subject_or_role_suffices(self):
        policy = AdminPolicy(subjects={"admin-sub"}, role="agbus:admin")
        # Match by subject (no roles)
        assert policy.is_admin(_identity(subject="admin-sub")) is True
        # Match by role (different subject)
        assert policy.is_admin(_identity(subject="other", roles=["agbus:admin"])) is True
        # Neither
        assert policy.is_admin(_identity(subject="other", roles=["nope"])) is False

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("AGBUS_ADMIN_SUBJECTS", "alice, bob ,charlie")
        monkeypatch.setenv("AGBUS_ADMIN_ROLE", "superadmin")
        monkeypatch.setenv("AGBUS_ADMIN_ROLE_CLAIM", "grants")
        policy = AdminPolicy.from_env()
        assert policy.subjects == {"alice", "bob", "charlie"}
        assert policy.role == "superadmin"
        assert policy.role_claim == "grants"

    def test_from_env_defaults(self, monkeypatch):
        monkeypatch.delenv("AGBUS_ADMIN_SUBJECTS", raising=False)
        monkeypatch.delenv("AGBUS_ADMIN_ROLE", raising=False)
        monkeypatch.delenv("AGBUS_ADMIN_ROLE_CLAIM", raising=False)
        policy = AdminPolicy.from_env()
        assert policy.subjects == set()
        assert policy.role == "agbus:admin"
        assert policy.role_claim == "roles"


# ---------------------------------------------------------------------------
# require_admin helper
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    def test_passes_for_admin(self):
        policy = AdminPolicy(subjects={"admin-1"})
        require_admin(_identity(subject="admin-1"), policy)  # should not raise

    def test_raises_for_non_admin(self):
        policy = AdminPolicy(subjects={"admin-1"})
        with pytest.raises(PermissionError, match="Admin privileges required"):
            require_admin(_identity(subject="pleb"), policy)


# ---------------------------------------------------------------------------
# AdminService
# ---------------------------------------------------------------------------


class TestAdminService:
    def _make_service(self, repo: AgentRepository, admin_subject: str = "admin-1"):
        policy = AdminPolicy(subjects={admin_subject})
        return AdminService(repo=repo, policy=policy)

    def test_approve_as_admin(self, repo):
        svc = self._make_service(repo)
        repo.enrol("a1", _generate_public_pem())
        agent = svc.approve_agent("a1", _identity(subject="admin-1"))
        assert agent.status.value == "approved"
        assert agent.approved_by == "admin-1"

    def test_approve_as_non_admin_raises(self, repo):
        svc = self._make_service(repo)
        repo.enrol("a2", _generate_public_pem())
        with pytest.raises(PermissionError):
            svc.approve_agent("a2", _identity(subject="random-user"))

    def test_reject_as_admin(self, repo):
        svc = self._make_service(repo)
        repo.enrol("a3", _generate_public_pem())
        agent = svc.reject_agent("a3", _identity(subject="admin-1"))
        assert agent.status.value == "rejected"

    def test_reject_as_non_admin_raises(self, repo):
        svc = self._make_service(repo)
        repo.enrol("a4", _generate_public_pem())
        with pytest.raises(PermissionError):
            svc.reject_agent("a4", _identity(subject="nobody"))

    def test_revoke_as_admin(self, repo):
        svc = self._make_service(repo)
        repo.enrol("a5", _generate_public_pem())
        repo.approve("a5")
        agent = svc.revoke_agent("a5", _identity(subject="admin-1"))
        assert agent.status.value == "revoked"

    def test_delete_as_admin(self, repo):
        svc = self._make_service(repo)
        repo.enrol("a6", _generate_public_pem())
        assert svc.delete_agent("a6", _identity(subject="admin-1")) is True
        assert repo.get("a6") is None

    def test_delete_as_non_admin_raises(self, repo):
        svc = self._make_service(repo)
        repo.enrol("a7", _generate_public_pem())
        with pytest.raises(PermissionError):
            svc.delete_agent("a7", _identity(subject="nobody"))

    # -- read-only (no admin check) ----------------------------------------

    def test_list_agents(self, repo):
        svc = self._make_service(repo)
        repo.enrol("r1", _generate_public_pem())
        repo.enrol("r2", _generate_public_pem())
        assert len(svc.list_agents()) == 2

    def test_list_pending(self, repo):
        svc = self._make_service(repo)
        repo.enrol("p1", _generate_public_pem())
        repo.enrol("p2", _generate_public_pem())
        repo.approve("p2")
        pending = svc.list_pending()
        assert len(pending) == 1
        assert pending[0].agent_id == "p1"

    def test_get_agent(self, repo):
        svc = self._make_service(repo)
        repo.enrol("g1", _generate_public_pem())
        assert svc.get_agent("g1") is not None
        assert svc.get_agent("ghost") is None

    def test_approve_via_role(self, repo):
        """Admin access via role claim instead of subject list."""
        policy = AdminPolicy(role="agbus:admin", role_claim="roles")
        svc = AdminService(repo=repo, policy=policy)
        repo.enrol("role-agent", _generate_public_pem())
        admin_ident = _identity(subject="some-user", roles=["agbus:admin"])
        agent = svc.approve_agent("role-agent", admin_ident)
        assert agent.status.value == "approved"
        assert agent.approved_by == "some-user"
