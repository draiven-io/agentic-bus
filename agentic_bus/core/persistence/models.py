"""SQLAlchemy ORM models for agent persistence, LLM configuration, and
multi-tenant user management."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class AgentStatus(str, PyEnum):
    """Approval status for persistent agents."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class RegistrationMode(str, PyEnum):
    """How an agent is registered on the bus."""

    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"


class PersistentAgent(Base):
    """A persistently-registered agent.

    The agent enrols by sending its Ed25519 **public key**.
    An admin approves (or auto-approve is on) and then the agent
    authenticates on every connect via challenge–response.
    """

    __tablename__ = "persistent_agents"

    agent_id: str = Column(String(256), primary_key=True)
    public_key_pem: str = Column(Text, nullable=False)
    status: AgentStatus = Column(
        Enum(AgentStatus), nullable=False, default=AgentStatus.PENDING
    )
    #: The OIDC subject entitled to register as this agent. Empty means no
    #: binding, and any authenticated peer may claim the id — which is why
    #: it is recorded the first time an authenticated agent registers.
    #:
    #: Authentication proves who is connecting. This is what makes an
    #: ``agent_id`` mean a particular *who*, rather than a name anyone
    #: holding any valid credential can put in a payload.
    oidc_subject: str = Column(String(512), nullable=False, default="")
    semantic_description: str = Column(Text, nullable=False, default="")
    version: str = Column(String(64), nullable=False, default="0.1.0")
    capabilities_json: dict = Column(JSON, nullable=False, default=list)
    required_scopes_json: list = Column(JSON, nullable=False, default=list)
    supported_domains_json: list = Column(JSON, nullable=False, default=list)
    enrolled_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    approved_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
    approved_by: str | None = Column(String(256), nullable=True)
    last_connected_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

    # ── Performance statistics (updated after each execution) ──────────
    total_executions: int = Column(Integer, nullable=False, default=0)
    current_score: float = Column(Float, nullable=False, default=0.0)
    mean_latency_ms: float = Column(Float, nullable=False, default=0.0)
    last_execution_at: datetime | None = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------


class LLMConfig(Base):
    """An LLM provider configuration stored in the database.

    The admin can create multiple configurations (e.g. one for OpenAI, one
    for Anthropic) and mark exactly one as *current* (``is_current=True``).
    The LLM factory reads the current configuration at runtime so that:

    - The application can start without any LLM configured.
    - The admin can add / switch providers via CLI or the admin API
      without restarting the coordinator.
    """

    __tablename__ = "llm_configs"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    name: str = Column(String(256), nullable=False, unique=True)
    provider: str = Column(String(64), nullable=False)
    model: str = Column(String(256), nullable=False)
    temperature: float = Column(Float, nullable=False, default=0.0)
    api_key: str | None = Column(Text, nullable=True)
    extra_config: dict = Column(JSON, nullable=False, default=dict)
    is_current: bool = Column(Boolean, nullable=False, default=False)
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: str = Column(String(256), nullable=False, default="admin")


# ---------------------------------------------------------------------------
# Managed agents – agents created and managed by the Agentic Bus itself
# ---------------------------------------------------------------------------


