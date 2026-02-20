"""SQLAlchemy ORM models for agent persistence and LLM configuration."""

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

    Uses the CrewAI Role-Goal-Backstory framework to define the agent's
    persona, plus capabilities (akin to CrewAI tasks) and tool bindings.

    Two kinds of agents live in the system:
    - **PersistentAgent**: externally-built agents that *connect* to the bus.
    - **ManagedAgent**: agents *created from within* the bus using CrewAI.
    """

    __tablename__ = "managed_agents"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    agent_id: str = Column(String(256), nullable=False, unique=True, index=True)

    # ── CrewAI Role-Goal-Backstory ──────────────────────────────────────
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

    # ── CrewAI agent options ───────────────────────────────────────────
    verbose: bool = Column(Boolean, nullable=False, default=False)
    max_iter: int = Column(Integer, nullable=False, default=25)
    max_rpm: int | None = Column(Integer, nullable=True)
    memory: bool = Column(Boolean, nullable=False, default=True)

    # ── Tool bindings (CrewAI tool names) ──────────────────────────────
    # Stored as a JSON list of tool identifiers, e.g.
    # ["SerperDevTool", "WebsiteSearchTool", "FileReadTool"]
    tools_json: list = Column(JSON, nullable=False, default=list)

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
    """A capability (≈ CrewAI Task template) bound to a managed agent.

    In Agentic Bus terminology a *capability* describes what an agent can
    do.  In CrewAI terms this maps to a Task the agent is specialised in.
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
        doc="Description of the expected output format (CrewAI expected_output).",
    )

    # ── Agentic Bus metadata ───────────────────────────────────────────
    required_scopes_json: list = Column(JSON, nullable=False, default=list)
    supported_data_domains_json: list = Column(JSON, nullable=False, default=list)
    operational_constraints_json: dict = Column(JSON, nullable=False, default=dict)
    expected_artifacts_json: list = Column(JSON, nullable=False, default=list)
    estimated_cost: float = Column(Float, nullable=False, default=0.0)
    estimated_latency: float = Column(Float, nullable=False, default=0.0)
    output_schema_json: dict = Column(JSON, nullable=False, default=dict)

    # ── Relationship ───────────────────────────────────────────────────
    agent = relationship(
        "ManagedAgent",
        back_populates="capabilities",
    )
