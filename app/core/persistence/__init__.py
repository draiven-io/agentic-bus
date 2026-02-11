"""Agent persistence layer.

Supports two agent registration modes:

- **Ephemeral**: agent registers on connect and disappears when the
  WebSocket connection drops.
- **Persistent**: agent enrols with an Ed25519 public key.  An admin
  approves the enrolment (or auto-approve is on).  On subsequent connects
  the agent proves identity via a cryptographic challenge–response.

Storage is backed by SQLAlchemy (SQLite by default, any SQL database via
``AGBUS_DATABASE_URL``).
"""

from app.core.persistence.database import init_db, get_session, get_engine
from app.core.persistence.repository import AgentRepository
from app.core.persistence.llm_repository import (
    LLMConfigRepository,
    LLMConfigNotFoundError,
    NoCurrentLLMConfigError,
)

__all__ = [
    "init_db",
    "get_session",
    "get_engine",
    "AgentRepository",
    "LLMConfigRepository",
    "LLMConfigNotFoundError",
    "NoCurrentLLMConfigError",
]