class ManagedAgentStatus(str, PyEnum):
    """Lifecycle status for a managed agent."""

    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class ManagedAgent(Base):
    """An agent created and managed within the Agentic Bus via CLI.

    Uses a role/goal/backstory persona to define the agent's
    persona, plus capabilities and tool bindings.

    Two kinds of agents live in the system:
    - **PersistentAgent**: externally-built agents that *connect* to the bus.
    - **ManagedAgent**: agents *created from within* the bus.
    """

    __tablename__ = "managed_agents"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    agent_id: str = Column(String(256), nullable=False, unique=True, index=True)

    # ── Role-Goal-Backstory persona ─────────────────────────────────────
    name: str = Column(String(256), nullable=False)
    role: str = Column(Text, nullable=False)
    goal: str = Column(Text, nullable=False)
    backstory: str = Column(Text, nullable=False)

    # ── LLM configuration ──────────────────────────────────────────────
    # Optional override – when NULL the bus-wide current LLM config is used.
    llm_config_name: str | None = Column(
        String(256),
        nullable=True,
        doc="Name of the LLMConfig to use.  NULL = bus default.",
    )

    # ── Agent options ──────────────────────────────────────────────────
    verbose: bool = Column(Boolean, nullable=False, default=False)
    max_iter: int = Column(Integer, nullable=False, default=25)
    max_rpm: int | None = Column(Integer, nullable=True)
    memory: bool = Column(Boolean, nullable=False, default=True)

    # ── Tool bindings ──────────────────────────────────────────────────
    # Stored as a JSON list of tool identifiers, e.g.
    # ["web_search", "fetch_webpage", "read_file"]
    tools_json: list = Column(JSON, nullable=False, default=list)

    # ── Per-tool configuration ─────────────────────────────────────────
    # Stored as a JSON dict mapping tool names to their config dicts:
    # {"web_search": {"api_key": "..."}}
    tool_config_json: dict = Column(JSON, nullable=False, default=dict)

    # ── Lifecycle ──────────────────────────────────────────────────────
    status: ManagedAgentStatus = Column(
        Enum(ManagedAgentStatus),
        nullable=False,
        default=ManagedAgentStatus.DRAFT,
    )
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: str = Column(String(256), nullable=False, default="admin")

    # ── Performance statistics (updated after each execution) ──────────
    total_executions: int = Column(Integer, nullable=False, default=0)
    current_score: float = Column(Float, nullable=False, default=0.0)
    mean_latency_ms: float = Column(Float, nullable=False, default=0.0)
    last_execution_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

    # ── Relationships ──────────────────────────────────────────────────
    # NOTE: no type annotation — SQLAlchemy Declarative Table interprets
    # bare ``list[...]`` as a mapped column.  Use untyped assignment.
    capabilities = relationship(
        "ManagedAgentCapability",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="joined",
    )


