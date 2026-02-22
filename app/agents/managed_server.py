"""Managed Agent Server – standalone process for CrewAI-backed agents.

Each managed agent runs as an independent server process that connects to the
coordinator via WebSocket, just like any external (persistent/ephemeral) agent.
This architecture means:

- Every managed agent is a first-class bus citizen with its own lifecycle.
- The coordinator discovers, negotiates with, and delegates to managed agents
  exactly the same way it does for external agents.
- Agents can be started/stopped independently — enabling container-based
  scaling (Docker, K8s) without touching the coordinator.
- Crash isolation: a failing agent does not bring down the coordinator.

The server wraps a CrewAI ``Agent`` + ``Task`` + ``Crew`` execution behind the
Agentic Bus protocol handled by ``BaseAgent``.

Usage (programmatic)::

    from app.agents.managed_server import run_managed_agent
    await run_managed_agent("translator")

Usage (CLI)::

    agbus agent start translator
    agbus agent stop translator
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Any

from app.agents.base.agent import BaseAgent
from app.agents.factory import (
    build_crewai_agent,
    build_output_model,
    capabilities_from_agent,
)
from app.core.persistence.database import init_db
from app.core.persistence.managed_agent_repository import ManagedAgentRepository
from app.core.persistence.models import ManagedAgent, ManagedAgentStatus
from app.core.registry.capability_registry import AgentCapability

logger = logging.getLogger(__name__)


class ManagedAgentServer(BaseAgent):
    """A BaseAgent implementation backed by a CrewAI agent from the database.

    On startup it:
    1. Loads the ``ManagedAgent`` record from the DB.
    2. Converts its capabilities into ``AgentCapability`` objects.
    3. Connects to the coordinator and registers (via ``BaseAgent.start``).
    4. Listens for intents/executions and delegates to CrewAI.

    The ``execute_task`` method builds a CrewAI ``Task`` and ``Crew`` on the
    fly and kicks off execution synchronously (via ``run_in_executor`` so the
    event loop isn't blocked).
    """

    def __init__(
        self,
        managed_agent: ManagedAgent,
        coordinator_uri: str = "ws://localhost:8765",
    ):
        self._ma = managed_agent
        self._caps = capabilities_from_agent(managed_agent)
        self._crew_agent: Any = None  # lazily built

        super().__init__(
            agent_id=managed_agent.agent_id,
            coordinator_uri=coordinator_uri,
            version="managed-1.0",
            semantic_description=(
                f"{managed_agent.role}. {managed_agent.goal}"
                if managed_agent.goal
                else managed_agent.role
            ),
        )

    # -- BaseAgent abstract methods -----------------------------------------

    def capabilities(self) -> list[AgentCapability]:
        return self._caps

    async def execute_task(
        self,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute via CrewAI.

        Builds (or reuses) the ``crewai.Agent``, wraps the intent in a
        ``crewai.Task``, and runs a single-agent ``Crew``.
        """
        # Lazy-build the CrewAI agent (first execution)
        if self._crew_agent is None:
            self._crew_agent = build_crewai_agent(self._ma)
            logger.info("CrewAI agent built for %s", self.agent_id)

        try:
            from crewai import Task as CrewTask, Crew
        except ImportError as exc:
            raise RuntimeError(
                "CrewAI is required for managed agents. "
                "Install with: pip install crewai"
            ) from exc

        intent_text = payload.get("intent_text", "")
        prior_results = payload.get("prior_results", {})

        # Pick the best capability description as task description
        cap_desc = ""
        expected_output = "A structured result fulfilling the intent."
        output_pydantic = None
        if self._ma.capabilities:
            cap = self._ma.capabilities[0]
            cap_desc = cap.description
            expected_output = cap.expected_output or expected_output

            # Build a dynamic Pydantic model if output fields are defined
            output_fields = cap.output_fields_json or []
            if output_fields:
                try:
                    output_pydantic = build_output_model(
                        cap.capability_id, output_fields,
                    )
                except (ValueError, Exception) as exc:
                    logger.warning(
                        "Could not build output model for %s: %s",
                        cap.capability_id,
                        exc,
                    )

        task_description = cap_desc or intent_text

        task_kwargs: dict[str, Any] = {
            "description": (
                f"{task_description}\n\n"
                f"Original intent: {intent_text}\n"
                f"Context: {context}\n"
                f"Prior step results: {prior_results}"
            ),
            "expected_output": expected_output,
            "agent": self._crew_agent,
        }
        if output_pydantic is not None:
            task_kwargs["output_pydantic"] = output_pydantic

        task = CrewTask(**task_kwargs)

        crew = Crew(
            agents=[self._crew_agent],
            tasks=[task],
            verbose=self._ma.verbose,
        )

        # CrewAI's kickoff() is synchronous – offload to a thread
        loop = asyncio.get_running_loop()
        crew_result = await loop.run_in_executor(None, crew.kickoff)

        logger.info(
            "CrewAI execution complete for %s (session context omitted)",
            self.agent_id,
        )

        result: dict[str, Any] = {
            "raw": str(crew_result),
            "agent_id": self.agent_id,
        }

        # When the task was configured with output_pydantic, CrewAI parses
        # the LLM response into the Pydantic model.  Extract the validated
        # dict so callers get predictable, typed JSON.
        if output_pydantic is not None and hasattr(crew_result, "pydantic"):
            pydantic_obj = crew_result.pydantic
            if pydantic_obj is not None:
                result["json"] = pydantic_obj.model_dump()

        return result


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

async def run_managed_agent(
    agent_id: str,
    coordinator_uri: str | None = None,
) -> None:
    """Load a managed agent from the DB and run it as a standalone server.

    This is the main entry-point called by ``agbus agent start <id>``.
    """
    init_db()
    repo = ManagedAgentRepository()
    ma = repo.get(agent_id)
    if ma is None:
        logger.error("Managed agent %r not found in database", agent_id)
        sys.exit(1)

    if ma.status != ManagedAgentStatus.ACTIVE:
        logger.error(
            "Managed agent %r is not active (status=%s). "
            "Activate it first with: agbus agent activate %s",
            agent_id,
            ma.status,
            agent_id,
        )
        sys.exit(1)

    uri = coordinator_uri or os.getenv("AGBUS_WS_URI", "ws://localhost:8765")

    server = ManagedAgentServer(ma, coordinator_uri=uri)

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(server.stop()))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for all signals
            pass

    logger.info(
        "Starting managed agent %r (role=%r) → %s",
        agent_id,
        ma.role,
        uri,
    )
    await server.run_forever()


def run_managed_agent_sync(
    agent_id: str,
    coordinator_uri: str | None = None,
) -> None:
    """Synchronous wrapper for ``run_managed_agent`` (used by CLI / subprocess)."""
    asyncio.run(run_managed_agent(agent_id, coordinator_uri))
