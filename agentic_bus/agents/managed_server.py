"""Managed Agent Server – standalone process for database-defined agents.

Each managed agent runs as an independent server process that connects to the
coordinator via WebSocket, just like any external (persistent/ephemeral) agent.
This architecture means:

- Every managed agent is a first-class bus citizen with its own lifecycle.
- The coordinator discovers, negotiates with, and delegates to managed agents
  exactly the same way it does for external agents.
- Agents can be started/stopped independently — enabling container-based
  scaling (Docker, K8s) without touching the coordinator.
- Crash isolation: a failing agent does not bring down the coordinator.

The server wraps a LangGraph ReAct agent behind the
Agentic Bus protocol handled by ``BaseAgent``.

Usage (programmatic)::

    from agentic_bus.agents.managed_server import run_managed_agent
    await run_managed_agent("translator")

Usage (CLI)::

    agbus agent start translator
    agbus agent stop translator
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from typing import Any

from agentic_bus.agents.base.agent import BaseAgent
from agentic_bus.agents.factory import (
    build_agent,
    capabilities_from_agent,
)
from agentic_bus.core.persistence.database import init_db
from agentic_bus.core.persistence.managed_agent_repository import ManagedAgentRepository
from agentic_bus.core.persistence.models import ManagedAgent, ManagedAgentStatus
from agentic_bus.core.registry.capability_registry import AgentCapability
from agentic_bus.core.llm import get_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation prompt for managed agents
# ---------------------------------------------------------------------------

_VALIDATION_SYSTEM = """\
You are a validation agent with the following identity:

**Role**: {role}
**Goal**: {goal}
**Backstory**: {backstory}

## IBAC Governance Rules
{ibac_rules}

## Your Task
You must validate whether the answer below correctly fulfils the original
intent.  Evaluate the answer against:

1. **Your expertise** – does the answer align with your role and goal?
2. **Completeness** – does it address all aspects of the intent?
3. **Accuracy** – does the information appear correct?
4. **IBAC compliance** – does the answer violate any of the governance rules
   listed above?  Even if the content seems technically correct, it MUST
   comply with all active IBAC rules.
5. **Quality** – is the answer well-structured and actionable?

Return ONLY a JSON object (no markdown fences, no commentary):
{{
  "approved": true or false,
  "reason": "one-sentence explanation of your decision",
  "suggestions": ["improvement suggestion 1", "..."]
}}

Be strict.  If IBAC rules are violated, you MUST reject.
If the answer is vague, incomplete, or off-topic, reject with clear suggestions.
"""

_VALIDATION_HUMAN = """\
Original intent: {intent_text}
Context: {context}

{prior_feedback_block}

