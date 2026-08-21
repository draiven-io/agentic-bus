"""Tests for the LLM configuration repository."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agentic_bus.core.persistence.models import Base
from agentic_bus.core.persistence.llm_repository import (
    LLMConfigRepository,
    LLMConfigNotFoundError,
    NoCurrentLLMConfigError,
)


@pytest.fixture(autouse=True)
def _in_memory_db(monkeypatch):
    """Create a fresh in-memory SQLite database for every test."""
    engine = create_engine("sqlite:///:memory:", echo=False, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(
        "agentic_bus.core.persistence.database.get_session",
        factory,
    )
    # Also patch the import path used by the repository module
    monkeypatch.setattr(
        "agentic_bus.core.persistence.llm_repository.get_session",
        factory,
    )
    yield engine


class TestLLMConfigRepository:
    """CRUD operations for LLM configurations."""

    def test_add_config(self):
        repo = LLMConfigRepository()
        cfg = repo.add(
            name="test-openai",
            provider="openai",
            model="gpt-4o-mini",
            temperature=0.0,
            api_key="sk-test",
        )
        assert cfg.name == "test-openai"
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o-mini"
        assert cfg.api_key == "sk-test"
        assert cfg.is_current is False

    def test_add_duplicate_raises(self):
        repo = LLMConfigRepository()
        repo.add(name="dup", provider="openai", model="gpt-4o-mini")
        with pytest.raises(ValueError, match="already exists"):
            repo.add(name="dup", provider="openai", model="gpt-4o")

    def test_add_with_is_current(self):
        repo = LLMConfigRepository()
        cfg = repo.add(
            name="active-one",
            provider="openai",
            model="gpt-4o-mini",
            is_current=True,
        )
        assert cfg.is_current is True

    def test_add_current_deactivates_previous(self):
        repo = LLMConfigRepository()
        repo.add(name="first", provider="openai", model="gpt-4o-mini", is_current=True)
        repo.add(name="second", provider="anthropic", model="claude-sonnet", is_current=True)

        first = repo.get_by_name("first")
        second = repo.get_by_name("second")
        assert first is not None and first.is_current is False
        assert second is not None and second.is_current is True

    def test_get_current(self):
        repo = LLMConfigRepository()
        repo.add(name="active", provider="openai", model="gpt-4o-mini", is_current=True)
        cfg = repo.get_current()
        assert cfg.name == "active"

    def test_get_current_raises_when_none(self):
        repo = LLMConfigRepository()
        with pytest.raises(NoCurrentLLMConfigError, match="No LLM configuration"):
            repo.get_current()

    def test_get_current_or_none(self):
        repo = LLMConfigRepository()
        assert repo.get_current_or_none() is None
        repo.add(name="one", provider="openai", model="gpt-4o-mini", is_current=True)
        assert repo.get_current_or_none() is not None

    def test_get_by_name(self):
        repo = LLMConfigRepository()
        repo.add(name="find-me", provider="openai", model="gpt-4o-mini")
        cfg = repo.get_by_name("find-me")
        assert cfg is not None
        assert cfg.name == "find-me"

    def test_get_by_name_not_found(self):
        repo = LLMConfigRepository()
        assert repo.get_by_name("nope") is None

    def test_list_all(self):
        repo = LLMConfigRepository()
        repo.add(name="a", provider="openai", model="gpt-4o-mini")
        repo.add(name="b", provider="anthropic", model="claude-sonnet")
        configs = repo.list_all()
        assert len(configs) == 2
        # Ordered by name
        assert configs[0].name == "a"
        assert configs[1].name == "b"

    def test_activate(self):
        repo = LLMConfigRepository()
        repo.add(name="old", provider="openai", model="gpt-4o-mini", is_current=True)
        repo.add(name="new", provider="anthropic", model="claude-sonnet")

        cfg = repo.activate("new")
        assert cfg.is_current is True

        old = repo.get_by_name("old")
        assert old is not None and old.is_current is False

    def test_activate_not_found(self):
        repo = LLMConfigRepository()
        with pytest.raises(LLMConfigNotFoundError):
            repo.activate("ghost")

    def test_update(self):
        repo = LLMConfigRepository()
        repo.add(name="updatable", provider="openai", model="gpt-4o-mini")
        cfg = repo.update("updatable", model="gpt-4o", temperature=0.7)
        assert cfg.model == "gpt-4o"
        assert cfg.temperature == 0.7

    def test_update_not_found(self):
        repo = LLMConfigRepository()
        with pytest.raises(LLMConfigNotFoundError):
            repo.update("ghost", model="x")

    def test_delete(self):
        repo = LLMConfigRepository()
        repo.add(name="deletable", provider="openai", model="gpt-4o-mini")
        assert repo.delete("deletable") is True
        assert repo.get_by_name("deletable") is None

    def test_delete_not_found(self):
        repo = LLMConfigRepository()
        assert repo.delete("ghost") is False

    def test_extra_config_stored(self):
        repo = LLMConfigRepository()
        extras = {"azure_openai_endpoint": "https://test.azure.com/", "azure_openai_api_version": "2024-12-01"}
        _cfg = repo.add(
            name="azure-cfg",
            provider="azure",
            model="gpt-4o-mini",
            extra_config=extras,
        )
        fetched = repo.get_by_name("azure-cfg")
        assert fetched is not None
        assert fetched.extra_config == extras

    def test_multiple_activate_cycles(self):
        """Cycling through activations keeps exactly one current."""
        repo = LLMConfigRepository()
        repo.add(name="a", provider="openai", model="m1")
        repo.add(name="b", provider="openai", model="m2")
        repo.add(name="c", provider="openai", model="m3")

        for name in ("a", "b", "c", "a"):
            repo.activate(name)
            configs = repo.list_all()
            current_count = sum(1 for c in configs if c.is_current)
            assert current_count == 1
            assert repo.get_current().name == name
