"""Tests for the MCP bridge integration layer.

Covers:
- MCPServerRepository CRUD operations
- MCPServer ORM model
- MCPBridgeAgent capability mapping
- Admin DTO serialization
"""

from __future__ import annotations

import os
import pytest

# ---------------------------------------------------------------------------
# Database setup – use an in-memory SQLite database for tests
# ---------------------------------------------------------------------------

os.environ.setdefault("AGBUS_DB_URL", "sqlite:///:memory:")

from app.core.persistence.database import Base, get_engine
from app.core.persistence.models import MCPServerStatus


@pytest.fixture(autouse=True)
def _fresh_db():
    """Create a fresh in-memory database for each test."""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


# ===========================================================================
# MCPServerRepository tests
# ===========================================================================


class TestMCPServerRepository:
    """CRUD operations on MCP server bridge configurations."""

    def _repo(self):
        from app.core.persistence.mcp_server_repository import MCPServerRepository
        return MCPServerRepository()

    def test_create_and_get(self):
        repo = self._repo()
        mcp = repo.create(
            server_id="acme-tools",
            server_url="http://acme.example.com/mcp",
            agent_id="mcp-acme",
            transport="http",
            semantic_description="ACME toolkit",
        )
        assert mcp.server_id == "acme-tools"
        assert mcp.agent_id == "mcp-acme"
        assert mcp.status == MCPServerStatus.ACTIVE

        fetched = repo.get("acme-tools")
        assert fetched is not None
        assert fetched.server_url == "http://acme.example.com/mcp"

    def test_get_by_agent_id(self):
        repo = self._repo()
        repo.create(
            server_id="srv1",
            server_url="http://srv1.example.com/mcp",
            agent_id="agent-srv1",
        )
        result = repo.get_by_agent_id("agent-srv1")
        assert result is not None
        assert result.server_id == "srv1"

    def test_create_duplicate_server_id_raises(self):
        repo = self._repo()
        repo.create(server_id="dup", server_url="http://x", agent_id="a1")
        with pytest.raises(ValueError, match="already exists"):
            repo.create(server_id="dup", server_url="http://y", agent_id="a2")

    def test_create_duplicate_agent_id_raises(self):
        repo = self._repo()
        repo.create(server_id="s1", server_url="http://x", agent_id="shared-agent")
        with pytest.raises(ValueError, match="already in use"):
            repo.create(server_id="s2", server_url="http://y", agent_id="shared-agent")

    def test_list_all(self):
        repo = self._repo()
        repo.create(server_id="a", server_url="http://a", agent_id="ag-a")
        repo.create(
            server_id="b", server_url="http://b", agent_id="ag-b",
            status=MCPServerStatus.DISABLED,
        )
        assert len(repo.list_all()) == 2
        assert len(repo.list_all(status=MCPServerStatus.ACTIVE)) == 1
        assert len(repo.list_all(status=MCPServerStatus.DISABLED)) == 1

    def test_update(self):
        repo = self._repo()
        repo.create(server_id="upd", server_url="http://old", agent_id="ag-upd")
        updated = repo.update("upd", server_url="http://new", semantic_description="Updated")
        assert updated.server_url == "http://new"
        assert updated.semantic_description == "Updated"

    def test_update_tool_overrides(self):
        repo = self._repo()
        repo.create(server_id="ovr", server_url="http://x", agent_id="ag-ovr")
        overrides = {
            "my_tool": {
                "required_scopes": ["admin"],
                "estimated_cost": 0.5,
            }
        }
        updated = repo.update("ovr", tool_overrides=overrides)
        assert updated.tool_overrides_json["my_tool"]["required_scopes"] == ["admin"]

    def test_set_status(self):
        repo = self._repo()
        repo.create(server_id="st", server_url="http://x", agent_id="ag-st")
        mcp = repo.set_status("st", MCPServerStatus.DISABLED)
        assert mcp.status == MCPServerStatus.DISABLED

    def test_delete(self):
        repo = self._repo()
        repo.create(server_id="del", server_url="http://x", agent_id="ag-del")
        assert repo.delete("del") is True
        assert repo.get("del") is None
        assert repo.delete("del") is False

    def test_record_execution(self):
        repo = self._repo()
        repo.create(server_id="exec", server_url="http://x", agent_id="ag-exec")
        repo.record_execution("exec", latency_ms=100.0, success=True)
        repo.record_execution("exec", latency_ms=200.0, success=True)
        mcp = repo.get("exec")
        assert mcp.total_executions == 2
        assert mcp.mean_latency_ms == pytest.approx(150.0)
        assert mcp.last_execution_at is not None

    def test_record_execution_score(self):
        repo = self._repo()
        repo.create(server_id="score", server_url="http://x", agent_id="ag-score")
        # Initial current_score is 0.0 but record_execution uses (score or 0.5)
        # so effective starting score is 0.5. First success → 0.55
        repo.record_execution("score", latency_ms=50.0, success=True)
        mcp = repo.get("score")
        assert mcp.current_score == pytest.approx(0.55)
        # Failure reduces by 0.05 → 0.50
        repo.record_execution("score", latency_ms=50.0, success=False)
        mcp = repo.get("score")
        assert mcp.current_score == pytest.approx(0.50)


