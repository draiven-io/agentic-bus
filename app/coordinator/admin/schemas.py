"""Pydantic response schemas for the Admin REST API.

These DTOs decouple the API contract from the SQLAlchemy ORM models and
the in-memory registry structures.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Capability DTOs
# ---------------------------------------------------------------------------


class AgentCapabilityDTO(BaseModel):
    capability_id: str
    description: str = ""
    estimated_cost: float | None = None
    estimated_latency: float | None = None


class OutputFieldDTO(BaseModel):
    """A single field in a capability's structured output definition."""
    name: str
    type: str = "str"
    description: str = ""


class ManagedAgentCapabilityDTO(BaseModel):
    id: int
    capability_id: str
    description: str = ""
    expected_output: str = ""
    required_scopes: list[str] = Field(default_factory=list)
    supported_data_domains: list[str] = Field(default_factory=list)
    estimated_cost: float = 0.0
    estimated_latency: float = 0.0
    output_fields: list[OutputFieldDTO] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent DTOs
# ---------------------------------------------------------------------------


class PersistentAgentDTO(BaseModel):
    agent_id: str
    public_key_pem: str
    status: str
    semantic_description: str
    version: str
    capabilities: list[AgentCapabilityDTO] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    supported_domains: list[str] = Field(default_factory=list)
    enrolled_at: str
    approved_at: str | None = None
    approved_by: str | None = None
    last_connected_at: str | None = None


class ManagedAgentDTO(BaseModel):
    id: int
    agent_id: str
    name: str
    role: str
    goal: str
    backstory: str
    llm_config_name: str | None = None
    verbose: bool
    max_iter: int
    max_rpm: int | None = None
    memory: bool
    tools: list[str] = Field(default_factory=list)
    tool_config: dict[str, dict[str, Any]] = Field(default_factory=dict)
    status: str
    capabilities: list[ManagedAgentCapabilityDTO] = Field(default_factory=list)
    created_at: str
    updated_at: str
    created_by: str


class OutputFieldCreateRequest(BaseModel):
    """Field definition for a capability's structured output.

    Supported types: ``str``, ``int``, ``float``, ``bool``, ``list``, ``dict``.
    """
    name: str
    type: str = "str"
    description: str = ""


class ManagedAgentCapabilityCreateRequest(BaseModel):
    capability_id: str
    description: str = ""
    expected_output: str = ""
    supported_data_domains: list[str] = Field(default_factory=list)
    estimated_cost: float = 0.0
    estimated_latency: float = 0.0
    output_fields: list[OutputFieldCreateRequest] = Field(default_factory=list)


class ManagedAgentCreateRequest(BaseModel):
    agent_id: str
    name: str
    role: str
    goal: str
    backstory: str
    llm_config_name: str | None = None
    verbose: bool = False
    max_iter: int = 25
    max_rpm: int | None = None
    memory: bool = True
    tools: list[str] = Field(default_factory=list)
    tool_config: dict[str, dict[str, Any]] = Field(default_factory=dict)
    capabilities: list[ManagedAgentCapabilityCreateRequest] = Field(default_factory=list)
    activate: bool = False


class EphemeralAgentDTO(BaseModel):
    agent_id: str
    version: str
    status: str = "online"
    semantic_description: str = ""
    capabilities: list[AgentCapabilityDTO] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    supported_domains: list[str] = Field(default_factory=list)
    operational_constraints: dict[str, Any] = Field(default_factory=dict)
    registered_at: str = ""


# ---------------------------------------------------------------------------
# Session DTO
# ---------------------------------------------------------------------------


class SessionDTO(BaseModel):
    session_id: str
    phase: str
    requester_id: str
    discovered_agents: list[str] = Field(default_factory=list)
    accepted_offers: list[str] = Field(default_factory=list)
    created_at: str
    dissolved_at: str | None = None


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------


class AuditLogEntryDTO(BaseModel):
    id: str
    timestamp: str
    action: str
    actor: str
    target: str
    target_type: str  # agent | session | llm_config | system
    details: str = ""
    severity: str = "info"  # info | warning | error | critical


# ---------------------------------------------------------------------------
# LLM Configuration
# ---------------------------------------------------------------------------


class LLMConfigDTO(BaseModel):
    id: int
    name: str
    provider: str
    model: str
    temperature: float
    is_current: bool
    extra_config: dict[str, Any] | None = None
    created_at: str
    updated_at: str
    created_by: str


class LLMConfigCreateRequest(BaseModel):
    name: str
    provider: str
    model: str
    temperature: float = 0.0
    api_key: str | None = None
    extra_config: dict[str, Any] | None = None
    is_current: bool = False


class LLMConfigUpdateRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    api_key: str | None = None
    extra_config: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------------------------------


class DashboardStatsDTO(BaseModel):
    total_agents: int
    approved_agents: int
    pending_agents: int
    managed_agents: int
    ephemeral_agents: int
    active_sessions: int
    total_sessions_today: int
    llm_provider: str
    llm_model: str


# ---------------------------------------------------------------------------
# Coordinator Settings
# ---------------------------------------------------------------------------


class CoordinatorSettingsDTO(BaseModel):
    host: str
    port: int
    oidc_enabled: bool
    oidc_issuer: str
    oidc_audience: str
    auto_approve: bool
    database_url: str


# ---------------------------------------------------------------------------
# Tenant DTOs
# ---------------------------------------------------------------------------


class TenantDTO(BaseModel):
    id: int
    slug: str
    name: str
    enabled: bool
    created_at: str
    updated_at: str
    user_count: int = 0
    agent_count: int = 0


class TenantCreateRequest(BaseModel):
    slug: str
    name: str
    enabled: bool = True


class TenantUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# User DTOs
# ---------------------------------------------------------------------------


class UserDTO(BaseModel):
    id: int
    subject: str
    email: str
    display_name: str
    role: str
    enabled: bool
    created_at: str
    updated_at: str
    created_by: str
    tenant_ids: list[int] = Field(default_factory=list)
    tenant_slugs: list[str] = Field(default_factory=list)


class UserCreateRequest(BaseModel):
    subject: str
    email: str = ""
    display_name: str = ""
    role: str = "user"
    enabled: bool = True
    tenant_ids: list[int] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None
    role: str | None = None
    enabled: bool | None = None
    tenant_ids: list[int] | None = None


# ---------------------------------------------------------------------------
# Identity / "who am I" DTO
# ---------------------------------------------------------------------------


class CurrentUserDTO(BaseModel):
    """Returned by ``GET /api/admin/me`` so the UI knows who is logged in
    and which tenants / role it should use for scoping."""

    subject: str
    email: str = ""
    display_name: str = ""
    role: str  # "admin" | "user"
    is_admin: bool
    tenant_ids: list[int] = Field(default_factory=list)
    tenant_slugs: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# IBAC Rule DTOs
# ---------------------------------------------------------------------------


class IBACRuleDTO(BaseModel):
    """Read model returned by the API."""
    id: int
    rule_id: str
    name: str
    description: str = ""
    enabled: bool
    priority: int
    action: str  # "deny" | "allow"
    evaluation_points: list[str] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    created_by: str


class IBACRuleCreateRequest(BaseModel):
    """Payload for creating a new IBAC rule."""
    rule_id: str
    name: str
    description: str = ""
    enabled: bool = True
    priority: int = 100
    action: str = "deny"
    evaluation_points: list[str] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)


class IBACRuleUpdateRequest(BaseModel):
    """Payload for updating an existing IBAC rule.  Only provided fields are changed."""
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    action: str | None = None
    evaluation_points: list[str] | None = None
    conditions: dict[str, Any] | None = None
