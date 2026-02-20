"""Tests for managed agent models, repository, and factory."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.persistence.models import (
    Base,
    ManagedAgent,
    ManagedAgentCapability,
    ManagedAgentStatus,
)
from app.core.persistence.managed_agent_repository import (
    ManagedAgentRepository,
    ManagedAgentNotFoundError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_engine():
    """Create an in-memory SQLite engine with all tables."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _patch_get_session(session_factory):
    """Patch get_session to use our in-memory DB."""
    with patch(
        "app.core.persistence.managed_agent_repository.get_session",
        side_effect=lambda: session_factory(),
    ):
        yield


@pytest.fixture()
def repo():
    return ManagedAgentRepository()


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestManagedAgentModel:
    def test_defaults(self, session_factory):
        """Verify sane defaults on a freshly-created row."""
        session = session_factory()
        agent = ManagedAgent(
            agent_id="test-01",
            name="Test Agent",
            role="Tester",
            goal="Test things",
            backstory="A dedicated tester.",
        )
        session.add(agent)
        session.commit()
        session.refresh(agent)

        assert agent.status == ManagedAgentStatus.DRAFT
        assert agent.verbose is False
        assert agent.max_iter == 25
        assert agent.memory is True
        assert agent.tools_json == []
        assert agent.llm_config_name is None

    def test_capability_cascade_delete(self, session_factory):
        """Deleting an agent should cascade-delete its capabilities."""
        session = session_factory()
        agent = ManagedAgent(
            agent_id="cascade-test",
            name="Cascade",
            role="R",
            goal="G",
            backstory="B",
        )
        session.add(agent)
        session.flush()

        cap = ManagedAgentCapability(
            agent_id="cascade-test",
            capability_id="cap-1",
            description="desc",
        )
        session.add(cap)
        session.commit()

        # Verify capability exists
        assert session.query(ManagedAgentCapability).count() == 1

        session.delete(agent)
        session.commit()
        assert session.query(ManagedAgentCapability).count() == 0


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------

class TestManagedAgentRepository:
    def test_create_basic(self, repo):
        agent = repo.create(
            agent_id="researcher-01",
            name="Market Researcher",
            role="Senior Market Research Analyst",
            goal="Provide actionable market insights",
            backstory="15 years in market research for top tech firms.",
        )
        assert agent.agent_id == "researcher-01"
        assert agent.role == "Senior Market Research Analyst"
        assert agent.status == ManagedAgentStatus.DRAFT

    def test_create_with_tools_and_capabilities(self, repo):
        agent = repo.create(
            agent_id="writer-01",
            name="Content Writer",
            role="Technical Blog Writer",
            goal="Create engaging blog posts",
            backstory="A skilled writer with a passion for technology.",
            tools=["SerperDevTool", "WebsiteSearchTool"],
            capabilities=[
                {
                    "capability_id": "blog_writing",
                    "description": "Write technical blog posts",
                    "expected_output": "A markdown blog post",
                    "required_scopes": ["content:write"],
                    "supported_data_domains": ["content", "technology"],
                    "estimated_cost": 0.05,
                    "estimated_latency": 10.0,
                },
            ],
            status=ManagedAgentStatus.ACTIVE,
        )
        assert agent.tools_json == ["SerperDevTool", "WebsiteSearchTool"]
        assert agent.status == ManagedAgentStatus.ACTIVE
        # Capabilities are loaded eagerly
        caps = repo.list_capabilities(agent.agent_id)
        assert len(caps) == 1
        assert caps[0].capability_id == "blog_writing"
        assert caps[0].expected_output == "A markdown blog post"
        assert caps[0].required_scopes_json == ["content:write"]

    def test_create_duplicate_raises(self, repo):
        repo.create(
            agent_id="dup-01",
            name="D",
            role="R",
            goal="G",
            backstory="B",
        )
        with pytest.raises(ValueError, match="already exists"):
            repo.create(
                agent_id="dup-01",
                name="D2",
                role="R2",
                goal="G2",
                backstory="B2",
            )

    def test_get_and_list(self, repo):
        repo.create(agent_id="a1", name="A1", role="R", goal="G", backstory="B")
        repo.create(
            agent_id="a2", name="A2", role="R", goal="G", backstory="B",
            status=ManagedAgentStatus.ACTIVE,
        )

        assert repo.get("a1") is not None
        assert repo.get("nonexistent") is None

        all_agents = repo.list_all()
        assert len(all_agents) == 2

        active = repo.list_all(status=ManagedAgentStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].agent_id == "a2"

    def test_get_or_raise(self, repo):
        with pytest.raises(ManagedAgentNotFoundError):
            repo.get_or_raise("nope")

    def test_update(self, repo):
        repo.create(agent_id="upd-01", name="Old", role="R", goal="G", backstory="B")

        updated = repo.update(
            "upd-01",
            name="New Name",
            role="New Role",
            verbose=True,
            tools=["FileReadTool"],
        )
        assert updated.name == "New Name"
        assert updated.role == "New Role"
        assert updated.verbose is True
        assert updated.tools_json == ["FileReadTool"]
        # Unchanged fields
        assert updated.goal == "G"

    def test_update_not_found(self, repo):
        with pytest.raises(ManagedAgentNotFoundError):
            repo.update("nope", name="X")

    def test_set_status(self, repo):
        repo.create(agent_id="st-01", name="S", role="R", goal="G", backstory="B")

        agent = repo.set_status("st-01", ManagedAgentStatus.ACTIVE)
        assert agent.status == ManagedAgentStatus.ACTIVE

        agent = repo.set_status("st-01", ManagedAgentStatus.DISABLED)
        assert agent.status == ManagedAgentStatus.DISABLED

    def test_add_and_remove_capability(self, repo):
        repo.create(agent_id="cap-01", name="C", role="R", goal="G", backstory="B")

        cap = repo.add_capability(
            "cap-01",
            capability_id="search",
            description="Search the web",
            expected_output="A list of search results",
            required_scopes=["web:read"],
        )
        assert cap.capability_id == "search"

        caps = repo.list_capabilities("cap-01")
        assert len(caps) == 1

        assert repo.remove_capability("cap-01", "search") is True
        assert repo.remove_capability("cap-01", "search") is False  # already removed
        assert repo.list_capabilities("cap-01") == []

    def test_add_capability_not_found(self, repo):
        with pytest.raises(ManagedAgentNotFoundError):
            repo.add_capability("nope", capability_id="x")

    def test_delete(self, repo):
        repo.create(agent_id="del-01", name="D", role="R", goal="G", backstory="B")
        assert repo.delete("del-01") is True
        assert repo.delete("del-01") is False
        assert repo.get("del-01") is None


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------

