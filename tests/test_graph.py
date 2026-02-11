"""Tests for the dynamic graph builder."""

import pytest
from app.coordinator.graph.builder import DynamicGraphBuilder, AgBusGraphState


class TestDynamicGraphBuilder:
    def test_empty_plan_raises(self):
        builder = DynamicGraphBuilder()
        with pytest.raises(ValueError, match="empty composition plan"):
            builder.build({"steps": [], "viable": True})

    def test_single_step_graph(self):
        """A single-step plan produces a START → step → END graph."""
        results = {}

        async def mock_executor(state: AgBusGraphState) -> AgBusGraphState:
            r = dict(state.get("step_results", {}))
            r["agent-1"] = "done"
            return {**state, "step_results": r}

        builder = DynamicGraphBuilder(agent_executors={"agent-1": mock_executor})
        plan = {
            "steps": [
                {
                    "agent_id": "agent-1",
                    "capability_id": "cap-1",
                    "description": "Do something",
                    "constraints": {},
                }
            ],
            "viable": True,
        }
        graph = builder.build(plan)
        # Verify the graph compiled without error
        compiled = graph.compile()
        assert compiled is not None

    def test_multi_step_graph(self):
        """Multi-step plans produce a sequential chain."""

        async def noop(state: AgBusGraphState) -> AgBusGraphState:
            return state

        builder = DynamicGraphBuilder(
            agent_executors={"a1": noop, "a2": noop, "a3": noop}
        )
        plan = {
            "steps": [
                {"agent_id": "a1", "capability_id": "c1", "description": "", "constraints": {}},
                {"agent_id": "a2", "capability_id": "c2", "description": "", "constraints": {}},
                {"agent_id": "a3", "capability_id": "c3", "description": "", "constraints": {}},
            ],
            "viable": True,
        }
        graph = builder.build(plan)
        compiled = graph.compile()
        assert compiled is not None

    @pytest.mark.asyncio
    async def test_execution_captures_results(self):
        """Node execution results are captured in step_results."""

        async def agent_exec(state: AgBusGraphState) -> AgBusGraphState:
            r = dict(state.get("step_results", {}))
            r["agent-x"] = {"answer": 42}
            return {**state, "step_results": r}

        builder = DynamicGraphBuilder(agent_executors={"agent-x": agent_exec})
        plan = {
            "steps": [
                {"agent_id": "agent-x", "capability_id": "c", "description": "", "constraints": {}},
            ],
            "viable": True,
        }
        graph = builder.build(plan)
        compiled = graph.compile()

        result = await compiled.ainvoke(
            {
                "session_id": "test",
                "intent_text": "test",
                "context": {},
                "step_results": {},
                "errors": [],
                "metadata": {},
            }
        )
        assert "agent-x" in result["step_results"]

    def test_missing_executor_creates_placeholder(self):
        """Agents without registered executors get error-recording nodes."""
        builder = DynamicGraphBuilder()
        plan = {
            "steps": [
                {"agent_id": "unknown", "capability_id": "c", "description": "", "constraints": {}},
            ],
            "viable": True,
        }
        # Should not raise – creates a placeholder node
        graph = builder.build(plan)
        assert graph is not None
