"""Admin service – authenticated administrative operations.

All mutating operations require a verified ``OIDCIdentity`` that satisfies
the ``AdminPolicy``.  This keeps the ``AgentRepository`` free from auth
concerns while guaranteeing that only authorised subjects can approve,
reject, or revoke agents.

Also provides LLM configuration management – admins can add, activate,
update, and remove LLM provider configurations.
"""

from __future__ import annotations

import logging
from typing import Any

from agentic_bus.core.auth.admin import AdminPolicy, require_admin
from agentic_bus.core.auth.oidc import OIDCIdentity
from agentic_bus.core.persistence.models import AgentStatus, LLMConfig, PersistentAgent
from agentic_bus.core.persistence.repository import AgentRepository
from agentic_bus.core.persistence.llm_repository import LLMConfigRepository
from agentic_bus.core.persistence.ibac_repository import IBACRuleRepository

logger = logging.getLogger(__name__)


class AdminService:
    """Thin authorisation wrapper around ``AgentRepository`` and
    ``LLMConfigRepository``.

    Every method that mutates state takes an ``OIDCIdentity``
    and verifies it against the ``AdminPolicy`` before proceeding.
    Read-only operations are unrestricted.
    """

    def __init__(
        self,
        repo: AgentRepository | None = None,
        policy: AdminPolicy | None = None,
        llm_repo: LLMConfigRepository | None = None,
        ibac_repo: IBACRuleRepository | None = None,
    ) -> None:
        self.repo = repo or AgentRepository()
        self.policy = policy or AdminPolicy.from_env()
        self.llm_repo = llm_repo or LLMConfigRepository()
        self.ibac_repo = ibac_repo or IBACRuleRepository()

    # ------------------------------------------------------------------
    # Admin-gated mutations
    # ------------------------------------------------------------------

    def approve_agent(
        self,
        agent_id: str,
        identity: OIDCIdentity,
    ) -> PersistentAgent:
        """Approve a pending agent enrolment.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        agent = self.repo.approve(agent_id, approved_by=identity.subject)
        logger.info(
            "Agent %s approved by admin %s",
            agent_id,
            identity.subject,
        )
        return agent

    def reject_agent(
        self,
        agent_id: str,
        identity: OIDCIdentity,
    ) -> PersistentAgent:
        """Reject a pending agent enrolment.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        agent = self.repo.reject(agent_id)
        logger.info(
            "Agent %s rejected by admin %s",
            agent_id,
            identity.subject,
        )
        return agent

    def revoke_agent(
        self,
        agent_id: str,
        identity: OIDCIdentity,
    ) -> PersistentAgent:
        """Revoke a previously-approved agent.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        agent = self.repo.revoke(agent_id)
        logger.info(
            "Agent %s revoked by admin %s",
            agent_id,
            identity.subject,
        )
        return agent

    def delete_agent(
        self,
        agent_id: str,
        identity: OIDCIdentity,
    ) -> bool:
        """Permanently delete an agent record.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        deleted = self.repo.delete(agent_id)
        if deleted:
            logger.info(
                "Agent %s deleted by admin %s",
                agent_id,
                identity.subject,
            )
        return deleted

    # ------------------------------------------------------------------
    # Read-only (no admin check needed)
    # ------------------------------------------------------------------

    def list_agents(
        self,
        status: AgentStatus | None = None,
    ) -> list[PersistentAgent]:
        """List agents, optionally filtered by status."""
        if status is not None:
            return self.repo.list_all(status=status)
        return self.repo.list_all()

    def get_agent(self, agent_id: str) -> PersistentAgent | None:
        """Retrieve a single agent record."""
        return self.repo.get(agent_id)

    def list_pending(self) -> list[PersistentAgent]:
        """Convenience: list agents awaiting approval."""
        return self.repo.list_all(status=AgentStatus.PENDING)

    # ------------------------------------------------------------------
    # LLM configuration management (admin-gated)
    # ------------------------------------------------------------------

    def add_llm_config(
        self,
        name: str,
        provider: str,
        model: str,
        identity: OIDCIdentity,
        *,
        temperature: float = 0.0,
        api_key: str | None = None,
        extra_config: dict[str, Any] | None = None,
        is_current: bool = False,
    ) -> LLMConfig:
        """Add a new LLM configuration.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        config = self.llm_repo.add(
            name=name,
            provider=provider,
            model=model,
            temperature=temperature,
            api_key=api_key,
            extra_config=extra_config,
            is_current=is_current,
            created_by=identity.subject,
        )
        logger.info(
            "LLM config %r added by admin %s",
            name,
            identity.subject,
        )
        return config

    def activate_llm_config(
        self,
        name: str,
        identity: OIDCIdentity,
    ) -> LLMConfig:
        """Activate an LLM configuration (make it the current one).

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        config = self.llm_repo.activate(name)
        logger.info(
            "LLM config %r activated by admin %s",
            name,
            identity.subject,
        )
        return config

    def update_llm_config(
        self,
        name: str,
        identity: OIDCIdentity,
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        api_key: str | None = None,
        extra_config: dict[str, Any] | None = None,
    ) -> LLMConfig:
        """Update an existing LLM configuration.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        config = self.llm_repo.update(
            name,
            provider=provider,
            model=model,
            temperature=temperature,
            api_key=api_key,
            extra_config=extra_config,
        )
        logger.info(
            "LLM config %r updated by admin %s",
            name,
            identity.subject,
        )
        return config

    def delete_llm_config(
        self,
        name: str,
        identity: OIDCIdentity,
    ) -> bool:
        """Delete an LLM configuration.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        deleted = self.llm_repo.delete(name)
        if deleted:
            logger.info(
                "LLM config %r deleted by admin %s",
                name,
                identity.subject,
            )
        return deleted

    # Read-only LLM queries (no admin check needed)

    def list_llm_configs(self) -> list[LLMConfig]:
        """List all LLM configurations."""
        return self.llm_repo.list_all()

    def get_current_llm_config(self) -> LLMConfig | None:
        """Return the currently active LLM configuration, or ``None``."""
        return self.llm_repo.get_current_or_none()

    # ------------------------------------------------------------------
    # IBAC rule management (admin-gated)
    # ------------------------------------------------------------------

    def add_ibac_rule(
        self,
        rule_id: str,
        name: str,
        identity: OIDCIdentity,
        *,
        description: str = "",
        enabled: bool = True,
        priority: int = 100,
        action: str = "deny",
        evaluation_points: list[str] | None = None,
        conditions: dict[str, Any] | None = None,
    ) -> Any:
        """Create a new IBAC guardrail rule.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        rule = self.ibac_repo.add(
            rule_id=rule_id,
            name=name,
            description=description,
            enabled=enabled,
            priority=priority,
            action=action,
            evaluation_points=evaluation_points,
            conditions=conditions,
            created_by=identity.subject,
        )
        logger.info(
            "IBAC rule %r created by admin %s",
            rule_id,
            identity.subject,
        )
        return rule

    def update_ibac_rule(
        self,
        rule_id: str,
        identity: OIDCIdentity,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        priority: int | None = None,
        action: str | None = None,
        evaluation_points: list[str] | None = None,
        conditions: dict[str, Any] | None = None,
    ) -> Any:
        """Update an existing IBAC rule.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        rule = self.ibac_repo.update(
            rule_id,
            name=name,
            description=description,
            enabled=enabled,
            priority=priority,
            action=action,
            evaluation_points=evaluation_points,
            conditions=conditions,
        )
        logger.info(
            "IBAC rule %r updated by admin %s",
            rule_id,
            identity.subject,
        )
        return rule

    def delete_ibac_rule(
        self,
        rule_id: str,
        identity: OIDCIdentity,
    ) -> bool:
        """Delete an IBAC rule.

        Raises ``PermissionError`` if *identity* is not an admin.
        """
        require_admin(identity, self.policy)
        deleted = self.ibac_repo.delete(rule_id)
        if deleted:
            logger.info(
                "IBAC rule %r deleted by admin %s",
                rule_id,
                identity.subject,
            )
        return deleted

    # Read-only IBAC queries (no admin check needed)

    def list_ibac_rules(self) -> list[Any]:
        """List all IBAC rules ordered by priority."""
        return self.ibac_repo.list_all()

    def get_ibac_rule(self, rule_id: str) -> Any:
        """Retrieve a single IBAC rule."""
        return self.ibac_repo.get(rule_id)
