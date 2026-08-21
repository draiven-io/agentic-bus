"""Dynamic LangGraph synthesis (§12 of AGENTS.md).

The coordinator MUST dynamically synthesise a LangGraph graph at runtime.
The graph is built only **after** IBAC validation and negotiation convergence.

Construction rules:
- Each selected agent becomes one or more nodes.
- Negotiation output determines the topology.
- Dependencies are derived from the intent decomposition.
- The coordinator can rebuild the graph if renegotiation occurs.

No static graphs.  No pre-declared DAGs.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, TypedDict

from langgraph.graph import StateGraph, START, END

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class AgBusGraphState(TypedDict, total=False):
    """State that flows through the dynamically synthesised execution graph."""

    session_id: str
    intent_text: str
    context: dict[str, Any]
    step_results: dict[str, Any]  # agent_id -> result
    errors: list[dict[str, Any]]
    metadata: dict[str, Any]


# Type for an agent execution callback
AgentExecutor = Callable[[AgBusGraphState], Coroutine[Any, Any, AgBusGraphState]]


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

class DynamicGraphBuilder:
    """Synthesises a LangGraph ``StateGraph`` from a negotiation composition plan.

    The builder takes the composition plan produced by the ``NegotiationEngine``
    and creates an executable graph where each node delegates to the
    corresponding provider agent.

    Parameters
    ----------
    agent_executors : dict
        Mapping of ``agent_id`` to an async callable that executes the agent's
        task and returns an updated ``AgBusGraphState``.
    """

    def __init__(
        self,
        agent_executors: dict[str, AgentExecutor] | None = None,
    ):
        self._executors: dict[str, AgentExecutor] = agent_executors or {}

    def register_executor(self, agent_id: str, executor: AgentExecutor) -> None:
        """Register an execution callback for an agent."""
        self._executors[agent_id] = executor

    def build(self, composition_plan: dict[str, Any]) -> StateGraph:
        """Build a LangGraph ``StateGraph`` from the composition plan.

        The plan is expected to have the shape::

            {
              "steps": [
                {"agent_id": "...", "capability_id": "...", "description": "...", "constraints": {...}},
                ...
              ],
              "viable": true
            }

        Dependencies between steps are implicitly sequential unless the plan
        contains explicit ``depends_on`` fields.
        """
        steps: list[dict[str, Any]] = composition_plan.get("steps", [])
        if not steps:
            raise ValueError("Cannot build graph from empty composition plan")

        graph = StateGraph(AgBusGraphState)

        # Create a node for each step
        node_names: list[str] = []
        for i, step in enumerate(steps):
            agent_id = step["agent_id"]
            node_name = f"step_{i}_{agent_id}"
            node_names.append(node_name)

            executor = self._executors.get(agent_id)
            if executor is None:
                # Create a placeholder node that records a missing-executor error
                executor = self._make_missing_executor(agent_id)

            # Wrap the executor to capture results keyed by agent_id
            wrapped = self._wrap_executor(agent_id, step, executor, step_index=i)
            graph.add_node(node_name, wrapped)

        # Wire edges: sequential chain by default
        if len(node_names) == 1:
            graph.add_edge(START, node_names[0])
            graph.add_edge(node_names[0], END)
        else:
            graph.add_edge(START, node_names[0])
            for a, b in zip(node_names[:-1], node_names[1:]):
                graph.add_edge(a, b)
            graph.add_edge(node_names[-1], END)

        logger.info(
            "Synthesised execution graph with %d nodes: %s",
            len(node_names),
            " → ".join(node_names),
        )
        return graph

    # -- internal helpers ----------------------------------------------------

    @staticmethod
    def _wrap_executor(
        agent_id: str,
        step: dict[str, Any],
        executor: AgentExecutor,
        *,
        step_index: int = 0,
    ) -> AgentExecutor:
        """Wrap an agent executor to store results in the graph state."""

        async def _node(state: AgBusGraphState) -> dict[str, Any]:
            try:
                # Inject the current step index so the executor (and events)
                # can distinguish between multiple invocations of the same agent.
                state_with_step = {**state, "_current_step_index": step_index}
                updated = await executor(state_with_step)
                results = dict(state.get("step_results", {}))
                results[agent_id] = updated.get("step_results", {}).get(agent_id, "ok")
                return {"step_results": results}
            except Exception as exc:
                errors = list(state.get("errors", []))
                errors.append(
                    {
                        "agent_id": agent_id,
                        "capability_id": step.get("capability_id", ""),
                        "error": str(exc),
                    }
                )
                return {"errors": errors}

        return _node  # type: ignore[return-value]

    @staticmethod
    def _make_missing_executor(agent_id: str) -> AgentExecutor:
        async def _missing(state: AgBusGraphState) -> AgBusGraphState:
            logger.error("No executor registered for agent %s", agent_id)
            errors = list(state.get("errors", []))
            errors.append(
                {
                    "agent_id": agent_id,
                    "error": f"No executor registered for agent '{agent_id}'",
                }
            )
            return {**state, "errors": errors}

        return _missing  # type: ignore[return-value]