# ===========================================================================
# MCPServer ORM model tests
# ===========================================================================


class TestMCPServerModel:
    """Verify the MCPServer ORM model fields and defaults."""

    def test_defaults(self):
        from app.core.persistence.mcp_server_repository import MCPServerRepository
        repo = MCPServerRepository()
        mcp = repo.create(
            server_id="defaults",
            server_url="http://x",
            agent_id="ag-defaults",
        )
        assert mcp.transport == "http"
        assert mcp.mode == "persistent"
        assert mcp.command == ""
        assert mcp.args_json == []
        assert mcp.env_json == {}
        assert mcp.auth_headers_json == {}
        assert mcp.tool_overrides_json == {}
        assert mcp.total_executions == 0
        assert mcp.current_score == 0.0
        assert mcp.mean_latency_ms == 0.0

    def test_stdio_transport_fields(self):
        from app.core.persistence.mcp_server_repository import MCPServerRepository
        repo = MCPServerRepository()
        mcp = repo.create(
            server_id="stdio-srv",
            server_url="",
            agent_id="ag-stdio",
            transport="stdio",
            command="python",
            args=["-m", "my_mcp_server"],
            env={"MCP_API_KEY": "test-key"},
        )
        assert mcp.transport == "stdio"
        assert mcp.command == "python"
        assert mcp.args_json == ["-m", "my_mcp_server"]
        assert mcp.env_json == {"MCP_API_KEY": "test-key"}


# ===========================================================================
# Serializer tests
# ===========================================================================


class TestMCPServerSerializer:
    """Verify ORM → DTO conversion for MCP servers."""

    def test_basic_conversion(self):
        from app.core.persistence.mcp_server_repository import MCPServerRepository
        from app.coordinator.admin.serializers import mcp_server_to_dto

        repo = MCPServerRepository()
        mcp = repo.create(
            server_id="ser-test",
            server_url="http://test.example.com/mcp",
            agent_id="mcp-ser-test",
            semantic_description="Test server",
        )

        dto = mcp_server_to_dto(mcp)
        assert dto.server_id == "ser-test"
        assert dto.agent_id == "mcp-ser-test"
        assert dto.status == "active"
        assert dto.is_connected is False
        assert dto.discovered_tools == []

    def test_with_runtime_info(self):
        from app.core.persistence.mcp_server_repository import MCPServerRepository
        from app.coordinator.admin.serializers import mcp_server_to_dto

        repo = MCPServerRepository()
        mcp = repo.create(
            server_id="rt-test",
            server_url="http://x",
            agent_id="mcp-rt",
        )

        dto = mcp_server_to_dto(
            mcp,
            is_connected=True,
            discovered_tools=["search", "translate"],
        )
        assert dto.is_connected is True
        assert dto.discovered_tools == ["search", "translate"]

    def test_tool_overrides_conversion(self):
        from app.core.persistence.mcp_server_repository import MCPServerRepository
        from app.coordinator.admin.serializers import mcp_server_to_dto

        repo = MCPServerRepository()
        mcp = repo.create(
            server_id="ovr-test",
            server_url="http://x",
            agent_id="mcp-ovr",
            tool_overrides={
                "my_tool": {
                    "required_scopes": ["read:data"],
                    "estimated_cost": 0.1,
                }
            },
        )

        dto = mcp_server_to_dto(mcp)
        assert "my_tool" in dto.tool_overrides
        ovr = dto.tool_overrides["my_tool"]
        assert ovr.required_scopes == ["read:data"]
        assert ovr.estimated_cost == pytest.approx(0.1)


