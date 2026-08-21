"""Tests for the capability registry."""

from pydantic import BaseModel

from agentic_bus.core.registry.capability_registry import (
    CapabilityRegistry,
    AgentRegistration,
    AgentCapability,
)


def _make_agent(agent_id: str, domains: list[str] | None = None) -> AgentRegistration:
    return AgentRegistration(
        agent_id=agent_id,
        version="1.0.0",
        semantic_description=f"Agent {agent_id}",
        supported_data_domains=domains or [],
        capabilities=[
            AgentCapability(
                capability_id=f"{agent_id}-cap-1",
                description=f"Capability of {agent_id}",
                supported_data_domains=domains or [],
            ),
        ],
    )


class TestCapabilityRegistry:
    def test_register_and_get(self):
        reg = CapabilityRegistry()
        agent = _make_agent("a-1")
        reg.register(agent)
        assert reg.get("a-1") is not None
        assert reg.count == 1

    def test_deregister(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("a-1"))
        removed = reg.deregister("a-1")
        assert removed is not None
        assert reg.get("a-1") is None

    def test_find_by_domain(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("a-1", ["logistics"]))
        reg.register(_make_agent("a-2", ["finance"]))
        reg.register(_make_agent("a-3", ["logistics", "warehousing"]))
        found = reg.find_by_domain("logistics")
        assert len(found) == 2

    def test_capability_summaries(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("a-1", ["logistics"]))
        summaries = reg.capability_summaries()
        assert len(summaries) == 1
        assert summaries[0]["agent_id"] == "a-1"
        assert summaries[0]["capability_id"] == "a-1-cap-1"
        assert "output_schema" in summaries[0]

    def test_capability_with_output_schema(self):
        """Capabilities can declare a structured output schema."""
        schema = {"title": "TestOutput", "type": "object", "properties": {"value": {"type": "integer"}}}
        reg = CapabilityRegistry()
        agent = AgentRegistration(
            agent_id="a-schema",
            version="1.0.0",
            semantic_description="Agent with output schema",
            supported_data_domains=["test"],
            capabilities=[
                AgentCapability(
                    capability_id="typed-cap",
                    description="A typed capability",
                    supported_data_domains=["test"],
                    output_schema=schema,
                ),
            ],
        )
        reg.register(agent)
        summaries = reg.capability_summaries()
        assert summaries[0]["output_schema"] == schema

    def test_hot_reload(self):
        """Registry must support hot-reloading (§7 of AGENTS.md)."""
        reg = CapabilityRegistry()
        reg.register(_make_agent("a-1", ["v1"]))
        assert reg.get("a-1").supported_data_domains == ["v1"]

        # Re-register with updated capabilities
        reg.register(_make_agent("a-1", ["v2"]))
        assert reg.get("a-1").supported_data_domains == ["v2"]
        assert reg.count == 1  # same agent, not duplicated

    def test_output_model_auto_derives_schema(self):
        """Passing output_model to AgentCapability auto-populates output_schema."""

        class MyOutput(BaseModel):
            value: int
            label: str

        cap = AgentCapability(
            capability_id="auto-schema",
            description="Capability with output_model",
            output_model=MyOutput,
        )
        assert cap.output_schema != {}
        assert cap.output_schema["title"] == "MyOutput"
        assert "value" in cap.output_schema["properties"]
        assert "label" in cap.output_schema["properties"]

    def test_output_model_excluded_from_serialisation(self):
        """output_model (a Python class) must not leak into JSON."""

        class MyOutput(BaseModel):
            x: float

        cap = AgentCapability(
            capability_id="no-leak",
            output_model=MyOutput,
        )
        dumped = cap.model_dump()
        assert "output_model" not in dumped
        assert "output_schema" in dumped

    def test_explicit_output_schema_not_overwritten(self):
        """If output_schema is provided explicitly, output_model does not overwrite it."""

        class MyOutput(BaseModel):
            x: float

        explicit = {"title": "Custom", "type": "object"}
        cap = AgentCapability(
            capability_id="explicit",
            output_model=MyOutput,
            output_schema=explicit,
        )
        assert cap.output_schema == explicit
