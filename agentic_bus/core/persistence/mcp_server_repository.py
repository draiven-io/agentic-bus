"""Repository for MCP server bridge CRUD.

MCP servers are external services that expose tools via the Model Context
Protocol.  The bridge agent connects to them and maps their tools into
Agentic Bus capabilities so they participate in the full bus lifecycle
(discovery, negotiation, IBAC, execution).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agentic_bus.core.persistence.database import get_session
from agentic_bus.core.persistence.models import MCPServer, MCPServerStatus

logger = logging.getLogger(__name__)


class MCPServerNotFoundError(Exception):
    """Raised when a referenced MCP server does not exist."""


class MCPServerRepository:
    """CRUD operations for MCP server bridge configurations."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        server_id: str,
        server_url: str,
        agent_id: str,
        *,
        transport: str = "http",
        auth_headers: dict[str, str] | None = None,
        command: str = "",
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        semantic_description: str = "",
        mode: str = "persistent",
        tool_overrides: dict[str, dict[str, Any]] | None = None,
        status: MCPServerStatus = MCPServerStatus.ACTIVE,
        created_by: str = "admin",
    ) -> MCPServer:
        """Register a new MCP server bridge.

        Parameters
        ----------
        server_id:
            Unique identifier for this MCP server config (e.g. ``"acme-tools"``).
        server_url:
            URL of the MCP server endpoint (e.g. ``"http://tools.acme.com/mcp"``).
        agent_id:
            How this MCP server appears on the bus as an agent.
        transport:
            MCP transport type: ``"http"`` (Streamable HTTP) or ``"stdio"``.
        auth_headers:
            HTTP headers for authenticated connections (e.g. Bearer tokens).
        command:
            Command to launch stdio MCP server (e.g. ``"python"``).
        args:
            Arguments for the stdio command.
        env:
            Extra environment variables for the stdio subprocess.
        semantic_description:
            Free-text description used by the semantic adjudicator.
        mode:
            Registration mode on the bus: ``"ephemeral"`` or ``"persistent"``.
        tool_overrides:
            Per-tool bus metadata overrides keyed by MCP tool name.
        """
        with get_session() as session:
            existing = (
                session.query(MCPServer)
                .filter(
                    (MCPServer.server_id == server_id)
                    | (MCPServer.agent_id == agent_id)
                )
                .first()
            )
            if existing is not None:
                if existing.server_id == server_id:
                    raise ValueError(f"MCP server {server_id!r} already exists")
                raise ValueError(f"Agent ID {agent_id!r} is already in use")

            mcp = MCPServer(
                server_id=server_id,
                server_url=server_url,
                transport=transport,
                auth_headers_json=auth_headers or {},
                command=command,
                args_json=args or [],
                env_json=env or {},
                agent_id=agent_id,
                semantic_description=semantic_description,
                mode=mode,
                tool_overrides_json=tool_overrides or {},
                status=status,
                created_by=created_by,
            )
            session.add(mcp)
            session.commit()
            session.refresh(mcp)
            logger.info("Created MCP server bridge %r → agent %r", server_id, agent_id)
            return mcp

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, server_id: str) -> MCPServer | None:
        """Return a single MCP server by its server_id."""
        with get_session() as session:
            return (
                session.query(MCPServer)
                .filter(MCPServer.server_id == server_id)
                .first()
            )

    def get_by_agent_id(self, agent_id: str) -> MCPServer | None:
        """Return a single MCP server by its bus agent_id."""
        with get_session() as session:
            return (
                session.query(MCPServer)
                .filter(MCPServer.agent_id == agent_id)
                .first()
            )

    def list_all(
        self, status: MCPServerStatus | None = None
    ) -> list[MCPServer]:
        """Return all MCP servers, optionally filtered by status."""
        with get_session() as session:
            q = session.query(MCPServer)
            if status is not None:
                q = q.filter(MCPServer.status == status)
            return q.order_by(MCPServer.server_id).all()

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        server_id: str,
        **kwargs: Any,
    ) -> MCPServer:
        """Update fields on an existing MCP server config."""
        # Map user-friendly names to JSON column names
        column_map = {
            "auth_headers": "auth_headers_json",
            "args": "args_json",
            "env": "env_json",
            "tool_overrides": "tool_overrides_json",
        }

        with get_session() as session:
            mcp = (
                session.query(MCPServer)
                .filter(MCPServer.server_id == server_id)
                .first()
            )
            if mcp is None:
                raise MCPServerNotFoundError(f"MCP server {server_id!r} not found")

            for key, value in kwargs.items():
                if value is None:
                    continue
                col_name = column_map.get(key, key)
                if hasattr(mcp, col_name):
                    setattr(mcp, col_name, value)
                else:
                    logger.warning("Unknown MCPServer field: %s", key)

            mcp.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(mcp)
            logger.info("Updated MCP server %r", server_id)
            return mcp

    def set_status(self, server_id: str, status: MCPServerStatus) -> MCPServer:
        """Change the status of an MCP server."""
        return self.update(server_id, status=status)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, server_id: str) -> bool:
        """Permanently remove an MCP server config."""
        with get_session() as session:
            mcp = (
                session.query(MCPServer)
                .filter(MCPServer.server_id == server_id)
                .first()
            )
            if mcp is None:
                return False
            session.delete(mcp)
            session.commit()
            logger.info("Deleted MCP server %r", server_id)
            return True

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def record_execution(
        self,
        server_id: str,
        latency_ms: float,
        success: bool,
    ) -> None:
        """Update execution statistics after a tool call completes."""
        with get_session() as session:
            mcp = (
                session.query(MCPServer)
                .filter(MCPServer.server_id == server_id)
                .first()
            )
            if mcp is None:
                return

            n = mcp.total_executions
            mcp.total_executions = n + 1
            # Running average for latency
            if n == 0:
                mcp.mean_latency_ms = latency_ms
            else:
                mcp.mean_latency_ms = (mcp.mean_latency_ms * n + latency_ms) / (n + 1)
            # Simple score update
            delta = 0.05 if success else -0.05
            mcp.current_score = max(0.0, min(1.0, (mcp.current_score or 0.5) + delta))
            mcp.last_execution_at = datetime.now(timezone.utc)
            session.commit()
