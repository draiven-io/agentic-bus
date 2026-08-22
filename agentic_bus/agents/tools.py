"""Tools that managed agents can be given.

These are ordinary LangChain tools, built on ``langchain_core`` and ``httpx``
— both of which the coordinator already depends on. That is the point: the
previous catalogue came from ``crewai-tools``, which meant installing CrewAI
(and its litellm/chromadb tree) to give an agent the ability to search the
web.

The catalogue here is deliberately much smaller than the 31 tools it
replaces. Each one is implemented and tested rather than re-exported, and
anything beyond them is better supplied by the deployment than guessed at by
us — see :func:`register_tool`.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)

#: Requirement descriptors are surfaced by the admin API so the dashboard can
#: prompt for credentials when an agent is given a tool that needs them.
Requirement = dict[str, Any]

_SERPER_ENDPOINT = "https://google.serper.dev/search"
_HTTP_TIMEOUT = 20.0
_MAX_PAGE_CHARS = 20_000


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------

@tool
def web_search(query: str) -> str:
    """Search the web and return the top results with titles, links and snippets.

    Use for questions about current events or anything not already known.
    """
    import httpx

    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return (
            "web_search is not configured: SERPER_API_KEY is unset. "
            "Set it on the agent's tool configuration."
        )

    try:
        response = httpx.post(
            _SERPER_ENDPOINT,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query},
            timeout=_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - reported to the model, not raised
        # Returning the error rather than raising lets the agent try another
        # approach; an exception here would abort the whole task.
        return f"web_search failed: {type(exc).__name__}: {exc}"

    results = payload.get("organic") or []
    if not results:
        return f"No results for {query!r}."

    lines = []
    for item in results[:8]:
        lines.append(
            f"- {item.get('title', 'untitled')}\n"
            f"  {item.get('link', '')}\n"
            f"  {item.get('snippet', '')}"
        )
    return "\n".join(lines)


@tool
def fetch_webpage(url: str) -> str:
    """Fetch a web page and return its readable text content."""
    import httpx

    if not url.lower().startswith(("http://", "https://")):
        return "fetch_webpage only accepts http:// or https:// URLs."

    try:
        response = httpx.get(
            url,
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "agentic-bus/fetch_webpage"},
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return f"fetch_webpage failed: {type(exc).__name__}: {exc}"

    return _html_to_text(response.text)[:_MAX_PAGE_CHARS]


@tool
def read_file(path: str) -> str:
    """Read a UTF-8 text file from disk and return its contents."""
    try:
        return Path(path).read_text(encoding="utf-8")[:_MAX_PAGE_CHARS]
    except Exception as exc:  # noqa: BLE001
        return f"read_file failed: {type(exc).__name__}: {exc}"


@tool
def list_directory(path: str = ".") -> str:
    """List the entries in a directory, marking which are directories."""
    try:
        entries = sorted(Path(path).iterdir())
    except Exception as exc:  # noqa: BLE001
        return f"list_directory failed: {type(exc).__name__}: {exc}"

    if not entries:
        return f"{path} is empty."
    return "\n".join(f"{'d' if e.is_dir() else '-'} {e.name}" for e in entries)


_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    """Reduce HTML to readable text.

    Intentionally dependency-free rather than pulling in a parser: the model
    needs prose, not a faithful DOM, and a wrong tag boundary costs a stray
    fragment rather than a failure.
    """
    text = _SCRIPT_OR_STYLE.sub(" ", html)
    text = _TAG.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    lines = [line.strip() for line in text.splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(line for line in lines if line))


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

class _Entry:
    __slots__ = ("factory", "description", "requirements")

    def __init__(
        self,
        factory: Callable[[], BaseTool],
        description: str,
        requirements: list[Requirement] | None = None,
    ):
        self.factory = factory
        self.description = description
        self.requirements = requirements or []


TOOL_CATALOGUE: dict[str, _Entry] = {
    "web_search": _Entry(
        lambda: web_search,
        "Search the web (Google via Serper) and return titles, links and snippets.",
        [
            {
                "key": "api_key",
                "env": "SERPER_API_KEY",
                "label": "Serper API Key",
                "required": True,
                "secret": True,
                "hint": "your-serper-api-key",
            }
        ],
    ),
    "fetch_webpage": _Entry(
        lambda: fetch_webpage,
        "Fetch a URL and return its readable text content.",
    ),
    "read_file": _Entry(
        lambda: read_file,
        "Read a UTF-8 text file from the coordinator's filesystem.",
    ),
    "list_directory": _Entry(
        lambda: list_directory,
        "List the entries of a directory on the coordinator's filesystem.",
    ),
}


def register_tool(
    name: str,
    factory: Callable[[], BaseTool],
    description: str = "",
    requirements: list[Requirement] | None = None,
) -> None:
    """Add a tool to the catalogue.

    The extension point for anything the built-ins do not cover. *factory* is
    called each time the tool is resolved, so it may read configuration
    injected just beforehand::

        from langchain_core.tools import tool
        from agentic_bus.agents.tools import register_tool

        @tool
        def check_inventory(sku: str) -> str:
            \"\"\"Return stock on hand for a SKU.\"\"\"
            ...

        register_tool("check_inventory", lambda: check_inventory,
                      "Look up stock levels.")
    """
    TOOL_CATALOGUE[name] = _Entry(factory, description, requirements)


def list_available_tools() -> list[str]:
    return sorted(TOOL_CATALOGUE)


def get_tool_description(name: str) -> str:
    entry = TOOL_CATALOGUE.get(name)
    return entry.description if entry else ""


def get_tool_requirements(name: str) -> list[Requirement]:
    entry = TOOL_CATALOGUE.get(name)
    return list(entry.requirements) if entry else []


def _inject_tool_env(name: str, config: dict[str, Any]) -> None:
    """Put per-agent tool credentials into the environment before resolving.

    Tools read their credentials from the environment, so an agent
    configured with its own key needs that key present at resolution time.
    """
    for requirement in get_tool_requirements(name):
        value = config.get(requirement["key"])
        if value:
            os.environ[requirement["env"]] = str(value)


def resolve_tool(
    name: str,
    *,
    tool_config: dict[str, Any] | None = None,
) -> BaseTool:
    """Instantiate one tool by name.

    Raises ``ValueError`` when the name is not in the catalogue.
    """
    entry = TOOL_CATALOGUE.get(name)
    if entry is None:
        raise ValueError(
            f"Unknown tool {name!r}. Available: {', '.join(list_available_tools())}"
        )

    if tool_config:
        _inject_tool_env(name, tool_config)

    return entry.factory()


def resolve_tools(
    names: list[str],
    tool_configs: dict[str, dict[str, Any]] | None = None,
) -> list[BaseTool]:
    """Instantiate several tools, skipping any that fail to load.

    A tool factory runs third-party code, which can fail in ways beyond
    ``ValueError`` — a missing credential, an incompatible dependency. Every
    one of those means the same thing here (this tool is unusable), so one
    broken tool degrades that tool rather than aborting the agent.
    """
    configs = tool_configs or {}
    tools: list[BaseTool] = []
    for name in names:
        try:
            tools.append(resolve_tool(name, tool_config=configs.get(name)))
        except Exception as exc:  # noqa: BLE001 - third-party boundary
            logger.warning("Skipping tool %r: %s: %s", name, type(exc).__name__, exc)
    return tools