# ===========================================================================
# MCPBridgeAgent capability mapping tests
# ===========================================================================


class TestMCPBridgeCapabilityMapping:
    """Verify that MCPBridgeAgent correctly maps MCP tools to AgentCapability."""

    def _make_mcp_record(self, **overrides):
        """Create a minimal MCPServer-like object for testing."""
        from app.core.persistence.mcp_server_repository import MCPServerRepository
        repo = MCPServerRepository()
        defaults = dict(
            server_id="bridge-test",
            server_url="http://mcp.example.com",
            agent_id="mcp-bridge-test",
            semantic_description="Test bridge",
        )
        defaults.update(overrides)
        return repo.create(**defaults)

    def test_init_sets_agent_id(self):
        from app.agents.mcp_bridge import MCPBridgeAgent
        mcp = self._make_mcp_record()
        bridge = MCPBridgeAgent(mcp, coordinator_uri="ws://localhost:9999")
        assert bridge.agent_id == "mcp-bridge-test"

    def test_capabilities_empty_before_connect(self):
        from app.agents.mcp_bridge import MCPBridgeAgent
        mcp = self._make_mcp_record()
        bridge = MCPBridgeAgent(mcp)
        assert bridge.capabilities() == []


# ===========================================================================
# Schema DTO tests
# ===========================================================================


class TestMCPSchemas:
    """Verify Pydantic schemas for MCP server API."""

    def test_create_request_defaults(self):
        from app.coordinator.admin.schemas import MCPServerCreateRequest
        req = MCPServerCreateRequest(
            server_id="test",
            server_url="http://x",
            agent_id="ag-test",
        )
        assert req.transport == "http"
        assert req.mode == "persistent"
        assert req.activate is True
        assert req.tool_overrides == {}

    def test_update_request_all_optional(self):
        from app.coordinator.admin.schemas import MCPServerUpdateRequest
        req = MCPServerUpdateRequest()
        assert req.server_url is None
        assert req.transport is None
        assert req.tool_overrides is None

    def test_tool_override_dto(self):
        from app.coordinator.admin.schemas import MCPToolOverrideDTO
        ovr = MCPToolOverrideDTO(
            required_scopes=["admin"],
            estimated_cost=0.5,
            estimated_latency=200.0,
        )
        assert ovr.required_scopes == ["admin"]
        assert ovr.estimated_cost == 0.5

    def test_mcp_server_dto(self):
        from app.coordinator.admin.schemas import MCPServerDTO
        dto = MCPServerDTO(
            id=1,
            server_id="s1",
            server_url="http://x",
            transport="http",
            agent_id="ag-s1",
            status="active",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            created_by="admin",
        )
        assert dto.server_id == "s1"
        assert dto.is_connected is False  # default

    def test_dashboard_stats_includes_mcp(self):
        from app.coordinator.admin.schemas import DashboardStatsDTO
        stats = DashboardStatsDTO(
            total_agents=5,
            approved_agents=2,
            pending_agents=1,
            managed_agents=1,
            ephemeral_agents=0,
            mcp_servers=1,
            active_sessions=0,
            total_sessions_today=0,
            llm_provider="openai",
            llm_model="gpt-4",
        )
        assert stats.mcp_servers == 1
