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
        assert agent.tool_config_json == {}
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
            tool_config={
                "SerperDevTool": {"api_key": "test-serper-key-12345"},
            },
            capabilities=[
                {
                    "capability_id": "blog_writing",
                    "description": "Write technical blog posts",
                    "expected_output": "A markdown blog post",
                    "supported_data_domains": ["content", "technology"],
                    "estimated_cost": 0.05,
                    "estimated_latency": 10.0,
                },
            ],
            status=ManagedAgentStatus.ACTIVE,
        )
        assert agent.tools_json == ["SerperDevTool", "WebsiteSearchTool"]
        assert agent.tool_config_json == {
            "SerperDevTool": {"api_key": "test-serper-key-12345"},
        }
        assert agent.status == ManagedAgentStatus.ACTIVE
        # Capabilities are loaded eagerly
        caps = repo.list_capabilities(agent.agent_id)
        assert len(caps) == 1
        assert caps[0].capability_id == "blog_writing"
        assert caps[0].expected_output == "A markdown blog post"

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
            tool_config={"FileReadTool": {}},
        )
        assert updated.name == "New Name"
        assert updated.role == "New Role"
        assert updated.verbose is True
        assert updated.tools_json == ["FileReadTool"]
        assert updated.tool_config_json == {"FileReadTool": {}}
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

    def test_capabilities_from_agent_with_output_fields(self, session_factory):
        """When output_fields_json is set, output_schema is auto-derived."""
        from app.agents.factory import capabilities_from_agent

        session = session_factory()
        agent = ManagedAgent(
            agent_id="conv-out",
            name="Conv Out",
            role="R",
            goal="G",
            backstory="B",
        )
        session.add(agent)
        session.flush()

        cap = ManagedAgentCapability(
            agent_id="conv-out",
            capability_id="translate_text",
            description="Translate",
            output_fields_json=[
                {"name": "translated_text", "type": "str", "description": "The translated text"},
                {"name": "confidence", "type": "float", "description": "Confidence score"},
            ],
        )
        session.add(cap)
        session.commit()
        session.refresh(agent)

        bus_caps = capabilities_from_agent(agent)
        assert len(bus_caps) == 1
        schema = bus_caps[0].output_schema
        assert "properties" in schema
        assert "translated_text" in schema["properties"]
        assert "confidence" in schema["properties"]

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

    def test_tool_requirements_metadata(self):
        """CREWAI_TOOL_REQUIREMENTS should have valid structure."""
        from app.agents.factory import (
            CREWAI_TOOL_CATALOGUE,
            CREWAI_TOOL_REQUIREMENTS,
            get_tool_requirements,
        )

        for tool_name, reqs in CREWAI_TOOL_REQUIREMENTS.items():
            assert tool_name in CREWAI_TOOL_CATALOGUE, (
                f"Requirement defined for unknown tool: {tool_name}"
            )
            assert isinstance(reqs, list)
            for req in reqs:
                assert "key" in req
                assert "env" in req
                assert "label" in req
                assert "required" in req
                assert "secret" in req
                assert "hint" in req

        # get_tool_requirements returns [] for tools with no reqs
        assert get_tool_requirements("FileReadTool") == []
        assert len(get_tool_requirements("SerperDevTool")) > 0

    def test_inject_tool_env(self, monkeypatch):
        """_inject_tool_env should set the correct environment variables."""
        import os
        from app.agents.factory import _inject_tool_env

        # Clear any existing env var
        monkeypatch.delenv("SERPER_API_KEY", raising=False)

        _inject_tool_env("SerperDevTool", {"api_key": "test-key-123"})
        assert os.environ.get("SERPER_API_KEY") == "test-key-123"

        # Empty value should not be injected
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        _inject_tool_env("SerperDevTool", {"api_key": ""})
        assert os.environ.get("SERPER_API_KEY") is None

        # Unknown tool does nothing
        _inject_tool_env("FileReadTool", {"api_key": "whatever"})
        # No error raised


# ---------------------------------------------------------------------------
# build_output_model tests
# ---------------------------------------------------------------------------