class ManagedAgentCapability(Base):
    """A capability bound to a managed agent.

    In Agentic Bus terminology a *capability* describes what an agent can
    do — a task the agent is specialised in.
    """

    __tablename__ = "managed_agent_capabilities"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    agent_id: str = Column(
        String(256),
        ForeignKey("managed_agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Capability identity ────────────────────────────────────────────
    capability_id: str = Column(String(256), nullable=False)
    description: str = Column(Text, nullable=False, default="")
    expected_output: str = Column(
        Text,
        nullable=False,
        default="",
        doc="Description of the expected output format.",
    )

    # ── Agentic Bus metadata ───────────────────────────────────────────
    required_scopes_json: list = Column(JSON, nullable=False, default=list)
    supported_data_domains_json: list = Column(JSON, nullable=False, default=list)
    operational_constraints_json: dict = Column(JSON, nullable=False, default=dict)
    expected_artifacts_json: list = Column(JSON, nullable=False, default=list)
    estimated_cost: float = Column(Float, nullable=False, default=0.0)
    estimated_latency: float = Column(Float, nullable=False, default=0.0)
    output_schema_json: dict = Column(JSON, nullable=False, default=dict)
    output_fields_json: list = Column(
        JSON,
        nullable=False,
        default=list,
        doc=(
            "List of output field definitions.  Each entry is a dict with "
            "'name' (str), 'type' (str – one of str/int/float/bool/list/dict), "
            "and optional 'description' (str).  Used to build a Pydantic model "
            "at runtime so the agent output is structured and predictable."
        ),
    )

    # ── Relationship ───────────────────────────────────────────────────
    agent = relationship(
        "ManagedAgent",
        back_populates="capabilities",
    )


# ---------------------------------------------------------------------------
# Multi-tenant user management
# ---------------------------------------------------------------------------


class UserRole(str, PyEnum):
    """Role a user can hold within the system."""

    ADMIN = "admin"
    USER = "user"


class Tenant(Base):
    """An organisational tenant.  Users and agents are grouped by tenant."""

    __tablename__ = "tenants"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    slug: str = Column(String(128), nullable=False, unique=True, index=True)
    name: str = Column(String(256), nullable=False)
    enabled: bool = Column(Boolean, nullable=False, default=True)
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # relationships
    user_associations = relationship(
        "UserTenantAssociation",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="joined",
    )
    agent_associations = relationship(
        "AgentTenantAssociation",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="joined",
    )


class User(Base):
    """A system user.  Created by an admin when OIDC is configured.

    The ``subject`` is the OIDC ``sub`` claim and uniquely identifies the
    user across IdPs.
    """

    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    subject: str = Column(String(256), nullable=False, unique=True, index=True)
    email: str = Column(String(320), nullable=False, default="")
    display_name: str = Column(String(256), nullable=False, default="")
    role: UserRole = Column(
        Enum(UserRole), nullable=False, default=UserRole.USER
    )
    enabled: bool = Column(Boolean, nullable=False, default=True)
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: str = Column(String(256), nullable=False, default="admin")

    # relationships
    tenant_associations = relationship(
        "UserTenantAssociation",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="joined",
    )


class UserTenantAssociation(Base):
    """Many-to-many: which users belong to which tenants."""

    __tablename__ = "user_tenants"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: int = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="tenant_associations")
    tenant = relationship("Tenant", back_populates="user_associations")


class AgentTenantAssociation(Base):
    """Many-to-many: which agents (persistent or managed) belong to
    which tenants.

    ``agent_id`` references the logical agent identifier string used by
    both ``PersistentAgent.agent_id`` and ``ManagedAgent.agent_id``.
    """

    __tablename__ = "agent_tenants"
    __table_args__ = (
        UniqueConstraint("agent_id", "tenant_id", name="uq_agent_tenant"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    agent_id: str = Column(String(256), nullable=False, index=True)
    tenant_id: int = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    tenant = relationship("Tenant", back_populates="agent_associations")


# ---------------------------------------------------------------------------
# IBAC Rules – admin-configurable guardrails (§6.1 of LIP paper)
# ---------------------------------------------------------------------------


class IBACRuleAction(str, PyEnum):
    """What happens when an IBAC rule matches."""

    DENY = "deny"
    ALLOW = "allow"


class IBACRule(Base):
    """A persisted IBAC guardrail rule created by an admin.

    IBAC (Intention-Based Access Control) evaluates governance decisions
    against the *expressed intent*, contextual constraints, and
    organisational policies (§6.1 of the Liquid Interfaces paper).

    Rules are evaluated at one or more IBAC evaluation points:
      1. intent_admission
      2. offer_eligibility
      3. negotiation_acceptance
      4. execution_authorization
      5. artifact_emission

    The ``conditions`` JSON column holds a flexible set of match criteria:
      - ``intent_keywords``:  list[str] – deny/allow when intent text
        contains any of these keywords (case-insensitive).
      - ``intent_patterns``: list[str] – regex patterns matched against
        the intent text.
      - ``blocked_agents`` / ``allowed_agents``: list[str] – agent ID
        filters.
      - ``blocked_scopes`` / ``allowed_scopes``: list[str] – scope
        filters.
      - ``blocked_domains`` / ``allowed_domains``: list[str] – data
        domain filters.
      - ``max_agents``: int – maximum number of agents in a composition.
      - ``require_human_approval``: bool – force human-in-the-loop (maps
        to a special constraint returned in the IBAC result).

    Rules are processed in ``priority`` order (lower = first).  First
    DENY wins; if no rule denies, default is ALLOW.
    """

    __tablename__ = "ibac_rules"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    rule_id: str = Column(String(256), nullable=False, unique=True, index=True)
    name: str = Column(String(256), nullable=False)
    description: str = Column(Text, nullable=False, default="")
    enabled: bool = Column(Boolean, nullable=False, default=True)
    priority: int = Column(Integer, nullable=False, default=100)
    action: IBACRuleAction = Column(
        Enum(IBACRuleAction), nullable=False, default=IBACRuleAction.DENY
    )

    # Which evaluation points this rule applies to (JSON list of strings).
    # Empty list means the rule applies to ALL evaluation points.
    evaluation_points_json: list = Column(JSON, nullable=False, default=list)

    # Flexible match conditions (see docstring above).
    conditions_json: dict = Column(JSON, nullable=False, default=dict)

    # Metadata
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: str = Column(String(256), nullable=False, default="admin")


# ---------------------------------------------------------------------------
# Session Archive – persisted snapshots of dissolved sessions (§5.1.2)
# ---------------------------------------------------------------------------


class SessionOutcome(str, PyEnum):
    """High-level outcome of a completed session."""

    SUCCESS = "success"
    ERROR = "error"
    PARTIAL_FAILURE = "partial_failure"
    DENIED = "denied"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Scope vocabulary (RFC 0003)
# ---------------------------------------------------------------------------


class ScopeCatalogueEntry(Base):
    """A scope name this coordinator recognises.

    The vocabulary belongs to the deployment, not to whoever wrote an agent.
    Without this table a scope was a free string nobody validated, so
    ``carrier:qoute`` registered exactly as successfully as ``carrier:quote``
    and every rule guarding that capability silently stopped applying.
    """

    __tablename__ = "scope_catalogue"

    name: str = Column(String(128), primary_key=True)
    #: What holding this permits, in the deployment's own words. Shown to an
    #: administrator deciding a binding, and in the refusal that teaches an
    #: agent author the right name — so it is worth writing properly.
    description: str = Column(Text, nullable=False, default="")
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    #: "admin" when authored, "auto" when a development coordinator added it
    #: on first sight. The distinction matters when reviewing a catalogue that
    #: grew by accident.
    created_by: str = Column(String(256), nullable=False, default="admin")


class CapabilityScopeBinding(Base):
    """Which catalogued scopes one agent's capability has been granted.

    The binding is the authority. An agent's declared ``required_scopes`` is a
    request and never a grant — RFC 0003 — so an unbound capability holds
    nothing, deliberately. Treating "nobody decided" as "everything permitted"
    is the fail-open shape this protocol has already had to remove twice.
    """

    __tablename__ = "capability_scope_bindings"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "capability_id", "scope", name="uq_capability_scope"
        ),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    agent_id: str = Column(String(256), nullable=False, index=True)
    capability_id: str = Column(String(256), nullable=False, index=True)
    scope: str = Column(String(128), nullable=False)
    bound_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    bound_by: str = Column(String(256), nullable=False, default="admin")


class ScopeRequest(Base):
    """A scope an agent asked for that the catalogue did not recognise.

    Recorded rather than discarded, because it is an agent telling an operator
    what it needs. Previously this information had nowhere to go: the name
    either passed unnoticed or failed without explanation.
    """

    __tablename__ = "scope_requests"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "capability_id", "scope", name="uq_scope_request"
        ),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    agent_id: str = Column(String(256), nullable=False, index=True)
    capability_id: str = Column(String(256), nullable=False, default="")
    scope: str = Column(String(128), nullable=False)
    first_requested_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_requested_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    #: How often the agent has asked. A capability that keeps requesting the
    #: same scope is making a case for itself.
    request_count: int = Column(Integer, nullable=False, default=1)


class SessionArchive(Base):
    """Archived snapshot of a dissolved Agentic Bus session.

    Per Invariant II (§5.1.2), live session state is destroyed upon
    dissolution.  This archive captures a *read-only historical record*
    of the session for auditing, debugging, and analytics — it is NOT
    a live coordination artifact.

    All rich data (timeline events, agent map, execution plan, results,
    and the full audit trail of envelopes) is stored as JSON columns so
    the frontend can replay the entire negotiation flow.
    """

    __tablename__ = "session_archives"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    session_id: str = Column(String(256), nullable=False, unique=True, index=True)

    # ── Identity ───────────────────────────────────────────────────────
    requester_id: str = Column(String(256), nullable=False)
    requester_oidc_subject: str = Column(String(256), nullable=False, default="")

    # ── Intent ─────────────────────────────────────────────────────────
    intent_text: str = Column(Text, nullable=False, default="")
    intent_domain: str = Column(String(256), nullable=False, default="")
    decomposition_json: dict = Column(JSON, nullable=False, default=dict)

    # ── Outcome ────────────────────────────────────────────────────────
    outcome: SessionOutcome = Column(
        Enum(SessionOutcome), nullable=False, default=SessionOutcome.SUCCESS
    )
    outcome_summary: str = Column(Text, nullable=False, default="")

    # ── Participating agents ───────────────────────────────────────────
    discovered_agents_json: list = Column(JSON, nullable=False, default=list)
    accepted_agents_json: list = Column(JSON, nullable=False, default=list)
    # Full agent detail map: {agent_id: {capabilityId, description, status, ...}}
    agents_json: dict = Column(JSON, nullable=False, default=dict)

    # ── Composition plan ───────────────────────────────────────────────
    composition_plan_json: dict = Column(JSON, nullable=False, default=dict)

    # ── Execution results ──────────────────────────────────────────────
    execution_results_json: list = Column(JSON, nullable=False, default=list)

    # ── Timeline events (the UI event stream) ─────────────────────────
    timeline_events_json: list = Column(JSON, nullable=False, default=list)

    # ── Full audit trail (every AgBusEnvelope exchanged) ──────────────
    audit_trail_json: list = Column(JSON, nullable=False, default=list)

    # ── IBAC decisions ─────────────────────────────────────────────────
    ibac_decisions_json: list = Column(JSON, nullable=False, default=list)

    # ── Agent quality metrics ──────────────────────────────────────────
    # Per-agent scoring and latency: [{agent_id, quality_score, latency_ms, retries, quality_rationale}]
    agent_metrics_json: list = Column(JSON, nullable=False, default=list)

    # ── Synthesised output ─────────────────────────────────────────────
    output: str = Column(Text, nullable=False, default="")
    output_summary: str = Column(Text, nullable=False, default="")

    # ── Timing ─────────────────────────────────────────────────────────
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    dissolved_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    duration_seconds: float = Column(Float, nullable=False, default=0.0)


# ---------------------------------------------------------------------------
# MCP Server Bridges – external MCP servers bridged into the bus
# ---------------------------------------------------------------------------


class MCPServerStatus(str, PyEnum):
    """Lifecycle status for an MCP server bridge."""

    ACTIVE = "active"
    DISABLED = "disabled"


class MCPServer(Base):
    """An external MCP server registered to participate on the Agentic Bus.

    MCP servers expose *tools* via the Model Context Protocol.  The bridge
    agent connects to the MCP server, discovers its tools, and maps each
    tool to an ``AgentCapability`` so the coordinator can discover, negotiate
    with, and delegate to MCP tools exactly like any native agent.

    Bus-specific metadata (IBAC scopes, cost estimates, data domains) is
    NOT part of the MCP protocol — the admin provides it here as overrides.
    """

    __tablename__ = "mcp_servers"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    server_id: str = Column(String(256), nullable=False, unique=True, index=True)

    # ── Connection ─────────────────────────────────────────────────────
    server_url: str = Column(Text, nullable=False)
    transport: str = Column(
        String(32), nullable=False, default="http",
        doc="MCP transport type: 'http' (Streamable HTTP) or 'stdio'.",
    )
    auth_headers_json: dict = Column(
        JSON, nullable=False, default=dict,
        doc="HTTP headers for authenticated MCP connections (e.g. Bearer tokens).",
    )
    # stdio-specific fields
    command: str = Column(
        String(512), nullable=False, default="",
        doc="Command to launch stdio MCP server (e.g. 'python').",
    )
    args_json: list = Column(
        JSON, nullable=False, default=list,
        doc="Arguments for the stdio command (e.g. ['/path/to/server.py']).",
    )
    env_json: dict = Column(
        JSON, nullable=False, default=dict,
        doc="Extra environment variables for the stdio subprocess.",
    )

    # ── Bus identity ───────────────────────────────────────────────────
    agent_id: str = Column(
        String(256), nullable=False, unique=True, index=True,
        doc="The agent ID under which this MCP server appears on the bus.",
    )
    semantic_description: str = Column(Text, nullable=False, default="")
    mode: str = Column(
        String(32), nullable=False, default="persistent",
        doc="Registration mode: 'ephemeral' or 'persistent'.",
    )

    # ── Per-tool bus metadata overrides (keyed by MCP tool name) ───────
    tool_overrides_json: dict = Column(
        JSON, nullable=False, default=dict,
        doc=(
            "Dict mapping MCP tool names to bus-specific metadata overrides. "
            "Each value is a dict with optional keys: required_scopes, "
            "supported_data_domains, operational_constraints, "
            "expected_artifacts, estimated_cost, estimated_latency."
        ),
    )

    # ── Lifecycle ──────────────────────────────────────────────────────
    status: MCPServerStatus = Column(
        Enum(MCPServerStatus),
        nullable=False,
        default=MCPServerStatus.ACTIVE,
    )
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: str = Column(String(256), nullable=False, default="admin")

    # ── Performance statistics ─────────────────────────────────────────
    total_executions: int = Column(Integer, nullable=False, default=0)
    current_score: float = Column(Float, nullable=False, default=0.0)
    mean_latency_ms: float = Column(Float, nullable=False, default=0.0)
    last_execution_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
