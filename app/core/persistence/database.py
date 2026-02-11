"""Database engine and session factory.

Reads ``AGBUS_DATABASE_URL`` from the environment (defaults to a local
SQLite file).  Call ``init_db()`` once at startup to create tables.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.persistence.models import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return (and lazily create) the global SQLAlchemy engine."""
    global _engine
    if _engine is None:
        url = os.getenv("AGBUS_DATABASE_URL", "sqlite:///agbus_agents.db")
        _engine = create_engine(url, echo=False, future=True)
        logger.info("Database engine created: %s", url.split("@")[-1])  # hide credentials
    return _engine


def get_session() -> Session:
    """Return a new SQLAlchemy session."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionFactory()


def init_db(engine: Engine | None = None) -> None:
    """Create all tables if they don't exist."""
    eng = engine or get_engine()
    Base.metadata.create_all(eng)
    logger.info("Database tables ensured")
