"""The ``agentic_bus`` public API is a contract with agent authors.

Two things must hold, and neither is obvious enough to survive refactoring
without a test:

1. The documented names are importable from the top-level package.
2. Importing it does **not** drag in the coordinator's dependency stack.

(2) is the whole reason the base install is separate from ``[server]``. It is
easy to break by accident — one eager ``from agentic_bus.core.persistence...``
in a re-exported module is enough — and it would not show up anywhere else,
because the development environment has every extra installed.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

#: Everything the README promises an agent author can import.
PUBLIC_NAMES = [
    "BaseAgent",
    "AgentCapability",
    "AgentRegistration",
    "ReconnectPolicy",
    "TokenProvider",
    "IntentClient",
    "IntentResult",
    "PlanDecision",
    "submit_intent",
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
    "LIP_PROTOCOL_VERSION",
    "__version__",
]

#: Third-party packages that only ``[server]`` installs. None of them may be
#: imported as a side effect of importing the base package.
SERVER_ONLY_MODULES = [
    "sqlalchemy",
    "fastapi",
    "uvicorn",
    "langchain",
    "langchain_core",
    "langgraph",
    "jwt",
]


class TestPublicSurface:
    def test_documented_names_are_importable(self):
        import agentic_bus

        missing = [n for n in PUBLIC_NAMES if not hasattr(agentic_bus, n)]
        assert missing == [], f"missing from agentic_bus: {missing}"

    def test_all_matches_the_documented_names(self):
        import agentic_bus

        assert sorted(agentic_bus.__all__) == sorted(PUBLIC_NAMES)

    def test_writing_an_agent_needs_only_the_public_api(self):
        """The README's hello-agent, compiled and instantiated."""
        from agentic_bus import AgentCapability, BaseAgent

        class WeatherAgent(BaseAgent):
            def capabilities(self):
                return [
                    AgentCapability(
                        capability_id="forecast",
                        description="Weather forecast for a city",
                    )
                ]

            async def execute_task(self, payload, context):
                return {"forecast": "sunny"}

        agent = WeatherAgent(agent_id="weather-01")
        assert agent.agent_id == "weather-01"
        assert [c.capability_id for c in agent.capabilities()] == ["forecast"]


class TestBaseInstallStaysLight:
    """Guards the base-install / [server] split.

    Run in a subprocess: this interpreter has already imported most of the
    server stack via other tests, so ``sys.modules`` here proves nothing.
    """

    @staticmethod
    def _modules_loaded_by(statement: str) -> set[str]:
        code = (
            "import sys, json\n"
            f"{statement}\n"
            "print(json.dumps(sorted(sys.modules)))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        import json

        return set(json.loads(result.stdout))

    def test_importing_the_package_pulls_no_server_dependencies(self):
        loaded = self._modules_loaded_by("import agentic_bus")
        leaked = sorted(m for m in SERVER_ONLY_MODULES if m in loaded)
        assert leaked == [], (
            f"importing agentic_bus loaded server-only modules: {leaked}. "
            "Something in the public API imports the coordinator stack "
            "eagerly; make it lazy or drop it from the re-exports."
        )

    def test_importing_the_agents_package_pulls_no_server_dependencies(self):
        """``MCPBridgeAgent`` needs SQLAlchemy, so it must stay lazy."""
        loaded = self._modules_loaded_by("import agentic_bus.agents")
        leaked = sorted(m for m in SERVER_ONLY_MODULES if m in loaded)
        assert leaked == [], f"agentic_bus.agents loaded: {leaked}"

    @pytest.mark.parametrize("name", ["BaseAgent", "IntentClient", "AgentCapability"])
    def test_core_sdk_types_resolve_without_the_server_stack(self, name):
        loaded = self._modules_loaded_by(f"from agentic_bus import {name}")
        leaked = sorted(m for m in SERVER_ONLY_MODULES if m in loaded)
        assert leaked == [], f"importing {name} loaded: {leaked}"


class TestLazyMCPBridge:
    def test_mcp_bridge_is_still_reachable(self):
        """Lazy must not mean gone — the name still resolves on access."""
        from agentic_bus.agents import MCPBridgeAgent

        assert MCPBridgeAgent.__name__ == "MCPBridgeAgent"

    def test_unknown_attribute_still_raises(self):
        import agentic_bus.agents as agents

        with pytest.raises(AttributeError):
            agents.NoSuchThing
