"""Agent persistence layer.

Supports two agent registration modes:

- **Ephemeral**: agent registers on connect and disappears when the
  WebSocket connection drops.
- **Persistent**: agent enrols with an Ed25519 public key.  An admin
  approves the enrolment (or auto-approve is on).  On subsequent connects
  the agent proves identity via a cryptographic challenge–response.

A third mode is now available:

- **Managed**: agent is *created from within* the Agentic Bus using the
  CrewAI Role-Goal-Backstory framework.  Managed agents are stored in
  their own table and can be instantiated as CrewAI agents on demand.

Storage is backed by SQLAlchemy (SQLite by default, any SQL database via
``AGBUS_DATABASE_URL``).
"""

from agentic_bus.core.persistence.database import init_db, get_session, get_engine
from agentic_bus.core.persistence.repository import AgentRepository
from agentic_bus.core.persistence.llm_repository import (
    LLMConfigRepository,
    LLMConfigNotFoundError,
    NoCurrentLLMConfigError,
)
from agentic_bus.core.persistence.managed_agent_repository import (
    ManagedAgentRepository,
    ManagedAgentNotFoundError,
)
from agentic_bus.core.persistence.session_archive_repository import (
    SessionArchiveRepository,
    SessionArchiveNotFoundError,
)

__all__ = [
    "init_db",
    "get_session",
    "get_engine",
    "AgentRepository",
    "LLMConfigRepository",
    "LLMConfigNotFoundError",
    "NoCurrentLLMConfigError",
    "ManagedAgentRepository",
    "ManagedAgentNotFoundError",
    "SessionArchiveRepository",
    "SessionArchiveNotFoundError",
]
