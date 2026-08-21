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

# ---------------------------------------------------------------------------
# Tool requirements – describes the configuration each tool needs.
#
# Each entry maps a tool name to a list of requirement dicts with:
#   - ``key``     – the config key (e.g. ``"api_key"``)
#   - ``env``     – the environment variable the tool reads at runtime
#   - ``label``   – human-friendly label for the UI
#   - ``required``– whether the tool will fail without it
#   - ``secret``  – whether the value should be masked in the UI
#   - ``hint``    – placeholder / example value
#
# Tools not listed here have no external configuration requirements.
# ---------------------------------------------------------------------------

CREWAI_TOOL_REQUIREMENTS: dict[str, list[dict[str, Any]]] = {
    "SerperDevTool": [
        {"key": "api_key", "env": "SERPER_API_KEY", "label": "Serper API Key",
         "required": True, "secret": True, "hint": "your-serper-api-key"},
    ],
    "EXASearchTool": [
        {"key": "api_key", "env": "EXA_API_KEY", "label": "EXA API Key",
         "required": True, "secret": True, "hint": "your-exa-api-key"},
    ],
    "BrowserbaseLoadTool": [
        {"key": "api_key", "env": "BROWSERBASE_API_KEY", "label": "Browserbase API Key",
         "required": True, "secret": True, "hint": "your-browserbase-api-key"},
        {"key": "project_id", "env": "BROWSERBASE_PROJECT_ID", "label": "Browserbase Project ID",
         "required": True, "secret": False, "hint": "your-project-id"},
    ],
    "FirecrawlSearchTool": [
        {"key": "api_key", "env": "FIRECRAWL_API_KEY", "label": "Firecrawl API Key",
         "required": True, "secret": True, "hint": "your-firecrawl-api-key"},
    ],
    "FirecrawlCrawlWebsiteTool": [
        {"key": "api_key", "env": "FIRECRAWL_API_KEY", "label": "Firecrawl API Key",
         "required": True, "secret": True, "hint": "your-firecrawl-api-key"},
    ],
    "FirecrawlScrapeWebsiteTool": [
        {"key": "api_key", "env": "FIRECRAWL_API_KEY", "label": "Firecrawl API Key",
         "required": True, "secret": True, "hint": "your-firecrawl-api-key"},
    ],
    "GithubSearchTool": [
        {"key": "api_key", "env": "GITHUB_TOKEN", "label": "GitHub Token",
         "required": True, "secret": True, "hint": "ghp_xxxxxxxxxxxx"},
        {"key": "github_repo", "env": "", "label": "GitHub Repository",
         "required": False, "secret": False, "hint": "owner/repo"},
        {"key": "content_types", "env": "", "label": "Content types (comma-sep)",
         "required": False, "secret": False, "hint": "code,repo,issue"},
    ],
    "DALLETool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key",
         "required": True, "secret": True, "hint": "sk-..."},
    ],
    "VisionTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key",
         "required": True, "secret": True, "hint": "sk-..."},
    ],
    "PGSearchTool": [
        {"key": "db_uri", "env": "PG_CONNECTION_STRING", "label": "PostgreSQL Connection URI",
         "required": True, "secret": True, "hint": "postgresql://user:pass@host/db"},
    ],
    "ComposioTool": [
        {"key": "api_key", "env": "COMPOSIO_API_KEY", "label": "Composio API Key",
         "required": True, "secret": True, "hint": "your-composio-api-key"},
    ],
    "ApifyActorsTool": [
        {"key": "api_key", "env": "APIFY_API_TOKEN", "label": "Apify API Token",
         "required": True, "secret": True, "hint": "apify_api_..."},
    ],
    # RAG-based tools – they all need an embedder; by default OpenAI embeddings.
    "WebsiteSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "PDFSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "DOCXSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "CSVSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "TXTSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "JSONSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "XMLSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "MDXSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "CodeDocsSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "DirectorySearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "YoutubeChannelSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "YoutubeVideoSearchTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
    "RagTool": [
        {"key": "api_key", "env": "OPENAI_API_KEY", "label": "OpenAI API Key (embeddings)",
         "required": False, "secret": True, "hint": "sk-... (for default embedder)"},
    ],
}


def get_tool_requirements(name: str) -> list[dict[str, Any]]:
    """Return the configuration requirements for a tool, or empty list."""
    return CREWAI_TOOL_REQUIREMENTS.get(name, [])


def list_available_tools() -> list[str]:
    """Return the sorted list of known CrewAI tool names."""
    return sorted(CREWAI_TOOL_CATALOGUE.keys())