class TestBuildOutputModel:
    def test_basic_model(self):
        """Build a model with str, int, float fields."""
        from app.agents.factory import build_output_model

        Model = build_output_model("translate_text", [
            {"name": "translated_text", "type": "str", "description": "The translated text"},
            {"name": "word_count", "type": "int"},
            {"name": "confidence", "type": "float", "description": "Confidence 0-1"},
        ])

        # Class name should be PascalCase + Output
        assert Model.__name__ == "TranslateTextOutput"

        # Should be a valid Pydantic model
        instance = Model(translated_text="Olá", word_count=1, confidence=0.95)
        assert instance.translated_text == "Olá"
        assert instance.word_count == 1
        assert instance.confidence == 0.95

        # JSON schema should have all fields
        schema = Model.model_json_schema()
        assert "translated_text" in schema["properties"]
        assert "word_count" in schema["properties"]
        assert "confidence" in schema["properties"]

    def test_bool_list_dict_types(self):
        from app.agents.factory import build_output_model

        Model = build_output_model("mixed", [
            {"name": "is_valid", "type": "bool"},
            {"name": "tags", "type": "list"},
            {"name": "metadata", "type": "dict"},
        ])
        instance = Model(is_valid=True, tags=["a", "b"], metadata={"k": "v"})
        assert instance.is_valid is True
        assert instance.tags == ["a", "b"]
        assert instance.metadata == {"k": "v"}

    def test_type_aliases(self):
        """'string', 'integer', 'number', 'boolean', 'array', 'object' should work."""
        from app.agents.factory import build_output_model

        Model = build_output_model("alias_test", [
            {"name": "a", "type": "string"},
            {"name": "b", "type": "integer"},
            {"name": "c", "type": "number"},
            {"name": "d", "type": "boolean"},
            {"name": "e", "type": "array"},
            {"name": "f", "type": "object"},
        ])
        instance = Model(a="x", b=1, c=3.14, d=False, e=[], f={})
        assert instance.a == "x"
        assert instance.b == 1

    def test_default_type_is_str(self):
        """Omitted or unknown type defaults to str."""
        from app.agents.factory import build_output_model

        Model = build_output_model("default_type", [
            {"name": "no_type"},
            {"name": "bad_type", "type": "unknown_type_xyz"},
        ])
        instance = Model(no_type="hello", bad_type="world")
        assert instance.no_type == "hello"

    def test_empty_fields_raises(self):
        from app.agents.factory import build_output_model

        with pytest.raises(ValueError, match="non-empty"):
            build_output_model("empty", [])

    def test_all_blank_names_raises(self):
        from app.agents.factory import build_output_model

        with pytest.raises(ValueError, match="No valid fields"):
            build_output_model("blank", [{"name": ""}, {"name": ""}])

    def test_model_dump(self):
        """Verify model_dump() produces a clean dict."""
        from app.agents.factory import build_output_model

        Model = build_output_model("report", [
            {"name": "title", "type": "str"},
            {"name": "score", "type": "float"},
        ])
        instance = Model(title="Q4 Report", score=92.5)
        d = instance.model_dump()
        assert d == {"title": "Q4 Report", "score": 92.5}


# ---------------------------------------------------------------------------
# Repository output_fields tests
# ---------------------------------------------------------------------------

class TestRepositoryOutputFields:
    def test_create_with_output_fields(self, repo):
        """output_fields should be stored and output_schema auto-derived."""
        agent = repo.create(
            agent_id="of-01",
            name="Output Fields Agent",
            role="R",
            goal="G",
            backstory="B",
            capabilities=[{
                "capability_id": "summarise",
                "description": "Summarise text",
                "output_fields": [
                    {"name": "summary", "type": "str", "description": "The summary"},
                    {"name": "length", "type": "int", "description": "Word count"},
                ],
            }],
        )
        cap = agent.capabilities[0]
        assert cap.output_fields_json == [
            {"name": "summary", "type": "str", "description": "The summary"},
            {"name": "length", "type": "int", "description": "Word count"},
        ]
        # output_schema should have been auto-derived
        assert "properties" in cap.output_schema_json
        assert "summary" in cap.output_schema_json["properties"]
        assert "length" in cap.output_schema_json["properties"]

    def test_add_capability_with_output_fields(self, repo):
        """add_capability should also accept and persist output_fields."""
        repo.create(
            agent_id="of-02",
            name="Add Cap Test",
            role="R",
            goal="G",
            backstory="B",
        )
        cap = repo.add_capability(
            agent_id="of-02",
            capability_id="extract",
            description="Extract entities",
            output_fields=[
                {"name": "entities", "type": "list"},
                {"name": "count", "type": "int"},
            ],
        )
        assert cap.output_fields_json == [
            {"name": "entities", "type": "list"},
            {"name": "count", "type": "int"},
        ]
        assert "properties" in cap.output_schema_json

    def test_create_without_output_fields(self, repo):
        """Capabilities without output_fields should still work fine."""
        agent = repo.create(
            agent_id="of-03",
            name="No Fields",
            role="R",
            goal="G",
            backstory="B",
            capabilities=[{
                "capability_id": "basic",
                "description": "Basic task",
            }],
        )
        cap = agent.capabilities[0]
        assert cap.output_fields_json == []
        assert cap.output_schema_json == {}


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


# ---------------------------------------------------------------------------
# Serializer secret masking tests
# ---------------------------------------------------------------------------

class TestToolSecretMasking:
    def test_mask_secrets(self):
        """Secret values in tool config should be masked in DTO output."""
        from app.coordinator.admin.serializers import _mask_tool_secrets

        config = {
            "SerperDevTool": {"api_key": "serper-key-1234567890"},
            "FileReadTool": {},
        }
        result = _mask_tool_secrets(
            ["SerperDevTool", "FileReadTool"], config,
        )
        # SerperDevTool api_key is secret → should be masked
        assert result["SerperDevTool"]["api_key"] != "serper-key-1234567890"
        assert "…" in result["SerperDevTool"]["api_key"]
        # FileReadTool has no config
        assert result["FileReadTool"] == {}

    def test_mask_non_secret_passes_through(self):
        """Non-secret fields should pass through unmasked."""
        from app.coordinator.admin.serializers import _mask_tool_secrets

        config = {
            "GithubSearchTool": {
                "api_key": "ghp_abc1234567890xyz",
                "github_repo": "owner/repo",
            },
        }
        result = _mask_tool_secrets(["GithubSearchTool"], config)
        # api_key is secret
        assert "…" in result["GithubSearchTool"]["api_key"]
        # github_repo is NOT secret
        assert result["GithubSearchTool"]["github_repo"] == "owner/repo"

    def test_mask_short_secret(self):
        """Very short secrets should be fully masked."""
        from app.coordinator.admin.serializers import _mask_tool_secrets

        config = {"SerperDevTool": {"api_key": "short"}}
        result = _mask_tool_secrets(["SerperDevTool"], config)
        assert result["SerperDevTool"]["api_key"] == "***"
