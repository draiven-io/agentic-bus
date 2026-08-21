"""Agentic Bus — reference implementation of the Liquid Interfaces Protocol.

This module is the **agent-author API**. Everything exported here works with
the base install::

    pip install agentic-bus

and needs only pydantic, websockets and OpenTelemetry — no web framework, no
database, no LLM stack. Writing an agent looks like this::

    from agentic_bus import AgentCapability, BaseAgent

    class WeatherAgent(BaseAgent):
        def capabilities(self):
            return [AgentCapability(capability_id="forecast",
                                    description="Weather forecast by city")]

        async def execute_task(self, payload, context):
            return {"forecast": "sunny"}

Running a *coordinator* is a different job with a much heavier dependency
set, so it lives behind an extra::

    pip install "agentic-bus[server]"

Nothing under ``agentic_bus.coordinator`` or ``agentic_bus.core.persistence``
is importable without it, and none of it is re-exported here — that is what
keeps this import light.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from agentic_bus.agents.base.agent import BaseAgent, ReconnectPolicy, TokenProvider
from agentic_bus.agents.requester import (
    IntentClient,
    IntentResult,
    PlanDecision,
    submit_intent,
)
from agentic_bus.core.protocol.envelope import (
    LIP_PROTOCOL_VERSION,
    AcceptPayload,
    AgBusEnvelope,
    CompletePayload,
    DissolvePayload,
    EventPayload,
    ExecutePayload,
    IntentPayload,
    MessageType,
    OfferPayload,
    RejectPayload,
    SenderInfo,
    SenderKind,
    TraceContext,
    build_envelope,
)
from agentic_bus.core.registry.capability_registry import (
    AgentCapability,
    AgentRegistration,
)

try:
    __version__ = _pkg_version("agentic-bus")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0.dev0"

__all__ = [
    # Version
    "__version__",
    "LIP_PROTOCOL_VERSION",
    # Writing a provider agent
    "BaseAgent",
    "AgentCapability",
    "AgentRegistration",
    "ReconnectPolicy",
    "TokenProvider",
    # Submitting intents
    "IntentClient",
    "IntentResult",
    "PlanDecision",
    "submit_intent",
    # Protocol
    "AgBusEnvelope",
    "MessageType",
    "SenderInfo",
    "SenderKind",
    "TraceContext",
    "build_envelope",
    "IntentPayload",
    "OfferPayload",
    "AcceptPayload",
    "RejectPayload",
    "ExecutePayload",
    "CompletePayload",
    "DissolvePayload",
    "EventPayload",
]