def _inject_tool_env(name: str, config: dict[str, Any]) -> None:
    """Set environment variables required by a tool before instantiation.

    The *config* dict maps requirement keys (e.g. ``"api_key"``) to their
    user-supplied values.  For each key that has a corresponding ``env``
    entry in ``CREWAI_TOOL_REQUIREMENTS``, the value is written into
    ``os.environ`` so that the tool's default env-var lookup succeeds.
    """
    import os

    requirements = CREWAI_TOOL_REQUIREMENTS.get(name, [])
    for req in requirements:
        req_key = req["key"]
        env_var = req.get("env", "")
        value = config.get(req_key)
        if value and env_var:
            os.environ[env_var] = str(value)
            logger.debug("Injected env %s for tool %s", env_var, name)


def resolve_tool(name: str, *, tool_config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """Instantiate a CrewAI tool by its catalogue name.

    Parameters
    ----------
    name:
        The tool name from ``CREWAI_TOOL_CATALOGUE``.
    tool_config:
        Optional per-tool configuration dict (e.g. ``{"api_key": "sk-…"}``).
        Values whose keys match entries in ``CREWAI_TOOL_REQUIREMENTS`` are
        injected as environment variables before instantiation.
    **kwargs:
        Additional keyword arguments forwarded to the tool constructor.

    Raises ``ValueError`` if the tool name is unknown and ``ImportError``
    if the underlying package is not installed.
    """
    entry = CREWAI_TOOL_CATALOGUE.get(name)
    if entry is None:
        raise ValueError(
            f"Unknown tool {name!r}. "
            f"Available: {', '.join(list_available_tools())}"
        )

    # Inject env vars from per-tool config
    if tool_config:
        _inject_tool_env(name, tool_config)

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


def resolve_tools(
    names: list[str],
    tool_configs: dict[str, dict[str, Any]] | None = None,
) -> list[Any]:
    """Instantiate a list of CrewAI tools by name.

    Parameters
    ----------
    names:
        List of tool names to instantiate.
    tool_configs:
        Optional mapping of tool name → config dict.  Each tool receives
        its matching config (if any) for env-var injection.

    Skips tools that fail to load (with a warning) so that the agent can
    still be created even if some tools are unavailable.

    Loading a third-party tool executes that package's import side effects,
    which can fail in ways beyond ``ImportError`` — an incompatible
    transitive dependency surfaces as ``AttributeError``, a missing
    credential as ``KeyError``, and so on.  Every one of those means the same
    thing here (this tool is unusable), so the whole boundary is caught:
    one broken optional dependency must degrade a single tool, never abort
    creation of the agent.
    """
    configs = tool_configs or {}
    tools = []
    for name in names:
        try:
            tools.append(resolve_tool(name, tool_config=configs.get(name)))
        except Exception as exc:  # noqa: BLE001 - third-party import boundary
            logger.warning(
                "Skipping tool %r: %s: %s", name, type(exc).__name__, exc
            )
    return tools


# ---------------------------------------------------------------------------
# Capability conversion & dynamic output model
# ---------------------------------------------------------------------------

# Mapping from user-friendly type names to Python types.
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
        An optional pre-configured CrewAI ``LLM`` instance (or a litellm
        model string).  When ``None`` the factory resolves one from the
        agent's ``llm_config_name`` or the bus-wide default.

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
        llm = _resolve_crewai_llm(agent.llm_config_name)

    # Resolve tools (with per-tool configuration when available)
    tool_configs = agent.tool_config_json if hasattr(agent, 'tool_config_json') else None
    tools = resolve_tools(agent.tools_json or [], tool_configs=tool_configs)

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


def _resolve_crewai_llm(config_name: str | None) -> Any:
    """Resolve a ``crewai.LLM`` instance from the LLM config store.

    CrewAI uses litellm under the hood, so the model string must follow
    litellm conventions (e.g. ``azure/<deployment>`` for Azure OpenAI).
    Environment variables for the chosen provider are injected so that
    litellm can pick them up transparently.

    Falls back to the bus-wide current configuration when *config_name*
    is ``None``.
    """
    from app.core.persistence.llm_repository import LLMConfigRepository

    repo = LLMConfigRepository()

    if config_name:
        config = repo.get_by_name(config_name)
        if config is None:
            logger.warning(
                "LLM config %r not found, falling back to bus default",
                config_name,
            )
            config = repo.get_current_or_none()
    else:
        config = repo.get_current_or_none()

    if config is None:
        raise RuntimeError(
            "No LLM provider configured. "
            "Use 'agbus llm add' to configure an LLM provider."
        )

    return _build_crewai_llm_from_config(config)


def _safe_crewai_llm(**kwargs: Any) -> Any:
    """Create a ``crewai.LLM`` instance, gracefully handling missing native SDKs.

    CrewAI ≥ 1.9 routes model prefixes (``openai/``, ``azure/``, ``gemini/``,
    …) to **native provider** classes.  If the corresponding optional SDK
    (e.g. ``azure-ai-inference``) is not installed the import fails *before*
    the ``is_litellm`` flag is checked — a known bug in CrewAI 1.9.x.

    This helper temporarily patches ``LLM._get_native_provider`` so that a
    missing SDK returns ``None`` instead of raising, allowing the constructor
    to fall through to litellm.
    """
    from crewai import LLM

    original_get = LLM._get_native_provider

    @classmethod  # type: ignore[misc]
    def _safe_get(cls, provider: str):  # type: ignore[no-untyped-def]
        try:
            return original_get.__func__(cls, provider)
        except (ImportError, Exception):
            logger.debug(
                "Native CrewAI provider %r unavailable – falling through to litellm",
                provider,
            )
            return None

    LLM._get_native_provider = _safe_get
    try:
        return LLM(**kwargs)
    finally:
        LLM._get_native_provider = original_get


def _build_crewai_llm_from_config(config: Any) -> Any:
    """Build a ``crewai.LLM`` from a database ``LLMConfig`` row.

    Injects the provider-specific environment variables and constructs the
    appropriate model identifier string.

    For **Azure OpenAI** the function uses CrewAI's *OpenAI native provider*
    (which is always available) and points it at the Azure-compatible
    endpoint.  This avoids the need for the ``azure-ai-inference`` extra
    and for ``litellm``.
    """
    import os

    provider = config.provider.lower()
    model = config.model
    api_key = config.api_key or ""
    extra = config.extra_config or {}

    # Provider-specific setup
    if provider == "azure":
        # Resolve Azure-specific parameters
        deployment = (
            extra.get("azure_deployment")
            or extra.get("azure_openai_deployment")
            or os.getenv("AZURE_OPENAI_DEPLOYMENT", model)
        )
        endpoint = (
            extra.get("azure_endpoint")
            or extra.get("azure_openai_endpoint")
            or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        )
        api_version = (
            extra.get("api_version")
            or extra.get("azure_openai_api_version")
            or os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        )
        resolved_key = api_key or os.getenv("AZURE_OPENAI_API_KEY", "")

        if api_key:
            os.environ["AZURE_API_KEY"] = api_key
            os.environ["AZURE_OPENAI_API_KEY"] = api_key
        if endpoint:
            os.environ["AZURE_API_BASE"] = endpoint
            os.environ["AZURE_OPENAI_ENDPOINT"] = endpoint
        if api_version:
            os.environ["AZURE_API_VERSION"] = api_version

        # Build the Azure-compatible OpenAI base URL:
        #   {endpoint}/openai/deployments/{deployment}
        azure_base_url = endpoint.rstrip("/")
        if azure_base_url and deployment:
            azure_base_url = f"{azure_base_url}/openai/deployments/{deployment}"

        # Use the OpenAI native provider pointed at the Azure endpoint.
        # The ``default_query`` injects ``?api-version=…`` on every request,
        # and ``default_headers`` passes the key via the Azure-specific
        # ``api-key`` header (the OpenAI SDK also accepts it via ``api_key``).
        return _safe_crewai_llm(
            model=deployment,
            api_key=resolved_key or None,
            base_url=azure_base_url or None,
            temperature=config.temperature,
            default_query={"api-version": api_version},
        )

    elif provider == "openai":
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
        return _safe_crewai_llm(
            model=f"openai/{model}",
            api_key=api_key or None,
            temperature=config.temperature,
        )

    elif provider == "anthropic":
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        return _safe_crewai_llm(
            model=f"anthropic/{model}",
            api_key=api_key or None,
            temperature=config.temperature,
        )

    elif provider == "google":
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            os.environ["GEMINI_API_KEY"] = api_key
        # Gemini exposes an OpenAI-compatible endpoint.  If the native
        # ``google-genai`` SDK is not installed, fall back to OpenAI
        # provider pointed at the Gemini OpenAI-compat base URL.
        try:
            return _safe_crewai_llm(
                model=f"gemini/{model}",
                api_key=api_key or None,
                temperature=config.temperature,
            )
        except ImportError:
            resolved_key = api_key or os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
            return _safe_crewai_llm(
                model=model,
                api_key=resolved_key or None,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                temperature=config.temperature,
            )

    elif provider == "ollama":
        base_url = (
            extra.get("base_url")
            or os.getenv("AGBUS_OLLAMA_BASE_URL", "http://localhost:11434")
        )
        # Ollama exposes an OpenAI-compatible API at /v1.  Use the OpenAI
        # native provider (always available) so we don't need litellm.
        ollama_openai_url = f"{base_url.rstrip('/')}/v1"
        return _safe_crewai_llm(
            model=model,
            base_url=ollama_openai_url,
            api_key="ollama",  # Ollama requires a non-empty key for the OpenAI client
            temperature=config.temperature,
        )

    else:
        # Best-effort: use litellm's default provider resolution
        return _safe_crewai_llm(
            model=model,
            api_key=api_key or None,
            temperature=config.temperature,
        )


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
