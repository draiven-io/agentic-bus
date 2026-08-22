"""Build runnable agents from ManagedAgent database records.

This module bridges the persistence layer with the execution runtime. Given a
``ManagedAgent`` row it:

1. Resolves the LLM (from the agent-level override or the bus-wide default).
2. Resolves the requested tools by name.
3. Converts ``ManagedAgentCapability`` rows into ``AgentCapability`` objects
   the capability registry understands.
4. Returns a LangChain/LangGraph agent ready to execute.

Agents were previously built with CrewAI. LangGraph already orchestrates the
coordinator, so a second agent framework bought nothing that could not be
expressed with the one already present — while costing a large dependency
tree, a monkeypatch of CrewAI's private ``LLM._get_native_provider``, and a
thread offload to bridge its synchronous ``kickoff()``. All three are gone.
"""

from __future__ import annotations

import logging
from typing import Any

from agentic_bus.core.persistence.models import ManagedAgent, ManagedAgentCapability
from agentic_bus.core.registry.capability_registry import AgentCapability
from agentic_bus.agents.tools import (  # re-exported for the admin API
    get_tool_description,
    get_tool_requirements,
    list_available_tools,
    register_tool,
    resolve_tool,
    resolve_tools,
)

logger = logging.getLogger(__name__)

__all__ = [
    "build_agent",
    "build_output_model",
    "capability_from_model",
    "capabilities_from_agent",
    "get_tool_description",
    "get_tool_requirements",
    "list_available_tools",
    "register_tool",
    "resolve_tool",
    "resolve_tools",
]

_FIELD_TYPE_MAP: dict[str, type] = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
    "list": list,
    "array": list,
    "dict": dict,
    "object": dict,
}


def build_output_model(
    capability_id: str,
    output_fields: list[dict[str, Any]],
) -> type:
    """Dynamically create a Pydantic ``BaseModel`` from a list of field defs.

    Each entry in *output_fields* is a dict with:

    - ``name``  – the field name (required).
    - ``type``  – one of ``str``, ``int``, ``float``, ``bool``, ``list``,
      ``dict`` (default ``str``).
    - ``description`` – optional human-readable description.

    Returns a ``BaseModel`` subclass named after the capability, e.g.
    ``TranslateTextOutput``.
    """
    from pydantic import BaseModel, Field as PydanticField

    if not output_fields:
        raise ValueError("output_fields must be a non-empty list")

    # Build a nice class name: "translate_text" → "TranslateTextOutput"
    class_name = (
        "".join(part.capitalize() for part in capability_id.split("_"))
        + "Output"
    )

    field_definitions: dict[str, Any] = {}
    for fdef in output_fields:
        fname = fdef.get("name")
        if not fname:
            continue
        ftype_str = fdef.get("type", "str").lower()
        ftype = _FIELD_TYPE_MAP.get(ftype_str, str)
        fdesc = fdef.get("description", "")
        field_definitions[fname] = (
            ftype,
            PydanticField(description=fdesc) if fdesc else PydanticField(default=...),
        )

    if not field_definitions:
        raise ValueError("No valid fields found in output_fields")

    model = type(class_name, (BaseModel,), {"__annotations__": {
        k: v[0] for k, v in field_definitions.items()
    }, **{k: v[1] for k, v in field_definitions.items()}})

    return model


def capability_from_model(cap: ManagedAgentCapability) -> AgentCapability:
    """Convert a ``ManagedAgentCapability`` DB row into an ``AgentCapability``.

    When ``output_fields_json`` is populated, a dynamic Pydantic model is
    built and assigned to ``output_model`` — this automatically derives
    ``output_schema`` via the ``AgentCapability`` model validator.
    """
    output_fields = cap.output_fields_json or []
    output_model = None
    if output_fields:
        try:
            output_model = build_output_model(cap.capability_id, output_fields)
        except (ValueError, Exception) as exc:
            logger.warning(
                "Could not build output model for capability %r: %s",
                cap.capability_id,
                exc,
            )

    return AgentCapability(
        capability_id=cap.capability_id,
        description=cap.description,
        required_scopes=cap.required_scopes_json or [],
        supported_data_domains=cap.supported_data_domains_json or [],
        operational_constraints=cap.operational_constraints_json or {},
        expected_artifacts=cap.expected_artifacts_json or [],
        estimated_cost=cap.estimated_cost,
        estimated_latency=cap.estimated_latency,
        output_model=output_model,
        output_schema=cap.output_schema_json or {},
    )


