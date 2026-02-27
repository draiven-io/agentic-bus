"""MCP Bridge Agent – connects external MCP servers to the Agentic Bus.

An MCP server exposes *tools* via the Model Context Protocol.  The bridge:

1. Connects to an MCP server (Streamable HTTP or stdio transport).
2. Discovers all available tools via ``session.list_tools()``.
3. Maps each MCP tool to an ``AgentCapability`` — merging auto-derived
   metadata (name, description, schema) with admin-provided bus overrides
   (IBAC scopes, cost, data domains).
4. Registers on the bus as a standard ``BaseAgent``, participating in
   discovery, negotiation, IBAC governance, and execution.
5. Routes ``execute_task`` calls to the appropriate MCP ``call_tool``.

This means any MCP-compliant server — whether it's a local script, a
remote HTTP service, or a third-party tool provider — can participate
in the Agentic Bus lifecycle without any modifications.

Usage (programmatic)::

    from app.agents.mcp_bridge import MCPBridgeAgent
    bridge = MCPBridgeAgent(mcp_server_record)
    await bridge.run_forever()

Usage (coordinator-managed)::

    The coordinator auto-starts bridge agents for all active MCPServer
    records in the database, just like it does for managed CrewAI agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.agents.base.agent import BaseAgent
from app.core.registry.capability_registry import AgentCapability
from app.core.persistence.models import MCPServer

logger = logging.getLogger(__name__)


class MCPBridgeAgent(BaseAgent):
    """A BaseAgent backed by an external MCP server.

    On startup it:
    1. Connects to the MCP server and discovers tools.
    2. Converts tools into ``AgentCapability`` objects (with admin overrides).
    3. Connects to the coordinator and registers (via ``BaseAgent.start``).
    4. Listens for intents/executions and delegates to MCP ``call_tool``.
    """

    def __init__(
        self,
        mcp_server: MCPServer,
        coordinator_uri: str = "ws://localhost:8765",
    ):
        self._mcp = mcp_server
        self._caps: list[AgentCapability] = []
        self._tool_names: list[str] = []
        # MCP client (MultiServerMCPClient) — created on start
        self._mcp_client: Any = None

        super().__init__(
            agent_id=mcp_server.agent_id,
            coordinator_uri=coordinator_uri,
            version="mcp-bridge-1.0",
            semantic_description=mcp_server.semantic_description or "",
        )

    # -- BaseAgent abstract methods -----------------------------------------

    def capabilities(self) -> list[AgentCapability]:
        return self._caps

    async def execute_task(
        self,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute via MCP tool call.

        The coordinator sends the intent text and prior results.  The bridge
        selects the best-matching tool and calls it via MCP.
        """
        from langchain_mcp_adapters.tools import load_mcp_tools

        intent_text = payload.get("intent_text", "")
        prior_results = payload.get("prior_results", {})

        # Determine which tool to call.
        # If there's only one tool, use it directly.
        # Otherwise, pick based on the capability_id hint in the payload.
        target_tool = self._pick_tool(payload)

        if not target_tool:
            return {
                "error": "No matching MCP tool found for this task",
                "agent_id": self.agent_id,
            }

        # Build arguments from the intent
        tool_args = self._build_tool_args(target_tool, intent_text, prior_results, context)

        start_time = time.monotonic()
        try:
            async with self._mcp_client.session(self._mcp.server_id) as session:
                result = await session.call_tool(target_tool, arguments=tool_args)

            elapsed_ms = (time.monotonic() - start_time) * 1000

            # Parse result content
            output = self._parse_mcp_result(result)

            logger.info(
                "MCP tool '%s' on server '%s' completed in %.0fms",
                target_tool, self._mcp.server_id, elapsed_ms,
            )

            # Record stats (best-effort)
            try:
                from app.core.persistence.mcp_server_repository import MCPServerRepository
                MCPServerRepository().record_execution(
                    self._mcp.server_id, elapsed_ms, success=True,
                )
            except Exception:
                pass

            return {
                "result": output,
                "tool": target_tool,
                "agent_id": self.agent_id,
                "latency_ms": round(elapsed_ms, 1),
            }
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.exception(
                "MCP tool '%s' on server '%s' failed", target_tool, self._mcp.server_id,
            )
            try:
                from app.core.persistence.mcp_server_repository import MCPServerRepository
                MCPServerRepository().record_execution(
                    self._mcp.server_id, elapsed_ms, success=False,
                )
            except Exception:
                pass
            return {
                "error": str(exc),
                "tool": target_tool,
                "agent_id": self.agent_id,
            }

    # -- Lifecycle overrides ------------------------------------------------

    async def start(self) -> None:
        """Connect to the MCP server, discover tools, then connect to the bus."""
        await self._connect_mcp()
        await self._discover_tools()
        await super().start()

    async def stop(self) -> None:
        """Disconnect from both the bus and the MCP server."""
        await super().stop()
        self._mcp_client = None

    # -- MCP connection and discovery ---------------------------------------

    async def _connect_mcp(self) -> None:
        """Create the MCP client connection."""
        from langchain_mcp_adapters.client import MultiServerMCPClient

        transport = self._mcp.transport or "http"
        config: dict[str, Any] = {}

        if transport in ("http", "streamable_http", "sse"):
            config = {
                "transport": "http",
                "url": self._mcp.server_url,
            }
            headers = self._mcp.auth_headers_json or {}
            if headers:
                config["headers"] = headers
        elif transport == "stdio":
            config = {
                "transport": "stdio",
                "command": self._mcp.command or "python",
                "args": self._mcp.args_json or [],
            }
            env = self._mcp.env_json or {}
            if env:
                config["env"] = env
        else:
            raise ValueError(f"Unsupported MCP transport: {transport}")

        self._mcp_client = MultiServerMCPClient({
            self._mcp.server_id: config,
        })

        logger.info(
            "MCP client configured for server '%s' (%s transport → %s)",
            self._mcp.server_id,
            transport,
            self._mcp.server_url if transport != "stdio" else self._mcp.command,
        )

    async def _discover_tools(self) -> None:
        """Discover MCP tools and convert them to AgentCapability objects."""
        try:
            tools = await self._mcp_client.get_tools()
        except Exception:
            logger.exception(
                "Failed to discover tools from MCP server '%s'", self._mcp.server_id,
            )
            self._caps = []
            self._tool_names = []
            return

        overrides = self._mcp.tool_overrides_json or {}
        capabilities: list[AgentCapability] = []

        for tool in tools:
            tool_name = tool.name
            tool_desc = tool.description or ""
            self._tool_names.append(tool_name)

            # Extract output schema from MCP tool (if available)
            output_schema: dict[str, Any] = {}
            if hasattr(tool, "response_format") and tool.response_format:
                output_schema = (
                    tool.response_format
                    if isinstance(tool.response_format, dict)
                    else {}
                )

            # Merge with admin-provided overrides
            tool_ov = overrides.get(tool_name, {})

            cap = AgentCapability(
                capability_id=f"mcp:{self._mcp.server_id}:{tool_name}",
                description=tool_ov.get("description", tool_desc),
                required_scopes=tool_ov.get("required_scopes", []),
                supported_data_domains=tool_ov.get("supported_data_domains", []),
                operational_constraints=tool_ov.get("operational_constraints", {}),
                expected_artifacts=tool_ov.get("expected_artifacts", []),
                estimated_cost=tool_ov.get("estimated_cost", 0.0),
                estimated_latency=tool_ov.get("estimated_latency", 0.0),
                output_schema=tool_ov.get("output_schema", output_schema),
            )
            capabilities.append(cap)

        self._caps = capabilities

        logger.info(
            "Discovered %d MCP tool(s) from server '%s': %s",
            len(capabilities),
            self._mcp.server_id,
            ", ".join(self._tool_names),
        )

    # -- Tool selection and argument building --------------------------------

    def _pick_tool(self, payload: dict[str, Any]) -> str | None:
        """Select the MCP tool to invoke for this execution.

        Strategy:
        1. If ``capability_id`` is in the payload, extract the tool name from it.
        2. If only one tool exists, use it.
        3. Fall back to the first tool (the coordinator's semantic adjudicator
           already chose this agent for the right capability).
        """
        cap_id = payload.get("capability_id", "")

        # capability_id format: "mcp:<server_id>:<tool_name>"
        if cap_id and cap_id.startswith("mcp:"):
            parts = cap_id.split(":", 2)
            if len(parts) == 3:
                tool_name = parts[2]
                if tool_name in self._tool_names:
                    return tool_name

        # Check prior_results or context for a hint
        context = payload.get("context", {})
        hint = context.get("mcp_tool") or context.get("tool_name", "")
        if hint and hint in self._tool_names:
            return hint

        # Single tool → use it
        if len(self._tool_names) == 1:
            return self._tool_names[0]

        # Fallback to first tool
        return self._tool_names[0] if self._tool_names else None

    @staticmethod
    def _build_tool_args(
        tool_name: str,
        intent_text: str,
        prior_results: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the arguments dict for an MCP tool call.

        MCP tools expect keyword arguments matching their ``inputSchema``.
        Since we don't know the exact schema at this point, we pass the
        intent text as a generic input and include context/prior results
        as supplementary fields.

        If the context contains an explicit ``mcp_tool_args`` dict, we
        use that instead (allows callers to pass structured arguments).
        """
        explicit_args = context.get("mcp_tool_args")
        if isinstance(explicit_args, dict):
            return explicit_args

        # Generic fallback: pass intent and context as top-level args.
        # Well-designed MCP tools will typically accept a 'query', 'input',
        # or 'message' parameter.
        args: dict[str, Any] = {}
        if intent_text:
            args["query"] = intent_text
            args["input"] = intent_text

        if prior_results:
            args["context"] = json.dumps(prior_results, default=str)[:4000]

        return args

    @staticmethod
    def _parse_mcp_result(result: Any) -> Any:
        """Extract usable output from an MCP CallToolResult."""
        # Check for structured content first
        if hasattr(result, "structuredContent") and result.structuredContent:
            return result.structuredContent

        # Fall back to text content
        if hasattr(result, "content"):
            contents = result.content
            if isinstance(contents, list):
                texts = []
                for c in contents:
                    if hasattr(c, "text"):
                        texts.append(c.text)
                    elif isinstance(c, str):
                        texts.append(c)
                return "\n".join(texts) if texts else str(contents)
            if isinstance(contents, str):
                return contents

        return str(result)

    # -- Rediscovery (admin can trigger this to pick up new tools) ----------

    async def rediscover_tools(self) -> int:
        """Re-discover tools from the MCP server and update capabilities.

        Returns the number of tools discovered.  Call this after the MCP
        server has been updated with new tools.
        """
        await self._discover_tools()
        # Re-register with the coordinator so the new capabilities are known
        await self._register()
        return len(self._caps)
