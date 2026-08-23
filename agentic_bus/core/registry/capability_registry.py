"""Dynamic Capability Registry (§7 of AGENTS.md).

Agents register themselves dynamically with semantic capability descriptors.
The registry is in-memory and hot-reloadable – no static capability lists.

Per §4.1.2 of the Liquid Interfaces paper, the registry feeds into semantic
capability matching:
given an intention Φ and context C_t, the coordination layer discovers
which agents are semantically compatible with the intended objective.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class AgentCapability(BaseModel):
    """A single capability exposed by an agent.

    All information needed to generate an ``OfferPayload`` is declared here,
    so agents don't need to implement offer generation logic individually.

    Pass ``output_model`` (a Pydantic ``BaseModel`` subclass) to declare the
    structured output format.  The JSON Schema is derived automatically and
    stored in ``output_schema`` — agents never need to build it by hand.
    """

    model_config = {"arbitrary_types_allowed": True}

    capability_id: str
    description: str = ""
    required_scopes: list[str] = Field(default_factory=list)
    supported_data_domains: list[str] = Field(default_factory=list)
    operational_constraints: dict[str, Any] = Field(default_factory=dict)
    expected_artifacts: list[str] = Field(
        default_factory=list,
        description="Names of the artifacts this capability will produce.",
    )
    estimated_cost: float = Field(
        default=0.0,
        description="Estimated monetary cost per invocation.",
    )
    estimated_latency: float = Field(
        default=0.0,
        description="Estimated latency in seconds.",
    )
    output_model: type[BaseModel] | None = Field(
        default=None,
        exclude=True,
        description=(
            "Pydantic model class describing the structured output. "
            "When provided, ``output_schema`` is derived automatically."
        ),
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "JSON Schema describing the structured output this capability "
            "produces.  Auto-populated from ``output_model`` when provided."
        ),
    )

    @model_validator(mode="after")
    def _derive_output_schema(self) -> "AgentCapability":
        """Auto-populate ``output_schema`` from ``output_model`` if given."""
        if self.output_model is not None and not self.output_schema:
            self.output_schema = self.output_model.model_json_schema()
        return self


class AgentRegistration(BaseModel):
    """Full registration record for a provider agent."""

    agent_id: str
    version: str = "0.1.0"
    mode: str = Field(
        default="ephemeral",
        description="Registration mode: 'ephemeral' or 'persistent'.",
    )
    capabilities: list[AgentCapability] = Field(default_factory=list)
    semantic_description: str = ""
    required_scopes: list[str] = Field(default_factory=list)
    supported_data_domains: list[str] = Field(default_factory=list)
    operational_constraints: dict[str, Any] = Field(default_factory=dict)
    registered_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class CapabilityRegistry:
    """In-memory, hot-reloadable agent capability registry.

    Combines two sources:
    - **Ephemeral agents**: in-memory only, removed on disconnect.
    - **Persistent agents**: backed by the database; their capabilities are
      loaded into memory when they connect and remain discoverable even when
      they are offline (marked as ``offline``).

    All mutations are O(1) dict operations.  The registry is designed to be
    queried by the semantic adjudicator during the discovery phase.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentRegistration] = {}
        # Track which agents are currently connected (for ephemeral cleanup)
        self._online: set[str] = set()

    # -- mutations -----------------------------------------------------------

    def register(self, registration: AgentRegistration) -> None:
        """Register or update an agent's capabilities."""
        self._agents[registration.agent_id] = registration
        self._online.add(registration.agent_id)
        logger.info(
            "Agent registered: %s (v%s, mode=%s) with %d capabilities",
            registration.agent_id,
            registration.version,
            registration.mode,
            len(registration.capabilities),
        )

    def deregister(self, agent_id: str) -> AgentRegistration | None:
        """Remove an agent from the registry."""
        self._online.discard(agent_id)
        reg = self._agents.pop(agent_id, None)
        if reg:
            logger.info("Agent deregistered: %s", agent_id)
        return reg

    def mark_offline(self, agent_id: str) -> None:
        """Mark an agent as disconnected without removing it from the registry.

        Used for persistent agents that should remain discoverable.
        """
        self._online.discard(agent_id)

    def mark_online(self, agent_id: str) -> None:
        """Mark a previously registered agent as connected again."""
        if agent_id in self._agents:
            self._online.add(agent_id)

    def handle_disconnect(self, agent_id: str) -> None:
        """Handle agent disconnect: ephemeral agents are removed,
        persistent agents are marked offline."""
        reg = self._agents.get(agent_id)
        if reg is None:
            return
        if reg.mode == "ephemeral":
            self.deregister(agent_id)
            logger.info("Ephemeral agent %s removed on disconnect", agent_id)
        else:
            self.mark_offline(agent_id)
            logger.info("Persistent agent %s marked offline", agent_id)

    def is_online(self, agent_id: str) -> bool:
        return agent_id in self._online

    # -- queries -------------------------------------------------------------

    def get(self, agent_id: str) -> AgentRegistration | None:
        return self._agents.get(agent_id)

    def all_agents(self) -> list[AgentRegistration]:
        return list(self._agents.values())

    def find_by_domain(self, domain: str) -> list[AgentRegistration]:
        """Return agents that declare support for a given data domain."""
        return [
            a for a in self._agents.values()
            if domain in a.supported_data_domains
        ]

    def capability_summaries(
        self, only: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return a lightweight list of agent+capability descriptions.

        This is the input fed to the LLM-based semantic adjudicator, which
        makes *only* the security-relevant parameter rather than a
        convenience: a capability description is not innocuous — "query ACME
        Corp's payroll database" names a customer — and once it is in a prompt
        it has been disclosed, whatever the model then chooses. Filtering the
        candidates afterwards would be too late.

        ``None`` means no restriction, which is the single-tenant case.
        """
        allowed = None if only is None else set(only)
        summaries: list[dict[str, Any]] = []
        for agent in self._agents.values():
            if allowed is not None and agent.agent_id not in allowed:
                continue
            for cap in agent.capabilities:
                summaries.append(
                    {
                        "agent_id": agent.agent_id,
                        "agent_description": agent.semantic_description,
                        "capability_id": cap.capability_id,
                        "capability_description": cap.description,
                        "required_scopes": cap.required_scopes,
                        "data_domains": cap.supported_data_domains,
                        "constraints": cap.operational_constraints,
                        "output_schema": cap.output_schema,
                    }
                )
        return summaries

    @property
    def count(self) -> int:
        return len(self._agents)
