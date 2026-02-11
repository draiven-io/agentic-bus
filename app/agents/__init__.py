"""Agent SDK and examples.

Provides:
- ``BaseAgent`` – Base class for provider agents (agents that offer capabilities)
- ``IntentClient`` – High-level client for requester agents (agents that submit intentions)
"""

from app.agents.base.agent import BaseAgent
from app.agents.requester import IntentClient, IntentResult, submit_intent

__all__ = [
    "BaseAgent",
    "IntentClient",
    "IntentResult",
    "submit_intent",
]
