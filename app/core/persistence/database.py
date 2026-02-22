"""Database engine and session factory.

Reads ``AGBUS_DATABASE_URL`` from the environment (defaults to a local
SQLite file).  Call ``init_db()`` once at startup to create tables.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine, inspect, Engine, text
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


def _migrate_missing_columns(eng: Engine) -> None:
    """Add any columns defined in models but missing from existing tables.

    This is a lightweight auto-migration that covers simple column additions
    without requiring a full migration framework like Alembic.  It inspects
    every table declared in ``Base.metadata`` and issues ``ALTER TABLE …
    ADD COLUMN`` for any column not yet present in the database.
    """
    insp = inspect(eng)
    existing_tables = set(insp.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # table will be created by create_all

        existing_cols = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue

            # Build a portable column type string
            col_type = col.type.compile(dialect=eng.dialect)
            nullable = "NULL" if col.nullable else "NOT NULL"

            # Derive a safe DEFAULT clause
            default_clause = ""
            if col.default is not None:
                val = col.default.arg
                if callable(val):
                    val = val(None)
                if isinstance(val, str):
                    default_clause = f" DEFAULT '{val}'"
                elif isinstance(val, bool):
                    default_clause = f" DEFAULT {int(val)}"
                elif isinstance(val, (int, float)):
                    default_clause = f" DEFAULT {val}"
                elif isinstance(val, (list, dict)):
                    import json
                    default_clause = f" DEFAULT '{json.dumps(val)}'"
            elif col.nullable:
                default_clause = " DEFAULT NULL"

            ddl = (
                f"ALTER TABLE {table.name} ADD COLUMN {col.name} "
                f"{col_type} {nullable}{default_clause}"
            )
            logger.info("Auto-migrating: %s", ddl)
            with eng.begin() as conn:
                conn.execute(text(ddl))


def init_db(engine: Engine | None = None) -> None:
    """Create all tables if they don't exist and add any missing columns."""
    eng = engine or get_engine()
    _migrate_missing_columns(eng)
    Base.metadata.create_all(eng)
    logger.info("Database tables ensured")
