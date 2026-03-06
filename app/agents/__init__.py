"""Agent SDK and examples.

Provides:
- ``BaseAgent`` – Base class for provider agents (agents that offer capabilities)
- ``IntentClient`` – High-level client for requester agents (agents that submit intentions)
- ``MCPBridgeAgent`` – Bridge for connecting external MCP servers to the bus
"""

from app.agents.base.agent import BaseAgent
from app.agents.requester import IntentClient, IntentResult, submit_intent
from app.agents.mcp_bridge import MCPBridgeAgent

__all__ = [
    "BaseAgent",
    "IntentClient",
    "IntentResult",
    "MCPBridgeAgent",
    "submit_intent",
]
