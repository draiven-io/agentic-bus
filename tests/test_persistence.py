"""Tests for agent persistence – enrolment, approval, challenge auth, and registry integration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PublicFormat,
    PrivateFormat,
)
from sqlalchemy import create_engine

from app.core.persistence.database import init_db, get_engine
from app.core.persistence.models import AgentStatus, Base, PersistentAgent
from app.core.persistence.repository import AgentRepository
from app.core.registry.capability_registry import (
    AgentCapability,
    AgentRegistration,
    CapabilityRegistry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _generate_keypair() -> tuple[Ed25519PrivateKey, str]:
    """Generate an Ed25519 keypair and return (private_key, public_pem)."""
    private = Ed25519PrivateKey.generate()
    public_pem = private.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private, public_pem


@pytest.fixture()
def db_engine(tmp_path):
    """Create a fresh in-memory SQLite engine and init tables."""
    engine = create_engine("sqlite:///:memory:", echo=False, future=True)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def repo(db_engine, monkeypatch):
    """Return an AgentRepository wired to the in-memory DB."""
    from sqlalchemy.orm import sessionmaker, Session
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    # Patch get_session so the repository uses our in-memory DB
    monkeypatch.setattr(
        "app.core.persistence.repository.get_session",
        lambda: factory(),
    )
    return AgentRepository()


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------


class TestEnrolment:
    def test_enrol_creates_pending_agent(self, repo):
        _, pub_pem = _generate_keypair()
        agent = repo.enrol("agent-1", pub_pem, semantic_description="Test agent")
        assert agent.agent_id == "agent-1"
        assert agent.status == AgentStatus.PENDING

    def test_enrol_auto_approve(self, repo, monkeypatch):
        monkeypatch.setenv("AGBUS_AGENT_AUTO_APPROVE", "true")
        _, pub_pem = _generate_keypair()
        agent = repo.enrol("agent-auto", pub_pem)
        assert agent.status == AgentStatus.APPROVED

    def test_enrol_duplicate_raises(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("dup-agent", pub_pem)
        with pytest.raises(ValueError, match="already enrolled"):
            repo.enrol("dup-agent", pub_pem)

    def test_enrol_invalid_key_raises(self, repo):
        with pytest.raises(Exception):
            repo.enrol("bad-key-agent", "not-a-valid-pem")


# ---------------------------------------------------------------------------
# Admin approval workflow
# ---------------------------------------------------------------------------


class TestApproval:
    def test_approve_pending(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("agent-pending", pub_pem)
        approved = repo.approve("agent-pending", approved_by="admin-1")
        assert approved.status == AgentStatus.APPROVED
        assert approved.approved_by == "admin-1"
        assert approved.approved_at is not None

    def test_approve_non_pending_raises(self, repo, monkeypatch):
        monkeypatch.setenv("AGBUS_AGENT_AUTO_APPROVE", "true")
        _, pub_pem = _generate_keypair()
        repo.enrol("already-approved", pub_pem)
        with pytest.raises(ValueError, match="not pending"):
            repo.approve("already-approved")

    def test_reject_pending(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("agent-rej", pub_pem)
        rejected = repo.reject("agent-rej")
        assert rejected.status == AgentStatus.REJECTED

    def test_revoke_approved(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("agent-rev", pub_pem)
        repo.approve("agent-rev")
        revoked = repo.revoke("agent-rev")
        assert revoked.status == AgentStatus.REVOKED

    def test_approve_nonexistent_raises(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.approve("ghost")


# ---------------------------------------------------------------------------
# Challenge–response authentication
# ---------------------------------------------------------------------------


class TestChallengeAuth:
    def test_full_challenge_flow(self, repo):
        """Enrol → approve → challenge → sign → verify succeeds."""
        priv, pub_pem = _generate_keypair()
        repo.enrol("auth-agent", pub_pem)
        repo.approve("auth-agent")

        nonce = repo.request_challenge("auth-agent")
        assert isinstance(nonce, bytes) and len(nonce) == 32

        signature = priv.sign(nonce)
        assert repo.verify_challenge("auth-agent", signature) is True

    def test_challenge_wrong_signature_fails(self, repo):
        priv, pub_pem = _generate_keypair()
        repo.enrol("wrong-sig", pub_pem)
        repo.approve("wrong-sig")

        nonce = repo.request_challenge("wrong-sig")
        # Sign with a *different* key
        other_priv = Ed25519PrivateKey.generate()
        bad_sig = other_priv.sign(nonce)
        assert repo.verify_challenge("wrong-sig", bad_sig) is False

    def test_challenge_not_approved_raises(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("pending-agent", pub_pem)
        with pytest.raises(PermissionError, match="not approved"):
            repo.request_challenge("pending-agent")

    def test_challenge_unknown_agent_raises(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.request_challenge("nobody")

    def test_verify_without_challenge_raises(self, repo):
        priv, pub_pem = _generate_keypair()
        repo.enrol("no-chal", pub_pem)
        repo.approve("no-chal")
        with pytest.raises(ValueError, match="No pending challenge"):
            repo.verify_challenge("no-chal", b"fake-sig")


# ---------------------------------------------------------------------------
# CRUD queries
# ---------------------------------------------------------------------------


class TestQueries:
    def test_get_existing(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("q-agent", pub_pem)
        assert repo.get("q-agent") is not None

    def test_get_missing_returns_none(self, repo):
        assert repo.get("nope") is None

    def test_list_all(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("la-1", pub_pem)
        _, pub_pem2 = _generate_keypair()
        repo.enrol("la-2", pub_pem2)
        assert len(repo.list_all()) == 2

    def test_list_approved(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("app-1", pub_pem)
        repo.approve("app-1")
        _, pub_pem2 = _generate_keypair()
        repo.enrol("pend-1", pub_pem2)
        approved = repo.list_approved()
        assert len(approved) == 1
        assert approved[0].agent_id == "app-1"

    def test_delete(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("del-1", pub_pem)
        assert repo.delete("del-1") is True
        assert repo.get("del-1") is None

    def test_delete_nonexistent(self, repo):
        assert repo.delete("phantom") is False


# ---------------------------------------------------------------------------
# Capability update
# ---------------------------------------------------------------------------


class TestCapabilityUpdate:
    def test_update_capabilities(self, repo):
        _, pub_pem = _generate_keypair()
        repo.enrol("cap-upd", pub_pem, capabilities=[{"capability_id": "old"}])
        updated = repo.update_capabilities(
            "cap-upd",
            capabilities=[{"capability_id": "new-cap", "description": "Fresh"}],
            version="2.0.0",
        )
        assert updated.capabilities_json == [{"capability_id": "new-cap", "description": "Fresh"}]
        assert updated.version == "2.0.0"

    def test_update_nonexistent_raises(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.update_capabilities("ghost", capabilities=[])


# ---------------------------------------------------------------------------
# Registry integration (ephemeral vs persistent disconnect)
# ---------------------------------------------------------------------------


class TestRegistryModes:
    def test_ephemeral_removed_on_disconnect(self):
        reg = CapabilityRegistry()
        agent = AgentRegistration(agent_id="eph-1", mode="ephemeral", capabilities=[
            AgentCapability(capability_id="c1"),
        ])
        reg.register(agent)
        assert reg.is_online("eph-1")
        assert reg.count == 1

        reg.handle_disconnect("eph-1")
        assert reg.get("eph-1") is None
        assert reg.count == 0

    def test_persistent_stays_on_disconnect(self):
        reg = CapabilityRegistry()
        agent = AgentRegistration(agent_id="per-1", mode="persistent", capabilities=[
            AgentCapability(capability_id="c1"),
        ])
        reg.register(agent)
        assert reg.is_online("per-1")

        reg.handle_disconnect("per-1")
        # Still in registry but offline
        assert reg.get("per-1") is not None
        assert not reg.is_online("per-1")
        assert reg.count == 1

    def test_mark_online_after_reconnect(self):
        reg = CapabilityRegistry()
        agent = AgentRegistration(agent_id="per-2", mode="persistent", capabilities=[])
        reg.register(agent)
        reg.mark_offline("per-2")
        assert not reg.is_online("per-2")
        reg.mark_online("per-2")
        assert reg.is_online("per-2")

    def test_handle_disconnect_unknown_is_noop(self):
        reg = CapabilityRegistry()
        reg.handle_disconnect("unknown-id")  # should not raise


# ---------------------------------------------------------------------------
# init_db idempotent
# ---------------------------------------------------------------------------


class TestInitDb:
    def test_init_db_creates_tables(self, tmp_path):
        """init_db can be called multiple times without error."""
        url = f"sqlite:///{tmp_path / 'test.db'}"
        engine = create_engine(url, echo=False, future=True)
        init_db(engine)
        init_db(engine)  # second call is a no-op
        # Tables should exist
        assert "persistent_agents" in Base.metadata.tables
