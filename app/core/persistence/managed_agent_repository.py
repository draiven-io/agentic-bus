"""Repository for managed agent CRUD.

Managed agents are created and administered from within the Agentic Bus
(via CLI or admin API) using the CrewAI Role-Goal-Backstory framework.
They differ from *persistent agents* which are externally-built and merely
register on the bus.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.persistence.database import get_session
from app.core.persistence.models import (
    ManagedAgent,
    ManagedAgentCapability,
    ManagedAgentStatus,
)

logger = logging.getLogger(__name__)


class ManagedAgentNotFoundError(Exception):
    """Raised when a referenced managed agent does not exist."""


class ManagedAgentRepository:
    """CRUD operations for managed agents and their capabilities."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        agent_id: str,
        name: str,
        role: str,
        goal: str,
        backstory: str,
        *,
        llm_config_name: str | None = None,
        verbose: bool = False,
        max_iter: int = 25,
        max_rpm: int | None = None,
        memory: bool = True,
        tools: list[str] | None = None,
        capabilities: list[dict[str, Any]] | None = None,
        status: ManagedAgentStatus = ManagedAgentStatus.DRAFT,
        created_by: str = "admin",
    ) -> ManagedAgent:
        """Create a new managed agent.

        Parameters
        ----------
        agent_id:
            Unique slug identifier (e.g. ``"market-researcher-01"``).
        name:
            Human-friendly display name.
        role:
            CrewAI role – the agent's specialised function.
        goal:
            CrewAI goal – the agent's purpose and motivation.
        backstory:
            CrewAI backstory – experience and perspective.
        llm_config_name:
            Optional name of a stored ``LLMConfig`` to use.  ``None``
            means the bus-wide default.
        tools:
            List of CrewAI tool class names to bind.
        capabilities:
            List of capability dicts.  Each dict must contain at least
            ``capability_id`` and ``description``.
        """
        now = datetime.now(timezone.utc)

        with get_session() as session:
            # Uniqueness check
            existing = (
                session.query(ManagedAgent)
                .filter(ManagedAgent.agent_id == agent_id)
                .first()
            )
            if existing is not None:
                raise ValueError(f"Managed agent {agent_id!r} already exists")

            agent = ManagedAgent(
                agent_id=agent_id,
                name=name,
                role=role,
                goal=goal,
                backstory=backstory,
                llm_config_name=llm_config_name,
                verbose=verbose,
                max_iter=max_iter,
                max_rpm=max_rpm,
                memory=memory,
                tools_json=tools or [],
                status=status,
                created_at=now,
                updated_at=now,
                created_by=created_by,
            )
            session.add(agent)

            # Add capabilities
            for cap_dict in (capabilities or []):
                cap = ManagedAgentCapability(
                    agent_id=agent_id,
                    capability_id=cap_dict["capability_id"],
                    description=cap_dict.get("description", ""),
                    expected_output=cap_dict.get("expected_output", ""),
                    required_scopes_json=cap_dict.get("required_scopes", []),
                    supported_data_domains_json=cap_dict.get("supported_data_domains", []),
                    operational_constraints_json=cap_dict.get("operational_constraints", {}),
                    expected_artifacts_json=cap_dict.get("expected_artifacts", []),
                    estimated_cost=cap_dict.get("estimated_cost", 0.0),
                    estimated_latency=cap_dict.get("estimated_latency", 0.0),
                    output_schema_json=cap_dict.get("output_schema", {}),
                )
                session.add(cap)

            session.commit()
            session.refresh(agent)

        logger.info(
            "Managed agent %r created (status=%s, tools=%d, capabilities=%d)",
            agent_id,
            status.value,
            len(tools or []),
            len(capabilities or []),
        )
        return agent

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, agent_id: str) -> ManagedAgent | None:
        """Return a managed agent by its ID, or ``None``."""
        with get_session() as session:
            return (
                session.query(ManagedAgent)
                .filter(ManagedAgent.agent_id == agent_id)
                .first()
            )

    def get_or_raise(self, agent_id: str) -> ManagedAgent:
        """Return a managed agent or raise ``ManagedAgentNotFoundError``."""
        agent = self.get(agent_id)
        if agent is None:
            raise ManagedAgentNotFoundError(
                f"Managed agent {agent_id!r} not found"
            )
        return agent

    def list_all(
        self,
        status: ManagedAgentStatus | None = None,
    ) -> list[ManagedAgent]:
        """Return all managed agents, optionally filtered by status."""
        with get_session() as session:
            q = session.query(ManagedAgent).order_by(ManagedAgent.agent_id)
            if status is not None:
                q = q.filter(ManagedAgent.status == status)
            return list(q.all())

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        role: str | None = None,
        goal: str | None = None,
        backstory: str | None = None,
        llm_config_name: str | None = ...,  # type: ignore[assignment]
        verbose: bool | None = None,
        max_iter: int | None = None,
        max_rpm: int | None = ...,  # type: ignore[assignment]
        memory: bool | None = None,
        tools: list[str] | None = None,
    ) -> ManagedAgent:
        """Update scalar fields on a managed agent.

        Only fields explicitly passed (not ``None``) are updated.
        For the nullable fields ``llm_config_name`` and ``max_rpm``,
        the sentinel ``...`` means "do not change" while ``None``
        means "clear the value".
        """
        with get_session() as session:
            agent = (
                session.query(ManagedAgent)
                .filter(ManagedAgent.agent_id == agent_id)
                .first()
            )
            if agent is None:
                raise ManagedAgentNotFoundError(
                    f"Managed agent {agent_id!r} not found"
                )

            if name is not None:
                agent.name = name
            if role is not None:
                agent.role = role
            if goal is not None:
                agent.goal = goal
            if backstory is not None:
                agent.backstory = backstory
            if llm_config_name is not ...:
                agent.llm_config_name = llm_config_name
            if verbose is not None:
                agent.verbose = verbose
            if max_iter is not None:
                agent.max_iter = max_iter
            if max_rpm is not ...:
                agent.max_rpm = max_rpm
            if memory is not None:
                agent.memory = memory
            if tools is not None:
                agent.tools_json = tools

            agent.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(agent)

        logger.info("Managed agent %r updated", agent_id)
        return agent

    def set_status(
        self,
        agent_id: str,
        status: ManagedAgentStatus,
    ) -> ManagedAgent:
        """Change the lifecycle status of a managed agent."""
        with get_session() as session:
            agent = (
                session.query(ManagedAgent)
                .filter(ManagedAgent.agent_id == agent_id)
                .first()
            )
            if agent is None:
                raise ManagedAgentNotFoundError(
                    f"Managed agent {agent_id!r} not found"
                )
            agent.status = status
            agent.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(agent)

        logger.info("Managed agent %r status → %s", agent_id, status.value)
        return agent

    # ------------------------------------------------------------------
    # Capability management
    # ------------------------------------------------------------------

    def add_capability(
        self,
        agent_id: str,
        capability_id: str,
        description: str = "",
        expected_output: str = "",
        *,
        required_scopes: list[str] | None = None,
        supported_data_domains: list[str] | None = None,
        operational_constraints: dict[str, Any] | None = None,
        expected_artifacts: list[str] | None = None,
        estimated_cost: float = 0.0,
        estimated_latency: float = 0.0,
        output_schema: dict[str, Any] | None = None,
    ) -> ManagedAgentCapability:
        """Add a capability to a managed agent."""
        with get_session() as session:
            agent = (
                session.query(ManagedAgent)
                .filter(ManagedAgent.agent_id == agent_id)
                .first()
            )
            if agent is None:
                raise ManagedAgentNotFoundError(
                    f"Managed agent {agent_id!r} not found"
                )

            cap = ManagedAgentCapability(
                agent_id=agent_id,
                capability_id=capability_id,
                description=description,
                expected_output=expected_output,
                required_scopes_json=required_scopes or [],
                supported_data_domains_json=supported_data_domains or [],
                operational_constraints_json=operational_constraints or {},
                expected_artifacts_json=expected_artifacts or [],
                estimated_cost=estimated_cost,
                estimated_latency=estimated_latency,
                output_schema_json=output_schema or {},
            )
            session.add(cap)
            session.commit()
            session.refresh(cap)

        logger.info(
            "Capability %r added to managed agent %r",
            capability_id,
            agent_id,
        )
        return cap

    def remove_capability(self, agent_id: str, capability_id: str) -> bool:
        """Remove a capability from a managed agent.  Returns ``True`` if found."""
        with get_session() as session:
            cap = (
                session.query(ManagedAgentCapability)
                .filter(
                    ManagedAgentCapability.agent_id == agent_id,
                    ManagedAgentCapability.capability_id == capability_id,
                )
                .first()
            )
            if cap is None:
                return False
            session.delete(cap)
            session.commit()

        logger.info(
            "Capability %r removed from managed agent %r",
            capability_id,
            agent_id,
        )
        return True

    def list_capabilities(self, agent_id: str) -> list[ManagedAgentCapability]:
        """Return all capabilities for a managed agent."""
        with get_session() as session:
            return list(
                session.query(ManagedAgentCapability)
                .filter(ManagedAgentCapability.agent_id == agent_id)
                .all()
            )

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, agent_id: str) -> bool:
        """Permanently remove a managed agent and its capabilities."""
        with get_session() as session:
            agent = (
                session.query(ManagedAgent)
                .filter(ManagedAgent.agent_id == agent_id)
                .first()
            )
            if agent is None:
                return False
            session.delete(agent)
            session.commit()

        logger.info("Managed agent %r deleted", agent_id)
        return True
