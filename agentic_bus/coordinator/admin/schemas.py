"""Pydantic response schemas for the Admin REST API.

These DTOs decouple the API contract from the SQLAlchemy ORM models and
the in-memory registry structures.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agentic_bus.core.protocol.envelope import LIP_PROTOCOL_VERSION


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
    # Performance statistics
    total_executions: int = 0
    current_score: float = 0.0
    mean_latency_ms: float = 0.0
    last_execution_at: str | None = None


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
    # Performance statistics
    total_executions: int = 0
    current_score: float = 0.0
    mean_latency_ms: float = 0.0
    last_execution_at: str | None = None
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
    mcp_servers: int = 0
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
    #: The LIP version this coordinator speaks, so a client can tell without
    #: inferring it from things not working.
    protocol_version: str = LIP_PROTOCOL_VERSION


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


# ---------------------------------------------------------------------------
# Session Archive DTOs
# ---------------------------------------------------------------------------


class SessionArchiveListDTO(BaseModel):
    """Lightweight summary for the history list view."""
    id: int
    session_id: str
    requester_id: str
    intent_text: str = ""
    intent_domain: str = ""
    outcome: str  # success | error | partial_failure | denied | rejected | cancelled
    outcome_summary: str = ""
    agent_count: int = 0
    step_count: int = 0
    created_at: str
    dissolved_at: str
    duration_seconds: float = 0.0


class SessionArchiveDetailDTO(BaseModel):
    """Full archive detail for the replay / inspection view."""
    id: int
    session_id: str
    requester_id: str
    requester_oidc_subject: str = ""
    intent_text: str = ""
    intent_domain: str = ""
    decomposition: dict[str, Any] = Field(default_factory=dict)
    outcome: str
    outcome_summary: str = ""
    discovered_agents: list[str] = Field(default_factory=list)
    accepted_agents: list[str] = Field(default_factory=list)
    agents: dict[str, Any] = Field(default_factory=dict)
    composition_plan: dict[str, Any] = Field(default_factory=dict)
    execution_results: list[dict[str, Any]] = Field(default_factory=list)
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)
    ibac_decisions: list[dict[str, Any]] = Field(default_factory=list)
    # Execution output & per-agent metrics
    output: str | None = None
    output_summary: str | None = None
    agent_metrics: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    dissolved_at: str
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# MCP Server DTOs
# ---------------------------------------------------------------------------


class MCPToolOverrideDTO(BaseModel):
    """Bus-specific metadata override for a single MCP tool."""
    description: str | None = None
    required_scopes: list[str] = Field(default_factory=list)
    supported_data_domains: list[str] = Field(default_factory=list)
    operational_constraints: dict[str, Any] = Field(default_factory=dict)
    expected_artifacts: list[str] = Field(default_factory=list)
    estimated_cost: float = 0.0
    estimated_latency: float = 0.0
    output_schema: dict[str, Any] = Field(default_factory=dict)


class MCPServerDTO(BaseModel):
    """Read model for an MCP server bridge."""
    id: int
    server_id: str
    server_url: str
    transport: str
    agent_id: str
    semantic_description: str = ""
    mode: str = "persistent"
    tool_overrides: dict[str, MCPToolOverrideDTO] = Field(default_factory=dict)
    status: str
    # Performance statistics
    total_executions: int = 0
    current_score: float = 0.0
    mean_latency_ms: float = 0.0
    last_execution_at: str | None = None
    created_at: str
    updated_at: str
    created_by: str
    # Runtime info (populated by the API)
    is_connected: bool = False
    discovered_tools: list[str] = Field(default_factory=list)


class MCPServerCreateRequest(BaseModel):
    """Payload for registering a new MCP server bridge."""
    server_id: str
    server_url: str
    agent_id: str
    transport: str = "http"
    auth_headers: dict[str, str] = Field(default_factory=dict)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    semantic_description: str = ""
    mode: str = "persistent"
    tool_overrides: dict[str, MCPToolOverrideDTO] = Field(default_factory=dict)
    activate: bool = True


class MCPServerUpdateRequest(BaseModel):
    """Payload for updating an MCP server bridge.  Only provided fields are changed."""
    server_url: str | None = None
    transport: str | None = None
    auth_headers: dict[str, str] | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    semantic_description: str | None = None
    mode: str | None = None
    tool_overrides: dict[str, MCPToolOverrideDTO] | None = None