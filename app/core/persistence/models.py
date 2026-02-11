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
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase


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