def capabilities_from_agent(agent: ManagedAgent) -> list[AgentCapability]:
    """Convert all capabilities of a ``ManagedAgent`` into bus-ready objects."""
    return [capability_from_model(c) for c in (agent.capabilities or [])]


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def _system_prompt(agent: ManagedAgent) -> str:
    """Turn the agent's persona into a system prompt.

    role/goal/backstory were CrewAI's framing. They remain a good way to
    describe an agent, and map directly onto the one instruction LangGraph
    takes.
    """
    parts = []
    if agent.role:
        parts.append(f"You are {agent.role}.")
    if agent.goal:
        parts.append(f"Your goal: {agent.goal}")
    if agent.backstory:
        parts.append(f"Background: {agent.backstory}")
    parts.append(
        "Use the tools available to you when they help. "
        "Answer only from what you can establish; say so when you cannot."
    )
    return "\n\n".join(parts)


def build_agent(agent: ManagedAgent, llm: Any | None = None) -> Any:
    """Build a LangGraph ReAct agent from a ``ManagedAgent`` record.

    Parameters
    ----------
    agent:
        The managed agent record, with capabilities eagerly loaded.
    llm:
        A pre-resolved LangChain chat model. Resolved from the agent's
        ``llm_config_name`` (or the bus default) when omitted.
    """
    # langgraph.prebuilt.create_react_agent is deprecated since LangGraph
    # v1.0 and slated for removal in v2.0; this is its replacement.
    from langchain.agents import create_agent

    if llm is None:
        llm = _resolve_llm(agent.llm_config_name)

    tool_configs = getattr(agent, "tool_config_json", None)
    tools = resolve_tools(agent.tools_json or [], tool_configs=tool_configs)

    # The first capability's output_fields describe the structured answer the
    # requester was promised, so the graph is asked to produce exactly that.
    response_format = None
    if agent.capabilities:
        output_fields = agent.capabilities[0].output_fields_json or []
        if output_fields:
            try:
                response_format = build_output_model(
                    agent.capabilities[0].capability_id, output_fields
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not build output model for %s: %s",
                    agent.capabilities[0].capability_id,
                    exc,
                )

    kwargs: dict[str, Any] = {
        "model": llm,
        "tools": tools,
        "system_prompt": _system_prompt(agent),
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    graph = create_agent(**kwargs)

    logger.info(
        "Agent built for %r (role=%r, tools=%d, structured=%s)",
        agent.agent_id,
        agent.role,
        len(tools),
        response_format is not None,
    )
    return graph


def _resolve_llm(config_name: str | None) -> Any:
    """Resolve a LangChain chat model from the LLM config store.

    Falls back to the bus-wide current configuration when *config_name*
    is ``None``.
    """
    from agentic_bus.core.persistence.llm_repository import LLMConfigRepository
    from agentic_bus.core.llm.factory import get_llm

    if config_name:
        repo = LLMConfigRepository()
        config = repo.get_by_name(config_name)
        if config is None:
            logger.warning(
                "LLM config %r not found, falling back to bus default",
                config_name,
            )
            # Fall through to default get_llm() which reads bus default
            return get_llm()

        # Build with explicit overrides from the named config
        extra = config.extra_config or {}
        kwargs: dict[str, Any] = {}
        if config.api_key:
            kwargs["api_key"] = config.api_key
        kwargs.update(extra)

        return get_llm(
            provider=config.provider,
            model=config.model,
            temperature=config.temperature,
            **kwargs,
        )

    # No specific config → use bus-wide default
    return get_llm()
