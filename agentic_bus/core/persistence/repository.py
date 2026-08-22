"""Repository for persistent agent CRUD and challenge–response auth.

Challenge flow
--------------
1. Agent sends ``enrol`` with its Ed25519 public key + metadata.
2. Repository stores it with status ``pending``.
3. Admin approves (or ``AGBUS_AGENT_AUTO_APPROVE=true``).
4. On connect the agent calls ``request_challenge(agent_id)`` →
   receives a random nonce.
5. Agent signs the nonce with its private key and sends the signature.
6. ``verify_challenge()`` checks the signature with the stored public key.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from agentic_bus.core.persistence.database import get_session
from agentic_bus.core.persistence.models import AgentStatus, PersistentAgent

logger = logging.getLogger(__name__)


class AgentRepository:
    """CRUD + challenge auth for persistent agents."""

    def __init__(self) -> None:
        # In-flight challenges: agent_id -> nonce bytes
        self._challenges: dict[str, bytes] = {}

    # ------------------------------------------------------------------
    # Enrolment
    # ------------------------------------------------------------------

    def enrol(
        self,
        agent_id: str,
        public_key_pem: str,
        semantic_description: str = "",
        version: str = "0.1.0",
        capabilities: list[dict[str, Any]] | None = None,
        required_scopes: list[str] | None = None,
        supported_domains: list[str] | None = None,
    ) -> PersistentAgent:
        """Register a new persistent agent (sign-up).

        Returns the stored record.  Status will be ``pending`` unless
        ``AGBUS_AGENT_AUTO_APPROVE=true``.
        """
        # Validate the public key is parseable
        self._load_public_key(public_key_pem)

        auto_approve = os.getenv("AGBUS_AGENT_AUTO_APPROVE", "false").lower() in (
            "true",
            "1",
            "yes",
        )

        now = datetime.now(timezone.utc)
        status = AgentStatus.APPROVED if auto_approve else AgentStatus.PENDING

        agent = PersistentAgent(
            agent_id=agent_id,
            public_key_pem=public_key_pem,
            status=status,
            semantic_description=semantic_description,
            version=version,
            capabilities_json=capabilities or [],
            required_scopes_json=required_scopes or [],
            supported_domains_json=supported_domains or [],
            enrolled_at=now,
            approved_at=now if auto_approve else None,
            approved_by="auto" if auto_approve else None,
        )

        with get_session() as session:
            existing = session.get(PersistentAgent, agent_id)
            if existing is not None:
                raise ValueError(f"Agent {agent_id!r} is already enrolled")
            session.add(agent)
            session.commit()
            session.refresh(agent)

        logger.info(
            "Agent %s enrolled (status=%s, auto_approve=%s)",
            agent_id,
            status.value,
            auto_approve,
        )
        return agent

    # ------------------------------------------------------------------
    # Admin approval
    # ------------------------------------------------------------------

    def approve(self, agent_id: str, approved_by: str = "admin") -> PersistentAgent:
        """Approve a pending agent enrolment."""
        with get_session() as session:
            agent = session.get(PersistentAgent, agent_id)
            if agent is None:
                raise ValueError(f"Agent {agent_id!r} not found")
            if agent.status != AgentStatus.PENDING:
                raise ValueError(
                    f"Agent {agent_id!r} is not pending (status={agent.status.value})"
                )
            agent.status = AgentStatus.APPROVED
            agent.approved_at = datetime.now(timezone.utc)
            agent.approved_by = approved_by
            session.commit()
            session.refresh(agent)
        logger.info("Agent %s approved by %s", agent_id, approved_by)
        return agent

    def reject(self, agent_id: str) -> PersistentAgent:
        """Reject a pending agent enrolment."""
        with get_session() as session:
            agent = session.get(PersistentAgent, agent_id)
            if agent is None:
                raise ValueError(f"Agent {agent_id!r} not found")
            agent.status = AgentStatus.REJECTED
            session.commit()
            session.refresh(agent)
        logger.info("Agent %s rejected", agent_id)
        return agent

    def revoke(self, agent_id: str) -> PersistentAgent:
        """Revoke a previously-approved agent."""
        with get_session() as session:
            agent = session.get(PersistentAgent, agent_id)
            if agent is None:
                raise ValueError(f"Agent {agent_id!r} not found")
            agent.status = AgentStatus.REVOKED
            session.commit()
            session.refresh(agent)
        logger.info("Agent %s revoked", agent_id)
        return agent

    # ------------------------------------------------------------------
    # Challenge–response authentication
    # ------------------------------------------------------------------

    def request_challenge(self, agent_id: str) -> bytes:
        """Generate a random nonce for the agent to sign.

        Returns the raw nonce bytes.
        """
        agent = self.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id!r} not found")
        if agent.status != AgentStatus.APPROVED:
            raise PermissionError(
                f"Agent {agent_id!r} is not approved (status={agent.status.value})"
            )

        nonce = secrets.token_bytes(32)
        self._challenges[agent_id] = nonce
        return nonce

    def verify_challenge(self, agent_id: str, signature: bytes) -> bool:
        """Verify the agent's Ed25519 signature over the nonce.

        Returns ``True`` on success and updates ``last_connected_at``.
        """
        nonce = self._challenges.pop(agent_id, None)
        if nonce is None:
            raise ValueError(f"No pending challenge for agent {agent_id!r}")

        agent = self.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id!r} not found")

        pub_key = self._load_public_key(agent.public_key_pem)
        try:
            pub_key.verify(signature, nonce)
        except Exception:
            logger.warning("Challenge verification failed for agent %s", agent_id)
            return False

        # Update last_connected_at
        with get_session() as session:
            db_agent = session.get(PersistentAgent, agent_id)
            if db_agent:
                db_agent.last_connected_at = datetime.now(timezone.utc)
                session.commit()

        logger.info("Agent %s authenticated via challenge", agent_id)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def bind_subject(self, agent_id: str, subject: str) -> bool:
        """Record the OIDC subject entitled to register as this agent.

        Only ever fills an empty binding. Changing one is an administrative
        act; letting a connection rebind an id it just authenticated against
        would make the binding self-issued and therefore worthless.

        Returns ``True`` if the binding was written.
        """
        if not subject:
            return False
        with get_session() as session:
            agent = session.get(PersistentAgent, agent_id)
            if agent is None or agent.oidc_subject:
                return False
            agent.oidc_subject = subject
            session.commit()
        logger.info("Agent %s bound to subject %s", agent_id, subject)
        return True

    def get(self, agent_id: str) -> PersistentAgent | None:
        with get_session() as session:
            return session.get(PersistentAgent, agent_id)

    def list_all(self, status: AgentStatus | None = None) -> list[PersistentAgent]:
        with get_session() as session:
            q = session.query(PersistentAgent)
            if status is not None:
                q = q.filter(PersistentAgent.status == status)
            return list(q.all())

    def list_approved(self) -> list[PersistentAgent]:
        return self.list_all(status=AgentStatus.APPROVED)

    # ------------------------------------------------------------------
    # Performance stats
    # ------------------------------------------------------------------

    def record_execution(
        self,
        agent_id: str,
        quality_score: float,
        latency_ms: float,
    ) -> None:
        """Update a persistent agent's running performance statistics.

        Uses an incremental running-average::

            n = total_executions + 1
            mean_latency = mean_latency + (latency - mean_latency) / n
            current_score = current_score + (score - current_score) / n
        """
        with get_session() as session:
            agent = session.get(PersistentAgent, agent_id)
            if agent is None:
                logger.debug(
                    "record_execution: persistent agent %r not found — skipping",
                    agent_id,
                )
                return

            n = agent.total_executions + 1
            agent.mean_latency_ms = agent.mean_latency_ms + (latency_ms - agent.mean_latency_ms) / n
            agent.current_score = agent.current_score + (quality_score - agent.current_score) / n
            agent.total_executions = n
            agent.last_execution_at = datetime.now(timezone.utc)

            session.commit()

        logger.debug(
            "Persistent agent %r stats updated: score=%.2f, latency=%.1fms, n=%d",
            agent_id,
            agent.current_score,
            agent.mean_latency_ms,
            n,
        )

    def delete(self, agent_id: str) -> bool:
        """Permanently remove an agent record."""
        with get_session() as session:
            agent = session.get(PersistentAgent, agent_id)
            if agent is None:
                return False
            session.delete(agent)
            session.commit()
        logger.info("Agent %s deleted", agent_id)
        return True

    # ------------------------------------------------------------------
    # Update capabilities (agent hot-reload)
    # ------------------------------------------------------------------

    def update_capabilities(
        self,
        agent_id: str,
        capabilities: list[dict[str, Any]],
        required_scopes: list[str] | None = None,
        supported_domains: list[str] | None = None,
        version: str | None = None,
    ) -> PersistentAgent:
        """Update the stored capabilities for a persistent agent."""
        with get_session() as session:
            agent = session.get(PersistentAgent, agent_id)
            if agent is None:
                raise ValueError(f"Agent {agent_id!r} not found")
            agent.capabilities_json = capabilities
            if required_scopes is not None:
                agent.required_scopes_json = required_scopes
            if supported_domains is not None:
                agent.supported_domains_json = supported_domains
            if version is not None:
                agent.version = version
            session.commit()
            session.refresh(agent)
        return agent

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_public_key(pem: str) -> Ed25519PublicKey:
        """Parse a PEM-encoded Ed25519 public key."""
        key = load_pem_public_key(pem.encode() if isinstance(pem, str) else pem)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Only Ed25519 public keys are supported")
        return key