class TestFactory:
    def test_list_available_tools(self):
        from app.agents.factory import list_available_tools

        tools = list_available_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0
        assert "SerperDevTool" in tools
        assert "FileReadTool" in tools
        # Should be sorted
        assert tools == sorted(tools)

    def test_capabilities_from_agent(self, session_factory):
        """Test conversion from DB model to AgentCapability."""
        from app.agents.factory import capabilities_from_agent

        session = session_factory()
        agent = ManagedAgent(
            agent_id="conv-test",
            name="Conv",
            role="R",
            goal="G",
            backstory="B",
        )
        session.add(agent)
        session.flush()

        cap = ManagedAgentCapability(
            agent_id="conv-test",
            capability_id="analysis",
            description="Analyse data",
            required_scopes_json=["data:read"],
            supported_data_domains_json=["analytics"],
            estimated_cost=0.1,
            estimated_latency=5.0,
        )
        session.add(cap)
        session.commit()
        session.refresh(agent)

        bus_caps = capabilities_from_agent(agent)
        assert len(bus_caps) == 1
        assert bus_caps[0].capability_id == "analysis"
        assert bus_caps[0].required_scopes == ["data:read"]
        assert bus_caps[0].estimated_cost == 0.1

    def test_resolve_tool_unknown(self):
        from app.agents.factory import resolve_tool

        with pytest.raises(ValueError, match="Unknown tool"):
            resolve_tool("NonExistentToolXYZ")

    def test_resolve_tools_skips_failures(self):
        from app.agents.factory import resolve_tools

        # All tools will fail to import in test env (crewai_tools not installed)
        # but the function should not raise
        result = resolve_tools(["SerperDevTool", "UnknownTool"])
        # Either empty (if crewai_tools not installed) or has entries
        assert isinstance(result, list)

    def test_tool_descriptions_cover_catalogue(self):
        """Every tool in the catalogue should have a description."""
        from app.agents.factory import CREWAI_TOOL_CATALOGUE, CREWAI_TOOL_DESCRIPTIONS

        missing = set(CREWAI_TOOL_CATALOGUE) - set(CREWAI_TOOL_DESCRIPTIONS)
        assert missing == set(), f"Tools missing descriptions: {missing}"


# ---------------------------------------------------------------------------
# Checkbox picker fallback tests
# ---------------------------------------------------------------------------

class TestCheckboxPickerFallback:
    def test_non_interactive_fallback(self, monkeypatch):
        """When stdin is not a tty, _checkbox_picker falls back to text input."""
        from app.cli import _checkbox_picker

        # Force isatty() to return False
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("builtins.input", lambda prompt: "SerperDevTool, FileReadTool")

        result = _checkbox_picker(
            items=["SerperDevTool", "FileReadTool", "CSVSearchTool"],
            title="Pick tools",
        )
        assert result == ["SerperDevTool", "FileReadTool"]

    def test_non_interactive_empty(self, monkeypatch):
        """Empty input in fallback mode returns empty list."""
        from app.cli import _checkbox_picker

        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("builtins.input", lambda prompt: "")

        result = _checkbox_picker(items=["A", "B"], title="Pick")
        assert result == []
