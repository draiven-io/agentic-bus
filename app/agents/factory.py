"""Factory that builds CrewAI Agent instances from ManagedAgent records.

This module bridges the Agentic Bus persistence layer with the CrewAI
runtime.  Given a ``ManagedAgent`` row it:

1. Resolves the LLM (from the agent-level override or bus-wide default).
2. Instantiates the requested CrewAI tools by name.
3. Converts ``ManagedAgentCapability`` rows into ``AgentCapability`` objects
   that the Agentic Bus capability registry understands.
4. Returns a fully-configured ``crewai.Agent`` ready for execution.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from app.core.persistence.models import ManagedAgent, ManagedAgentCapability
from app.core.registry.capability_registry import AgentCapability

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool catalogue – maps friendly names to (module_path, class_name) tuples.
# All entries come from the ``crewai_tools`` package.
# ---------------------------------------------------------------------------

CREWAI_TOOL_CATALOGUE: dict[str, tuple[str, str]] = {
    # Web & search
    "SerperDevTool":              ("crewai_tools", "SerperDevTool"),
    "WebsiteSearchTool":          ("crewai_tools", "WebsiteSearchTool"),
    "ScrapeWebsiteTool":          ("crewai_tools", "ScrapeWebsiteTool"),
    "ScrapeElementFromWebsiteTool": ("crewai_tools", "ScrapeElementFromWebsiteTool"),
    "EXASearchTool":              ("crewai_tools", "EXASearchTool"),
    "BrowserbaseLoadTool":        ("crewai_tools", "BrowserbaseLoadTool"),
    "FirecrawlSearchTool":        ("crewai_tools", "FirecrawlSearchTool"),
    "FirecrawlCrawlWebsiteTool":  ("crewai_tools", "FirecrawlCrawlWebsiteTool"),
    "FirecrawlScrapeWebsiteTool": ("crewai_tools", "FirecrawlScrapeWebsiteTool"),

    # File & directory
    "FileReadTool":               ("crewai_tools", "FileReadTool"),
    "DirectoryReadTool":          ("crewai_tools", "DirectoryReadTool"),
    "DirectorySearchTool":        ("crewai_tools", "DirectorySearchTool"),

    # Document search (RAG)
    "PDFSearchTool":              ("crewai_tools", "PDFSearchTool"),
    "DOCXSearchTool":             ("crewai_tools", "DOCXSearchTool"),
    "CSVSearchTool":              ("crewai_tools", "CSVSearchTool"),
    "TXTSearchTool":              ("crewai_tools", "TXTSearchTool"),
    "JSONSearchTool":             ("crewai_tools", "JSONSearchTool"),
    "XMLSearchTool":              ("crewai_tools", "XMLSearchTool"),
    "MDXSearchTool":              ("crewai_tools", "MDXSearchTool"),
    "CodeDocsSearchTool":         ("crewai_tools", "CodeDocsSearchTool"),

    # Code
    "CodeInterpreterTool":        ("crewai_tools", "CodeInterpreterTool"),
    "GithubSearchTool":           ("crewai_tools", "GithubSearchTool"),

    # Database
    "PGSearchTool":               ("crewai_tools", "PGSearchTool"),

    # Media
    "YoutubeChannelSearchTool":   ("crewai_tools", "YoutubeChannelSearchTool"),
    "YoutubeVideoSearchTool":     ("crewai_tools", "YoutubeVideoSearchTool"),
    "DALLETool":                  ("crewai_tools", "DALLETool"),
    "VisionTool":                 ("crewai_tools", "VisionTool"),

    # General
    "RagTool":                    ("crewai_tools", "RagTool"),

    # Third-party integrations
    "ComposioTool":               ("crewai_tools", "ComposioTool"),
    "LlamaIndexTool":             ("crewai_tools", "LlamaIndexTool"),

    # Apify
    "ApifyActorsTool":            ("crewai_tools", "ApifyActorsTool"),
}

# Human-readable descriptions for the interactive picker & help output.
CREWAI_TOOL_DESCRIPTIONS: dict[str, str] = {
    # Web & search
    "SerperDevTool":              "Google search via Serper API",
    "WebsiteSearchTool":          "RAG search over website content",
    "ScrapeWebsiteTool":          "Scrape entire websites",
    "ScrapeElementFromWebsiteTool": "Scrape specific elements from a page",
    "EXASearchTool":              "Exhaustive search across data sources",
    "BrowserbaseLoadTool":        "Interact with and extract data from browsers",
    "FirecrawlSearchTool":        "Search webpages via Firecrawl",
    "FirecrawlCrawlWebsiteTool":  "Crawl websites via Firecrawl",
    "FirecrawlScrapeWebsiteTool": "Scrape webpage URLs via Firecrawl",

    # File & directory
    "FileReadTool":               "Read and extract data from files",
    "DirectoryReadTool":          "Read directory structures and contents",
    "DirectorySearchTool":        "RAG search within directories",

    # Document search (RAG)
    "PDFSearchTool":              "RAG search within PDF documents",
    "DOCXSearchTool":             "RAG search within Word documents",
    "CSVSearchTool":              "RAG search within CSV files",
    "TXTSearchTool":              "RAG search within text files",
    "JSONSearchTool":             "RAG search within JSON files",
    "XMLSearchTool":              "RAG search within XML files",
    "MDXSearchTool":              "RAG search within Markdown (MDX) files",
    "CodeDocsSearchTool":         "RAG search through code documentation",

    # Code
    "CodeInterpreterTool":        "Interpret and execute Python code",
    "GithubSearchTool":           "RAG search within GitHub repositories",

    # Database
    "PGSearchTool":               "RAG search within PostgreSQL databases",

    # Media
    "YoutubeChannelSearchTool":   "RAG search within YouTube channels",
    "YoutubeVideoSearchTool":     "RAG search within YouTube videos",
    "DALLETool":                  "Generate images via DALL-E API",
    "VisionTool":                 "Analyse images via vision models",

    # General
    "RagTool":                    "General-purpose RAG over various data",

    # Third-party integrations
    "ComposioTool":               "Use Composio tool integrations",
    "LlamaIndexTool":             "Use LlamaIndex tool integrations",

    # Apify
    "ApifyActorsTool":            "Web scraping & automation via Apify Actors",
}


def list_available_tools() -> list[str]:
    """Return the sorted list of known CrewAI tool names."""
    return sorted(CREWAI_TOOL_CATALOGUE.keys())


def resolve_tool(name: str, **kwargs: Any) -> Any:
    """Instantiate a CrewAI tool by its catalogue name.

    Raises ``ValueError`` if the tool name is unknown and ``ImportError``
    if the underlying package is not installed.
    """
    entry = CREWAI_TOOL_CATALOGUE.get(name)
    if entry is None:
        raise ValueError(
            f"Unknown tool {name!r}. "
            f"Available: {', '.join(list_available_tools())}"
        )
    module_path, class_name = entry
    try:
        mod = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ImportError(
            f"Could not import {module_path!r} for tool {name!r}. "
            f"Install it with: pip install 'crewai[tools]'"
        ) from exc

    cls = getattr(mod, class_name)
    return cls(**kwargs)


def resolve_tools(names: list[str]) -> list[Any]:
    """Instantiate a list of CrewAI tools by name.

    Skips tools that fail to load (with a warning) so that the agent can
    still be created even if some tools are unavailable.
    """
    tools = []
    for name in names:
        try:
            tools.append(resolve_tool(name))
        except (ValueError, ImportError) as exc:
            logger.warning("Skipping tool %r: %s", name, exc)
    return tools


# ---------------------------------------------------------------------------
# Capability conversion
# ---------------------------------------------------------------------------

def capability_from_model(cap: ManagedAgentCapability) -> AgentCapability:
    """Convert a ``ManagedAgentCapability`` DB row into an ``AgentCapability``."""
    return AgentCapability(
        capability_id=cap.capability_id,
        description=cap.description,
        required_scopes=cap.required_scopes_json or [],
        supported_data_domains=cap.supported_data_domains_json or [],
        operational_constraints=cap.operational_constraints_json or {},
        expected_artifacts=cap.expected_artifacts_json or [],
        estimated_cost=cap.estimated_cost,
        estimated_latency=cap.estimated_latency,
        output_schema=cap.output_schema_json or {},
    )


def capabilities_from_agent(agent: ManagedAgent) -> list[AgentCapability]:
    """Convert all capabilities of a ``ManagedAgent`` into bus-ready objects."""
    return [capability_from_model(c) for c in (agent.capabilities or [])]


# ---------------------------------------------------------------------------
# CrewAI Agent factory
# ---------------------------------------------------------------------------

def build_crewai_agent(
    agent: ManagedAgent,
    llm: Any | None = None,
) -> Any:
    """Build a ``crewai.Agent`` from a ``ManagedAgent`` database record.

    Parameters
    ----------
    agent:
        The managed agent record (with capabilities eagerly loaded).
    llm:
        An optional pre-configured LangChain chat model.  When ``None``
        the factory attempts to resolve one from the agent's
        ``llm_config_name`` or the bus-wide default.

    Returns
    -------
    crewai.Agent
        A fully-configured CrewAI agent instance.
    """
    try:
        from crewai import Agent as CrewAgent
    except ImportError as exc:
        raise ImportError(
            "CrewAI is not installed.  Install with: pip install crewai"
        ) from exc

    # Resolve LLM if not provided
    if llm is None:
        llm = _resolve_llm(agent.llm_config_name)

    # Resolve tools
    tools = resolve_tools(agent.tools_json or [])

    crew_agent = CrewAgent(
        role=agent.role,
        goal=agent.goal,
        backstory=agent.backstory,
        verbose=agent.verbose,
        allow_delegation=False,
        max_iter=agent.max_iter,
        max_rpm=agent.max_rpm,
        memory=agent.memory,
        tools=tools,
        llm=llm,
    )

    logger.info(
        "CrewAI agent built for %r (role=%r, tools=%d)",
        agent.agent_id,
        agent.role,
        len(tools),
    )
    return crew_agent


def _resolve_llm(config_name: str | None) -> Any:
    """Resolve a LangChain chat model from the LLM config store.

    Falls back to the bus-wide current configuration when *config_name*
    is ``None``.
    """
    from app.core.persistence.llm_repository import LLMConfigRepository
    from app.core.llm.factory import get_llm

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
