"""Shared pytest configuration for the Agentic Bus test-suite.

Two things made the suite non-hermetic before this file existed:

1. ``agentic_bus/cli.py`` calls ``load_dotenv(find_dotenv(usecwd=True))`` at *import*
   time.  ``find_dotenv`` walks parent directories, so a developer's local
   ``.env`` — or any ``.env`` sitting above the checkout — silently populated
   ``os.environ`` before a single test ran.
2. Repositories share a lazily-built module-global engine bound to
   ``AGBUS_DATABASE_URL``.  Tests that patched only *one* repository's session
   factory left every other repository pointing at whatever database the host
   happened to be configured with.

Together those meant the suite passed on a configured workstation and failed
on a clean checkout or a CI runner — the inverse of what a test-suite is for.

The autouse fixtures below give every test a scrubbed environment and its own
fully-migrated SQLite database.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from agentic_bus.core.persistence import database as _database

#: Environment prefixes and keys that must never leak in from the host.
_MANAGED_PREFIXES = ("AGBUS_", "AZURE_OPENAI_")
_MANAGED_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
)


@pytest.fixture(scope="session")
def _schema_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the full schema once, then hand out copies.

    ``create_all`` on every test would add up over 400+ tests, so the schema
    is materialised a single time into a template file that per-test fixtures
    copy.  Copying a small SQLite file is far cheaper than re-running DDL.
    """
    from sqlalchemy import create_engine

    from agentic_bus.core.persistence.models import Base

    template = tmp_path_factory.mktemp("schema") / "template.db"
    engine = create_engine(f"sqlite:///{template}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    return template


@pytest.fixture(autouse=True)
def hermetic_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    _schema_template: Path,
) -> None:
    """Scrub host configuration and bind a private database per test.

    Autouse, so it applies everywhere.  A test that needs a specific value
    simply calls ``monkeypatch.setenv`` afterwards — fixture ordering
    guarantees the test's own override wins.
    """
    for key in list(os.environ):
        if key.startswith(_MANAGED_PREFIXES) or key in _MANAGED_KEYS:
            monkeypatch.delenv(key, raising=False)

    db_path = tmp_path / "agbus-test.db"
    shutil.copyfile(_schema_template, db_path)
    # ``_require_configuration`` in the CLI treats this as "the system has
    # been set up", so CLI tests exercise their real subject rather than the
    # not-configured guard rail.
    monkeypatch.setenv("AGBUS_DATABASE_URL", f"sqlite:///{db_path}")

    # The engine is a module global cached across imports; reset it so this
    # test's URL is honoured, and reset it again afterwards so no engine
    # outlives the temporary file it points at.
    _reset_engine()
    yield
    _reset_engine()


def _reset_engine() -> None:
    """Drop the cached engine and session factory."""
    if _database._engine is not None:
        _database._engine.dispose()
    _database._engine = None
    _database._SessionFactory = None
