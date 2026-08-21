"""Agent SDK and examples.

Provides:
- ``BaseAgent`` – Base class for provider agents (agents that offer capabilities)
- ``IntentClient`` – High-level client for requester agents (agents that submit intentions)
- ``MCPBridgeAgent`` – Bridge for connecting external MCP servers to the bus

``MCPBridgeAgent`` is resolved lazily: it reads MCP server records from the
database, so importing it pulls in SQLAlchemy and the rest of the server
stack. Importing it eagerly here would make ``from agentic_bus import
BaseAgent`` fail on a base install, which is exactly the weight the split
between the base package and the ``[server]`` extra exists to avoid.
"""

from typing import TYPE_CHECKING, Any

from agentic_bus.agents.base.agent import BaseAgent
from agentic_bus.agents.requester import IntentClient, IntentResult, submit_intent

if TYPE_CHECKING:  # import for type checkers only — never at runtime
    from agentic_bus.agents.mcp_bridge import MCPBridgeAgent

__all__ = [
    "BaseAgent",
    "IntentClient",
    "IntentResult",
    "MCPBridgeAgent",
    "submit_intent",
]


def __getattr__(name: str) -> Any:
    """Resolve ``MCPBridgeAgent`` on first access (PEP 562)."""
    if name == "MCPBridgeAgent":
        from agentic_bus.agents.mcp_bridge import MCPBridgeAgent

        return MCPBridgeAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
