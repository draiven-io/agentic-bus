"""Managed agents run on LangGraph.

The existing managed-agent tests cover persistence and the tool catalogue but
never build or execute an agent, because doing so meant standing up CrewAI.
A LangGraph agent can be driven by a fake chat model, so the execution path
is now testable without a provider.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agentic_bus.agents.factory import build_agent, _system_prompt
from agentic_bus.agents.tools import (
    TOOL_CATALOGUE,
    fetch_webpage,
    list_available_tools,
    read_file,
    register_tool,
    resolve_tool,
    resolve_tools,
    web_search,
)


class FakeManagedAgent:
    """Stands in for a ManagedAgent row without touching the database."""

    def __init__(self, **kwargs: Any):
        self.agent_id = kwargs.get("agent_id", "test-agent")
        self.role = kwargs.get("role", "Test Analyst")
        self.goal = kwargs.get("goal", "Answer questions accurately")
        self.backstory = kwargs.get("backstory", "Years of experience")
        self.tools_json = kwargs.get("tools_json", [])
        self.tool_config_json = kwargs.get("tool_config_json", None)
        self.llm_config_name = kwargs.get("llm_config_name", None)
        self.capabilities = kwargs.get("capabilities", [])
        self.verbose = False
        self.max_iter = 5
        self.max_rpm = None
        self.memory = False


class FakeCapability:
    def __init__(self, capability_id="cap", output_fields=None, description="", expected_output=""):
        self.capability_id = capability_id
        self.output_fields_json = output_fields or []
        self.description = description
        self.expected_output = expected_output


class ToolAwareFakeModel(GenericFakeChatModel):
    """A fake chat model that tolerates having tools bound to it.

    ``GenericFakeChatModel`` raises ``NotImplementedError`` from
    ``bind_tools``, and building an agent binds tools eagerly — so without
    this, any test that gives an agent a tool fails on the fake rather than
    on the code under test.
    """

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        return self


def _model(*replies: str) -> ToolAwareFakeModel:
    return ToolAwareFakeModel(messages=iter([AIMessage(content=r) for r in replies]))


class TestSystemPrompt:
    """role/goal/backstory were CrewAI's framing; they now become the prompt."""

    def test_persona_becomes_the_prompt(self):
        prompt = _system_prompt(
            FakeManagedAgent(
                role="Logistics Router",
                goal="find the cheapest viable route",
                backstory="a decade routing freight",
            )
        )
        assert "Logistics Router" in prompt
        assert "find the cheapest viable route" in prompt
        assert "a decade routing freight" in prompt

    def test_missing_pieces_are_skipped(self):
        prompt = _system_prompt(FakeManagedAgent(role="", goal="", backstory=""))
        assert prompt.strip(), "an agent with no persona still needs instructions"
        assert "You are ." not in prompt


class TestBuildAgent:
    def test_builds_a_runnable_graph(self):
        graph = build_agent(FakeManagedAgent(), llm=_model("done"))
        assert hasattr(graph, "ainvoke"), "expected a LangGraph runnable"

    def test_tools_are_bound(self):
        graph = build_agent(
            FakeManagedAgent(tools_json=["read_file", "list_directory"]),
            llm=_model("done"),
        )
        assert graph is not None

    def test_unknown_tools_are_skipped_not_fatal(self):
        """One bad tool name must degrade that tool, not the agent."""
        graph = build_agent(
            FakeManagedAgent(tools_json=["read_file", "NoSuchTool"]),
            llm=_model("done"),
        )
        assert graph is not None

    async def test_agent_executes_and_returns_text(self):
        graph = build_agent(FakeManagedAgent(), llm=_model("The answer is 42."))
        state = await graph.ainvoke(
            {"messages": [{"role": "user", "content": "what is the answer?"}]}
        )
        assert "42" in state["messages"][-1].content


class TestToolCatalogue:
    def test_catalogue_is_not_empty(self):
        assert list_available_tools()

    def test_every_tool_resolves_to_a_langchain_tool(self):
        for name in list_available_tools():
            resolved = resolve_tool(name)
            assert hasattr(resolved, "invoke"), f"{name} is not a LangChain tool"

    def test_unknown_tool_names_the_alternatives(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            resolve_tool("NoSuchTool")

    def test_resolve_tools_skips_failures(self):
        resolved = resolve_tools(["read_file", "NoSuchTool"])
        assert len(resolved) == 1

    def test_register_tool_extends_the_catalogue(self):
        from langchain_core.tools import tool

        @tool
        def check_stock(sku: str) -> str:
            """Return stock on hand."""
            return f"12 units of {sku}"

        register_tool("check_stock", lambda: check_stock, "Stock levels.")
        try:
            assert "check_stock" in list_available_tools()
            assert resolve_tool("check_stock").invoke({"sku": "A1"}) == "12 units of A1"
        finally:
            TOOL_CATALOGUE.pop("check_stock", None)


class TestBuiltInTools:
    """The built-ins report failures to the model rather than raising.

    An exception inside a tool aborts the whole task; a message describing
    the failure lets the agent try something else.
    """

    def test_web_search_without_credentials_explains_itself(self, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        result = web_search.invoke({"query": "anything"})
        assert "SERPER_API_KEY" in result

    def test_fetch_webpage_rejects_non_http_urls(self):
        result = fetch_webpage.invoke({"url": "file:///etc/passwd"})
        assert "http" in result.lower()

    def test_read_file_reports_missing_files(self):
        result = read_file.invoke({"path": "definitely-not-here.txt"})
        assert "failed" in result.lower()

    def test_read_file_returns_contents(self, tmp_path):
        target = tmp_path / "note.txt"
        target.write_text("hello from disk", encoding="utf-8")
        assert read_file.invoke({"path": str(target)}) == "hello from disk"


class TestHtmlToText:
    def test_tags_scripts_and_entities_are_stripped(self):
        from agentic_bus.agents.tools import _html_to_text

        html = (
            "<html><head><style>p{color:red}</style>"
            "<script>alert('x')</script></head>"
            "<body><h1>Title</h1><p>Body &amp; more</p></body></html>"
        )
        text = _html_to_text(html)
        assert "Title" in text
        assert "Body & more" in text
        assert "alert" not in text, "script contents leaked into the text"
        assert "color:red" not in text, "style contents leaked into the text"
        assert "<" not in text