Answer to validate:
{answer}
"""


def _final_text(state: dict[str, Any]) -> str:
    """Return the text of the last message in a LangGraph result."""
    messages = state.get("messages") or []
    if not messages:
        return ""
    content = getattr(messages[-1], "content", messages[-1])
    if isinstance(content, str):
        return content
    # Some providers return content as a list of typed blocks.
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


class ManagedAgentServer(BaseAgent):
    """A BaseAgent implementation backed by a LangGraph agent built from the database.

    On startup it:
    1. Loads the ``ManagedAgent`` record from the DB.
    2. Converts its capabilities into ``AgentCapability`` objects.
    3. Connects to the coordinator and registers (via ``BaseAgent.start``).
    4. Listens for intents/executions and delegates to the graph.

    The ``execute_task`` method builds the graph once and invokes it
    asynchronously (LangGraph is async-native, so unlike the CrewAI
    implementation it replaced there is no thread offload, and cancellation
    reaches the run rather than stopping at an executor boundary; the
    event loop isn't blocked).
    """

    def __init__(
        self,
        managed_agent: ManagedAgent,
        coordinator_uri: str = "ws://localhost:8765",
    ):
        self._ma = managed_agent
        self._caps = capabilities_from_agent(managed_agent)
        self._graph: Any = None  # LangGraph agent, built on first execution

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
        """Execute the task on a LangGraph ReAct agent.

        Previously this built a CrewAI ``Agent``, wrapped the intent in a
        ``Task`` and ran a single-agent ``Crew`` — whose ``kickoff()`` is
        synchronous, so it had to be pushed onto a thread. LangGraph is
        async-native, so the offload is gone and cancellation now propagates
        into the run rather than stopping at the executor boundary.
        """
        if self._graph is None:
            self._graph = build_agent(self._ma)
            logger.info("LangGraph agent built for %s", self.agent_id)

        intent_text = payload.get("intent_text", "")
        prior_results = payload.get("prior_results", {})

        expected_output = "A structured result fulfilling the intent."
        capability_description = ""
        if self._ma.capabilities:
            capability = self._ma.capabilities[0]
            capability_description = capability.description
            expected_output = capability.expected_output or expected_output

        instruction = "\n\n".join(
            part
            for part in (
                capability_description or intent_text,
                f"Original intent: {intent_text}" if capability_description else "",
                f"Context: {context}" if context else "",
                f"Prior step results: {prior_results}" if prior_results else "",
                f"Expected output: {expected_output}",
            )
            if part
        )

        state = await self._graph.ainvoke(
            {"messages": [{"role": "user", "content": instruction}]}
        )

        logger.info("Execution complete for %s", self.agent_id)

        result: dict[str, Any] = {
            "raw": _final_text(state),
            "agent_id": self.agent_id,
        }

        # Present when the capability declared output_fields, in which case
        # build_agent asked the graph for that exact shape.
        structured = state.get("structured_response")
        if structured is not None:
            result["json"] = (
                structured.model_dump()
                if hasattr(structured, "model_dump")
                else structured
            )

        return result

    # -- Answer validation (managed agents use LLM + role/goal/IBAC) -------

    async def validate_answer(
        self,
        answer: dict[str, Any],
        intent_text: str,
        context: dict[str, Any],
        ibac_rules_summary: str = "",
    ) -> dict[str, Any]:
        """Validate an execution answer using the agent's role, goal, backstory, and IBAC rules.

        Managed agents have rich identity information (role, goal, backstory)
        from their role/goal/backstory.  This method builds a validation
        prompt that incorporates all of that context plus any active IBAC
        rules, and asks the LLM to judge whether the answer is acceptable.
        """
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import JsonOutputParser

        # Serialise the answer
        if isinstance(answer, dict):
            answer_text = json.dumps(answer, default=str, indent=2)[:4000]
        else:
            answer_text = str(answer)[:4000]

        # Build prior feedback block from context
        prior_feedback = context.get("_validation_feedback", [])
        if prior_feedback:
            fb_lines = [
                f"Round {fb['round_num']}: REJECTED — {fb['reason']}\n"
                f"  Suggestions: {', '.join(fb.get('suggestions', []))}"
                for fb in prior_feedback
            ]
            prior_feedback_block = (
                "## Prior Validation Feedback (the answer was previously rejected):\n"
                + "\n".join(fb_lines)
            )
        else:
            prior_feedback_block = ""

        prompt = ChatPromptTemplate.from_messages([
            ("system", _VALIDATION_SYSTEM),
            ("human", _VALIDATION_HUMAN),
        ])
        parser = JsonOutputParser()

        try:
            llm = get_llm()
        except Exception:
            logger.warning(
                "No LLM configured — managed agent %s auto-approving validation",
                self.agent_id,
            )
            return {
                "approved": True,
                "reason": "No LLM configured — auto-approved.",
                "suggestions": [],
            }

        chain = prompt | llm | parser

        try:
            result = await chain.ainvoke({
                "role": self._ma.role,
                "goal": self._ma.goal,
                "backstory": self._ma.backstory,
                "ibac_rules": ibac_rules_summary or "(No IBAC rules configured.)",
                "intent_text": intent_text,
                "context": json.dumps(context, default=str)[:2000],
                "prior_feedback_block": prior_feedback_block,
                "answer": answer_text,
            })
            return {
                "approved": bool(result.get("approved", True)),
                "reason": result.get("reason", ""),
                "suggestions": result.get("suggestions", []),
            }
        except Exception:
            logger.exception(
                "Validation LLM call failed for agent %s — rejecting as precaution",
                self.agent_id,
            )
            return {
                "approved": False,
                "reason": "Validation failed due to an internal error — rejecting as a precaution.",
                "suggestions": ["Retry the validation."],
            }


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
