"""Agentic Bus CLI.

Provides full setup, administration, and control of the Agentic Bus coordinator
from the command line.

Usage::

    agbus install                        # interactive setup wizard
    agbus serve                          # start the coordinator server
    agbus db init                        # create / migrate database tables
    agbus agent list                     # list all agents
    agbus agent show  <id>               # inspect a single agent
    agbus agent approve <id>             # approve a pending enrolment
    agbus agent reject  <id>             # reject a pending enrolment
    agbus agent revoke  <id>             # revoke an approved agent
    agbus agent delete  <id>             # permanently remove an agent
    agbus agent create                   # create a managed agent (interactive)
    agbus agent create <id> --role ...   # create a managed agent (flags)
    agbus agent activate <id>            # activate a managed agent
    agbus agent disable <id>             # disable a managed agent
    agbus agent add-capability <id>      # add capability to managed agent
    agbus agent remove-capability <id> c # remove capability
    agbus agent tools                    # list tools agents can be given
    agbus config show                    # display resolved configuration
    agbus config init                    # write a starter .env file
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import logging
import os
import signal
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv, find_dotenv

# Load .env before any module reads os.environ
# find_dotenv() searches for .env in current dir and parent dirs
_dotenv_path = find_dotenv(usecwd=True)
_loaded = load_dotenv(_dotenv_path, encoding="utf-8")

# Debug: Uncomment to troubleshoot .env loading
# import sys
# print(f"[DEBUG] .env path: {_dotenv_path}", file=sys.stderr)
# print(f"[DEBUG] .env loaded: {_loaded}", file=sys.stderr)
# import os
# print(f"[DEBUG] AGBUS_LLM_PROVIDER: {os.getenv('AGBUS_LLM_PROVIDER', 'NOT SET')}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Lazy helpers (import heavy modules only when needed)
# ---------------------------------------------------------------------------

def _init_logging() -> None:
    logging.basicConfig(
        level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _version() -> str:
    try:
        return importlib.metadata.version("agentic-bus")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0-dev"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_DIM = "\033[2m"

_STATUS_COLORS = {
    "pending": _YELLOW,
    "approved": _GREEN,
    "rejected": _RED,
    "revoked": _RED,
}


def _c(text: str, code: str) -> str:
    """Wrap *text* in an ANSI colour code (no-op when not a tty)."""
    if not sys.stdout.isatty():
        return text
    return f"{code}{text}{_RESET}"


def _status_badge(status: str) -> str:
    colour = _STATUS_COLORS.get(status, "")
    return _c(status.upper(), colour)


def _ts(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _print_agent_row(agent: Any) -> None:
    """Print one agent as a compact table row."""
    print(
        f"  {_c(agent.agent_id, _BOLD):<40s}  "
        f"{_status_badge(agent.status.value):<22s}  "
        f"v{agent.version:<8s}  "
        f"{_ts(agent.enrolled_at)}"
    )


def _print_agent_detail(agent: Any) -> None:
    """Print full agent details."""
    print()
    print(f"  {_c('Agent ID', _BOLD)}:       {agent.agent_id}")
    print(f"  {_c('Status', _BOLD)}:         {_status_badge(agent.status.value)}")
    print(f"  {_c('Version', _BOLD)}:        {agent.version}")
    print(f"  {_c('Description', _BOLD)}:    {agent.semantic_description or '—'}")
    print(f"  {_c('Enrolled at', _BOLD)}:    {_ts(agent.enrolled_at)}")
    print(f"  {_c('Approved at', _BOLD)}:    {_ts(agent.approved_at)}")
    print(f"  {_c('Approved by', _BOLD)}:    {agent.approved_by or '—'}")
    print(f"  {_c('Last connected', _BOLD)}: {_ts(agent.last_connected_at)}")
    caps = agent.capabilities_json or []
    print(f"  {_c('Capabilities', _BOLD)}:   {len(caps)}")
    for cap in caps:
        cid = cap.get("capability_id", "?")
        desc = cap.get("description", "")
        print(f"    • {cid}: {desc}")
    scopes = agent.required_scopes_json or []
    if scopes:
        print(f"  {_c('Scopes', _BOLD)}:        {', '.join(scopes)}")
    domains = agent.supported_domains_json or []
    if domains:
        print(f"  {_c('Domains', _BOLD)}:       {', '.join(domains)}")
    print()


# ============================================================================
# Sub-commands
# ============================================================================

# -- install (interactive wizard) --------------------------------------------

_PROVIDERS = ["openai", "anthropic", "google", "ollama", "azure"]

_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai":    {"model": "gpt-4o-mini",   "key_env": "OPENAI_API_KEY",       "key_hint": "sk-…"},
    "anthropic": {"model": "claude-sonnet-4-20250514", "key_env": "ANTHROPIC_API_KEY",  "key_hint": "sk-ant-…"},
    "google":    {"model": "gemini-2.0-flash", "key_env": "GOOGLE_API_KEY",     "key_hint": "AI…"},
    "ollama":    {"model": "llama3",         "key_env": "AGBUS_OLLAMA_BASE_URL",  "key_hint": "http://localhost:11434"},
    "azure":     {"model": "gpt-4o-mini",   "key_env": "AZURE_OPENAI_API_KEY", "key_hint": "…"},
}

_AZURE_EXTRA_KEYS = [
    ("AZURE_OPENAI_ENDPOINT",    "Azure OpenAI endpoint URL",          "https://your-resource.openai.azure.com/"),
    ("AZURE_OPENAI_DEPLOYMENT",  "Azure deployment name",              "gpt-4o-mini"),
    ("AZURE_OPENAI_API_VERSION", "Azure API version",                  "2024-12-01-preview"),
]


def _require_configuration() -> None:
    """Require that the system is configured before proceeding."""
    db_url = os.getenv("AGBUS_DATABASE_URL")
    env_file = Path(".env")
    
    if db_url is None and not env_file.exists():
        print()
        print(f"  {_c('✗ Error:', _RED)} No configuration found", file=sys.stderr)
        print("  The Agentic Bus must be configured before use.", file=sys.stderr)
        print()
        print(f"  Run {_c('agbus install', _BOLD)} to set up database and LLM settings", file=sys.stderr)
        print(f"  Or create a .env file with {_c('AGBUS_DATABASE_URL', _YELLOW)}", file=sys.stderr)
        print()
        sys.exit(1)


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """Prompt the user for input, showing a default value."""
    if default:
        suffix = f" [{_c(default, _DIM)}]: "
    else:
        suffix = ": "
    display = f"  {label}{suffix}"

    if secret:
        import getpass
        value = getpass.getpass(display)
    else:
        try:
            value = input(display)
        except EOFError:
            value = ""
    return value.strip() or default


def _prompt_choice(label: str, choices: list[str], default: str) -> str:
    """Prompt the user to pick from a list of choices."""
    print(f"\n  {_c(label, _BOLD)}")
    for i, c in enumerate(choices, 1):
        marker = _c("●", _GREEN) if c == default else " "
        print(f"    {marker} {i}) {c}")
    raw = _prompt("Your choice (number or name)", default)
    # Accept numeric index
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(choices):
            return choices[idx]
    # Accept name
    if raw.lower() in [c.lower() for c in choices]:
        return raw.lower()
    return default


def _prompt_yes_no(label: str, default: bool = False) -> bool:
    """Prompt for a yes/no answer."""
    hint = "Y/n" if default else "y/N"
    raw = _prompt(f"{label} [{hint}]", "y" if default else "n")
    return raw.lower() in ("y", "yes", "true", "1")


def _checkbox_picker(
    items: list[str],
    title: str = "Select items",
    descriptions: dict[str, str] | None = None,
    page_size: int = 15,
) -> list[str]:
    """Interactive checkbox picker for terminal.

    Uses raw terminal input (arrow keys + space to toggle, Enter to confirm).
    Falls back to comma-separated text input if the terminal doesn't support
    raw mode (e.g. piped stdin).

    Returns the list of selected item names.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        # Fallback for non-interactive terminals
        raw = input(f"  {title} (comma-separated): ")
        return [s.strip() for s in raw.split(",") if s.strip()]

    import tty
    import termios

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    selected: set[int] = set()
    cursor = 0
    scroll_offset = 0
    search_query = ""
    prev_line_count = 0

    def _filtered_indices() -> list[int]:
        """Return indices of items matching the current search query."""
        if not search_query:
            return list(range(len(items)))
        q = search_query.lower()
        return [i for i, name in enumerate(items) if q in name.lower()]

    def _read_key() -> str:
        """Read a single keypress (handles escape sequences)."""
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(1)
            if seq == "[":
                code = sys.stdin.read(1)
                return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT"}.get(code, "")
            return ""
        return ch

    def _render() -> None:
        """Render the picker UI by overwriting previous output in-place."""
        nonlocal cursor, scroll_offset, prev_line_count
        visible = _filtered_indices()
        total = len(visible)

        # Ensure cursor is within bounds
        if total == 0:
            cursor = 0
            scroll_offset = 0
        else:
            cursor = max(0, min(cursor, total - 1))
            if cursor < scroll_offset:
                scroll_offset = cursor
            elif cursor >= scroll_offset + page_size:
                scroll_offset = cursor - page_size + 1

        # Build output lines (using \r\n for raw mode)
        lines: list[str] = []
        lines.append(f"  {_c(title, _BOLD)}")
        lines.append(f"  {_c('↑/↓ navigate  Space toggle  a toggle-all  / filter  Enter confirm', _DIM)}")
        if search_query:
            lines.append(f"  {_c('Filter:', _YELLOW)} {search_query}  ({total} match{'es' if total != 1 else ''})")
        else:
            lines.append("")

        window_end = min(scroll_offset + page_size, total)
        if scroll_offset > 0:
            lines.append(f"    {_c('▲ more above', _DIM)}")
        else:
            lines.append("")

        for vi in range(scroll_offset, window_end):
            idx = visible[vi]
            name = items[idx]
            is_cursor = vi == cursor
            is_selected = idx in selected

            check = _c("✓", _GREEN) if is_selected else " "
            pointer = _c("❯", _CYAN) if is_cursor else " "
            box = f"[{check}]"

            desc = ""
            if descriptions and name in descriptions:
                desc = f"  {_c(descriptions[name], _DIM)}"

            label = _c(name, _BOLD) if is_cursor else name
            lines.append(f"  {pointer} {box} {label}{desc}")

        # Pad remaining rows so the picker height stays fixed
        for _ in range(page_size - (window_end - scroll_offset)):
            lines.append("")

        if window_end < total:
            lines.append(f"    {_c('▼ more below', _DIM)}")
        else:
            lines.append("")

        count = len(selected)
        lines.append(f"  {_c(f'{count} selected', _GREEN if count else _DIM)}")

        # Move cursor up to overwrite previous render (if any)
        buf = ""
        if prev_line_count > 0:
            buf += f"\x1b[{prev_line_count}A"  # move up
            buf += "\r"  # move to column 0

        # Write each line, clearing the rest of the row
        for line in lines:
            buf += f"\x1b[2K{line}\r\n"

        prev_line_count = len(lines)
        sys.stdout.write(buf)
        sys.stdout.flush()

    try:
        tty.setraw(fd)
        _render()

        while True:
            key = _read_key()
            visible = _filtered_indices()
            total = len(visible)

            if key in ("\r", "\n"):
                break
            elif key == " ":
                if visible and 0 <= cursor < total:
                    idx = visible[cursor]
                    if idx in selected:
                        selected.discard(idx)
                    else:
                        selected.add(idx)
                    cursor = min(cursor + 1, total - 1)
            elif key == "UP":
                cursor = max(0, cursor - 1)
            elif key == "DOWN":
                cursor = min(total - 1, cursor + 1) if total else 0
            elif key == "a":
                all_visible = set(_filtered_indices())
                if all_visible <= selected:
                    selected -= all_visible
                else:
                    selected |= all_visible
            elif key == "/":
                search_query = ""
                cursor = 0
                scroll_offset = 0
                _render()
                while True:
                    sch = sys.stdin.read(1)
                    if sch in ("\r", "\n", "\x1b"):
                        break
                    elif sch in ("\x7f", "\x08"):
                        search_query = search_query[:-1]
                    elif sch.isprintable():
                        search_query += sch
                    cursor = 0
                    scroll_offset = 0
                    _render()
            elif key == "\x1b" or key == "q":
                if search_query:
                    search_query = ""
                    cursor = 0
                    scroll_offset = 0
                else:
                    selected.clear()
                    break
            elif key == "\x03":
                selected.clear()
                break

            _render()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        # Overwrite the picker area with blank lines to clean up
        buf = ""
        if prev_line_count > 0:
            buf += f"\x1b[{prev_line_count}A\r"
            for _ in range(prev_line_count):
                buf += "\x1b[2K\n"
            buf += f"\x1b[{prev_line_count}A\r"
        sys.stdout.write(buf)
        sys.stdout.flush()

    result = [items[i] for i in sorted(selected)]

    # Print summary after exiting picker
    if result:
        print(f"  {_c('Selected tools:', _BOLD)}")
        for name in result:
            print(f"    {_c('✓', _GREEN)} {name}")
    else:
        print(f"  {_c('No tools selected', _DIM)}")
    print()

    return result


def cmd_install(args: argparse.Namespace) -> None:  # noqa: C901
    """Interactive setup wizard – walks through every configuration option."""
    env_path = Path(args.output) if hasattr(args, "output") else Path(".env")
    env_values: dict[str, str] = {}

    # LLM config collected separately – will be saved to the database
    llm_provider: str = ""
    llm_model: str = ""
    llm_temperature: str = "0.0"
    llm_api_key: str | None = None
    llm_extra_config: dict[str, str] = {}

    print()
    print(f"  {_c('╔══════════════════════════════════════════╗', _CYAN)}")
    print(f"  {_c('║', _CYAN)}   {_c('Agentic Bus – Setup Wizard', _BOLD)}      {_c('║', _CYAN)}")
    print(f"  {_c('╚══════════════════════════════════════════╝', _CYAN)}")
    print()
    print("  This wizard will walk you through configuration and")
    print(f"  write a {_c('.env', _BOLD)} file, initialise the database, save")
    print("  LLM settings, and optionally start the coordinator server.")
    print()

    # ── Step 1: LLM Provider ───────────────────────────────────────────────
    print(f"  {_c('─── Step 1: LLM Provider ───', _YELLOW)}")
    print(f"  {_c('LLM configuration is stored in the database, not .env.', _DIM)}")
    print(f"  {_c('You can add more providers later with: agbus llm add', _DIM)}")
    print()
    llm_provider = _prompt_choice("Select your LLM provider", _PROVIDERS, "openai")

    info = _PROVIDER_DEFAULTS[llm_provider]

    # Model
    llm_model = _prompt("Model name", info["model"])

    # Temperature
    llm_temperature = _prompt("Sampling temperature (0.0 = deterministic)", "0.0")

    # API key / URL for the chosen provider
    print()
    if llm_provider == "ollama":
        base_url = _prompt("Ollama base URL", info["key_hint"])
        llm_extra_config["base_url"] = base_url
    else:
        key_env = info["key_env"]
        key_val = _prompt(f"{key_env}", info["key_hint"], secret=False)
        if key_val and key_val != info["key_hint"]:
            llm_api_key = key_val

        # Azure needs extra vars
        if llm_provider == "azure":
            for az_key, az_label, az_default in _AZURE_EXTRA_KEYS:
                val = _prompt(az_label, az_default)
                llm_extra_config[az_key.lower()] = val

    # ── Step 2: Server ─────────────────────────────────────────────────────
    print(f"\n  {_c('─── Step 2: Server Configuration ───', _YELLOW)}")
    host = _prompt("Bind address", "0.0.0.0")
    env_values["AGBUS_HOST"] = host

    port = _prompt("Bind port", "8765")
    env_values["AGBUS_PORT"] = port

    env_values["AGBUS_COORDINATOR_URI"] = f"ws://{host}:{port}"

    log_level = _prompt_choice(
        "Log level",
        ["DEBUG", "INFO", "WARNING", "ERROR"],
        "INFO",
    )
    env_values["AGBUS_LOG_LEVEL"] = log_level

    # ── Step 3: Database ───────────────────────────────────────────────────
    print(f"\n  {_c('─── Step 3: Database ───', _YELLOW)}")
    print(f"  {_c('Default SQLite stores data alongside the coordinator.', _DIM)}")
    print(f"  {_c('For production, use PostgreSQL or MySQL.', _DIM)}")
    db_url = _prompt("Database URL", "sqlite:///agbus_agents.db")
    env_values["AGBUS_DATABASE_URL"] = db_url

    auto_approve = _prompt_yes_no("Auto-approve agent enrolments?", False)
    env_values["AGBUS_AGENT_AUTO_APPROVE"] = "true" if auto_approve else "false"

    # ── Step 4: Admin ──────────────────────────────────────────────────────
    print(f"\n  {_c('─── Step 4: Admin & Authentication (optional) ───', _YELLOW)}")
    configure_auth = _prompt_yes_no("Configure OIDC authentication?", False)

    if configure_auth:
        oidc_issuer = _prompt("OIDC issuer URL", "")
        if oidc_issuer:
            env_values["AGBUS_OIDC_ISSUER"] = oidc_issuer
        oidc_audience = _prompt("OIDC audience", "")
        if oidc_audience:
            env_values["AGBUS_OIDC_AUDIENCE"] = oidc_audience

        admin_subjects = _prompt("Admin OIDC subjects (comma-separated)", "")
        if admin_subjects:
            env_values["AGBUS_ADMIN_SUBJECTS"] = admin_subjects

        admin_role = _prompt("Admin role value", "agbus:admin")
        env_values["AGBUS_ADMIN_ROLE"] = admin_role

        admin_claim = _prompt("Admin role claim key", "roles")
        env_values["AGBUS_ADMIN_ROLE_CLAIM"] = admin_claim
    else:
        print(f"  {_c('Skipped – using DevVerifier (accepts any token).', _DIM)}")

    # ── Write .env ─────────────────────────────────────────────────────────
    print(f"\n  {_c('─── Writing configuration ───', _YELLOW)}")

    if env_path.exists() and not getattr(args, "force", False):
        overwrite = _prompt_yes_no(f"  {env_path} already exists. Overwrite?", False)
        if not overwrite:
            print(f"  {_c('Aborted.', _RED)} Existing .env preserved.")
            sys.exit(0)

    lines: list[str] = [
        "# Agentic Bus – generated by `agbus install`",
        f"# {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
    ]
    for key, val in env_values.items():
        lines.append(f"{key}={val}")
    lines.append("")

    env_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  {_c('✓', _GREEN)} Wrote {env_path}")

    # Reload env so that init_db and serve see the new values
    load_dotenv(env_path, override=True, encoding="utf-8")

    # ── Initialise database ────────────────────────────────────────────────
    print(f"\n  {_c('─── Initialising database ───', _YELLOW)}")
    from agentic_bus.core.persistence.database import init_db

    init_db()
    display_url = db_url.split("@")[-1] if "@" in db_url else db_url
    print(f"  {_c('✓', _GREEN)} Database initialised ({display_url})")

    # ── Save LLM configuration to database ─────────────────────────────────
    print(f"\n  {_c('─── Saving LLM configuration ───', _YELLOW)}")
    from agentic_bus.core.persistence.llm_repository import LLMConfigRepository

    llm_repo = LLMConfigRepository()
    llm_config_name = f"{llm_provider}-default"
    try:
        llm_repo.add(
            name=llm_config_name,
            provider=llm_provider,
            model=llm_model,
            temperature=float(llm_temperature),
            api_key=llm_api_key,
            extra_config=llm_extra_config or None,
            is_current=True,
            created_by=f"cli:{os.getenv('USER', 'admin')}",
        )
        print(f"  {_c('✓', _GREEN)} LLM configuration {_c(llm_config_name, _BOLD)} saved and activated")
    except ValueError as exc:
        # Already exists – try to activate it
        logger_cli = logging.getLogger("agbus.cli")
        logger_cli.debug("LLM config add failed: %s – trying activate", exc)
        try:
            llm_repo.activate(llm_config_name)
            print(f"  {_c('✓', _GREEN)} LLM configuration {_c(llm_config_name, _BOLD)} already exists, activated")
        except Exception:
            print(f"  {_c('⚠', _YELLOW)} Could not save LLM config: {exc}")
            print(f"    Use {_c('agbus llm add', _BOLD)} to configure manually.")

    # ── Start server? ──────────────────────────────────────────────────────
    print()
    start_now = _prompt_yes_no("Start the coordinator server now?", True)

    if start_now:
        print(f"\n  {_c('Starting coordinator on', _DIM)} {host}:{port} …\n")
        _init_logging()

        from agentic_bus.coordinator.runtime import CoordinatorRuntime

        serve_host = env_values.get("AGBUS_HOST", "0.0.0.0")
        serve_port = int(env_values.get("AGBUS_PORT", "8765"))

        async def _run() -> None:
            runtime = CoordinatorRuntime(host=serve_host, port=serve_port)
            await runtime.start()

            stop = asyncio.Event()
            loop = asyncio.get_running_loop()

            if sys.platform != "win32":
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, stop.set)
            else:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

            logger = logging.getLogger("agbus.cli")
            logger.info("Coordinator running on %s:%d – press Ctrl+C to stop",
                        serve_host, serve_port)
            await stop.wait()
            await runtime.stop()
            logger.info("Coordinator shut down cleanly")

        asyncio.run(_run())
    else:
        print(f"\n  {_c('All set!', _GREEN)} Run {_c('agbus serve', _BOLD)} to start the coordinator.\n")


# -- serve -------------------------------------------------------------------

def cmd_serve(args: argparse.Namespace) -> None:
    """Start the coordinator WebSocket server and Admin REST API."""
    _init_logging()
    logger = logging.getLogger("agbus.cli")

    from agentic_bus.coordinator.runtime import CoordinatorRuntime
    from agentic_bus.coordinator.admin.api import create_admin_api

    host = args.host or os.getenv("AGBUS_HOST", "0.0.0.0")
    port = args.port or int(os.getenv("AGBUS_PORT", "8765"))
    api_port = int(os.getenv("AGBUS_API_PORT", "8766"))

    async def _run() -> None:
        runtime = CoordinatorRuntime(host=host, port=port)
        await runtime.start()

        # Start the Admin REST API alongside the WebSocket server
        import uvicorn

        api_app = create_admin_api(runtime)
        config = uvicorn.Config(
            api_app,
            host=host,
            port=api_port,
            log_level=os.getenv("AGBUS_LOG_LEVEL", "info").lower(),
        )
        api_server = uvicorn.Server(config)
        api_task = asyncio.create_task(api_server.serve())
        logger.info("Admin API listening on http://%s:%d/api/docs", host, api_port)

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
        else:
            # Windows does not support add_signal_handler; fall back to
            # signal.signal which schedules the event set threadsafe.
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

        logger.info(
            "Coordinator running – WS on %s:%d, API on %s:%d – press Ctrl+C to stop",
            host, port, host, api_port,
        )
        await stop.wait()

        # Graceful shutdown
        api_server.should_exit = True
        await api_task
        await runtime.stop()
        logger.info("Coordinator shut down cleanly")

    asyncio.run(_run())


# -- db ----------------------------------------------------------------------

def cmd_db_init(args: argparse.Namespace) -> None:
    """Initialise (or migrate) the database tables."""
    _init_logging()
    from agentic_bus.core.persistence.database import init_db

    init_db()
    url = os.getenv("AGBUS_DATABASE_URL", "sqlite:///agbus_agents.db")
    # Mask credentials in the URL
    display_url = url.split("@")[-1] if "@" in url else url
    print(f"✓ Database initialised ({display_url})")


# -- agent -------------------------------------------------------------------

def _get_repo():
    from agentic_bus.core.persistence.database import init_db
    from agentic_bus.core.persistence.repository import AgentRepository

    _require_configuration()
    init_db()
    return AgentRepository()


def cmd_agent_list(args: argparse.Namespace) -> None:
    """List all agents (both registered and managed)."""
    from agentic_bus.core.persistence.models import AgentStatus, ManagedAgentStatus

    repo = _get_repo()
    managed_repo = _get_managed_repo()

    # Collect status filter – accept values from both enums
    status_raw = args.status.lower() if args.status else None

    reg_status = None
    mgd_status = None
    if status_raw:
        try:
            reg_status = AgentStatus(status_raw)
        except ValueError:
            reg_status = None  # not a registered-agent status – skip
        try:
            mgd_status = ManagedAgentStatus(status_raw)
        except ValueError:
            mgd_status = None  # not a managed-agent status – skip

        if reg_status is None and mgd_status is None:
            # A typo would otherwise be indistinguishable from a genuinely
            # empty result, so reject it rather than reporting "no agents".
            valid = sorted(
                {s.value for s in AgentStatus} | {s.value for s in ManagedAgentStatus}
            )
            print(f"  {_c('✗ Error:', _RED)} unknown status {args.status!r}", file=sys.stderr)
            print(f"  Valid values: {', '.join(valid)}", file=sys.stderr)
            sys.exit(1)

    registered = repo.list_all(status=reg_status) if (not status_raw or reg_status) else []
    managed = managed_repo.list_all(status=mgd_status) if (not status_raw or mgd_status) else []

    if not registered and not managed:
        label = f" with status={args.status}" if args.status else ""
        print(f"  No agents found{label}.")
        return

    print()
    print(f"  {_c('AGENT ID', _DIM):<40s}  {_c('TYPE', _DIM):<14s}  "
          f"{_c('STATUS', _DIM):<22s}  {_c('SCORE', _DIM):<8s}  "
          f"{_c('LATENCY', _DIM):<10s}  {_c('RUNS', _DIM):<6s}  "
          f"{_c('DETAILS', _DIM)}")
    print(f"  {'─' * 40}  {'─' * 12}  {'─' * 10}  {'─' * 6}  "
          f"{'─' * 8}  {'─' * 4}  {'─' * 28}")

    for agent in registered:
        badge = _status_badge(agent.status.value)
        detail = f"v{agent.version}"
        score = f"{agent.current_score:.1f}" if getattr(agent, "current_score", None) else "—"
        latency = f"{agent.mean_latency_ms:.0f}ms" if getattr(agent, "mean_latency_ms", None) else "—"
        runs = str(getattr(agent, "total_executions", 0) or 0)
        print(
            f"  {_c(agent.agent_id, _BOLD):<40s}  "
            f"{_c('registered', _CYAN):<14s}  "
            f"{badge:<22s}  "
            f"{score:<8s}  "
            f"{latency:<10s}  "
            f"{runs:<6s}  "
            f"{detail}"
        )

    for agent in managed:
        status_colors = {"draft": _YELLOW, "active": _GREEN, "disabled": _RED}
        badge = _c(agent.status.value.upper(), status_colors.get(agent.status.value, ""))
        n_caps = len(agent.capabilities) if agent.capabilities else 0
        n_tools = len(agent.tools_json) if agent.tools_json else 0
        detail = f"{n_caps} cap · {n_tools} tools"
        score = f"{agent.current_score:.1f}" if getattr(agent, "current_score", None) else "—"
        latency = f"{agent.mean_latency_ms:.0f}ms" if getattr(agent, "mean_latency_ms", None) else "—"
        runs = str(getattr(agent, "total_executions", 0) or 0)
        print(
            f"  {_c(agent.agent_id, _BOLD):<40s}  "
            f"{_c('managed', _YELLOW):<14s}  "
            f"{badge:<22s}  "
            f"{score:<8s}  "
            f"{latency:<10s}  "
            f"{runs:<6s}  "
            f"{detail}"
        )

    total = len(registered) + len(managed)
    print()
    print(f"  {total} agent(s)")
    print()


def cmd_agent_show(args: argparse.Namespace) -> None:
    """Show details for a single agent (registered or managed)."""
    repo = _get_repo()
    managed_repo = _get_managed_repo()

    # Try managed first, then registered
    managed = managed_repo.get(args.agent_id)
    if managed is not None:
        _print_managed_agent_detail(managed)
        return

    registered = repo.get(args.agent_id)
    if registered is not None:
        _print_agent_detail(registered)
        return

    print(f"Error: agent {args.agent_id!r} not found.", file=sys.stderr)
    sys.exit(1)


def cmd_agent_approve(args: argparse.Namespace) -> None:
    """Approve a pending agent enrolment."""
    repo = _get_repo()
    try:
        agent = repo.approve(args.agent_id, approved_by=f"cli:{os.getenv('USER', 'admin')}")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ Agent {_c(agent.agent_id, _BOLD)} approved")


def cmd_agent_reject(args: argparse.Namespace) -> None:
    """Reject a pending agent enrolment."""
    repo = _get_repo()
    try:
        agent = repo.reject(args.agent_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ Agent {_c(agent.agent_id, _BOLD)} rejected")


def cmd_agent_revoke(args: argparse.Namespace) -> None:
    """Revoke an approved agent."""
    repo = _get_repo()
    try:
        agent = repo.revoke(args.agent_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ Agent {_c(agent.agent_id, _BOLD)} revoked")


def cmd_agent_delete(args: argparse.Namespace) -> None:
    """Permanently delete an agent (registered or managed)."""
    repo = _get_repo()
    managed_repo = _get_managed_repo()

    if not args.yes:
        answer = input(f"Delete agent {args.agent_id!r} permanently? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return

    # Try managed first, then registered
    if managed_repo.delete(args.agent_id):
        print(f"✓ Agent {_c(args.agent_id, _BOLD)} deleted (managed)")
    elif repo.delete(args.agent_id):
        print(f"✓ Agent {_c(args.agent_id, _BOLD)} deleted (registered)")
    else:
        print(f"Error: agent {args.agent_id!r} not found.", file=sys.stderr)
        sys.exit(1)


# -- agent create (managed agents) -------------------------------------------

def _get_managed_repo():
    from agentic_bus.core.persistence.database import init_db
    from agentic_bus.core.persistence.managed_agent_repository import ManagedAgentRepository

    _require_configuration()
    init_db()
    return ManagedAgentRepository()


def _print_managed_agent_row(agent) -> None:
    """Print one managed agent as a compact table row."""
    status_colors = {"draft": _YELLOW, "active": _GREEN, "disabled": _RED}
    badge = _c(agent.status.value.upper(), status_colors.get(agent.status.value, ""))
    n_caps = len(agent.capabilities) if agent.capabilities else 0
    n_tools = len(agent.tools_json) if agent.tools_json else 0
    print(
        f"  {_c(agent.agent_id, _BOLD):<36s}  "
        f"{agent.name:<24s}  "
        f"{badge:<22s}  "
        f"{n_caps} cap  "
        f"{n_tools} tools"
    )


def _print_managed_agent_detail(agent) -> None:
    """Print full managed agent details."""
    status_colors = {"draft": _YELLOW, "active": _GREEN, "disabled": _RED}
    badge = _c(agent.status.value.upper(), status_colors.get(agent.status.value, ""))
    print()
    print(f"  {_c('Agent ID', _BOLD)}:         {agent.agent_id}")
    print(f"  {_c('Name', _BOLD)}:             {agent.name}")
    print(f"  {_c('Status', _BOLD)}:           {badge}")
    print(f"  {_c('Role', _BOLD)}:             {agent.role}")
    print(f"  {_c('Goal', _BOLD)}:             {agent.goal}")
    print(f"  {_c('Backstory', _BOLD)}:")
    # Wrap backstory nicely
    for line in textwrap.wrap(agent.backstory, width=68):
        print(f"    {line}")
    print()
    llm_label = agent.llm_config_name or "(bus default)"
    print(f"  {_c('LLM Config', _BOLD)}:       {llm_label}")
    print(f"  {_c('Verbose', _BOLD)}:           {agent.verbose}")
    print(f"  {_c('Max Iterations', _BOLD)}:   {agent.max_iter}")
    print(f"  {_c('Max RPM', _BOLD)}:           {agent.max_rpm or '—'}")
    print(f"  {_c('Memory', _BOLD)}:            {agent.memory}")

    tools = agent.tools_json or []
    print(f"  {_c('Tools', _BOLD)} ({len(tools)}):")
    if tools:
        for t in tools:
            print(f"    • {t}")
    else:
        print(f"    {_c('(none)', _DIM)}")

    caps = agent.capabilities or []
    print(f"  {_c('Capabilities', _BOLD)} ({len(caps)}):")
    if caps:
        for cap in caps:
            print(f"    • {_c(cap.capability_id, _CYAN)}: {cap.description}")
            if cap.expected_output:
                print(f"      Expected output: {cap.expected_output}")
            out_fields = cap.output_fields_json or []
            if out_fields:
                print(f"      Output fields ({len(out_fields)}):")
                for f in out_fields:
                    fdesc = f" – {f['description']}" if f.get("description") else ""
                    print(f"        {_c(f['name'], _CYAN)}: {f.get('type', 'str')}{fdesc}")
    else:
        print(f"    {_c('(none – add with: agbus agent add-capability)', _DIM)}")

    print(f"  {_c('Created at', _BOLD)}:      {_ts(agent.created_at)}")
    print(f"  {_c('Updated at', _BOLD)}:      {_ts(agent.updated_at)}")
    print(f"  {_c('Created by', _BOLD)}:      {agent.created_by}")
    print()


def _prompt_multiline(label: str, hint: str = "") -> str:
    """Prompt for multiline text input.  Empty line finishes."""
    if hint:
        print(f"  {_c(hint, _DIM)}")
    print(f"  {label} (press Enter twice to finish):")
    lines: list[str] = []
    while True:
        try:
            line = input("  > ")
        except EOFError:
            break
        if line == "" and lines:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def cmd_agent_create(args: argparse.Namespace) -> None:  # noqa: C901
    """Create a new managed agent."""
    from agentic_bus.core.persistence.models import ManagedAgentStatus
    from agentic_bus.agents.factory import list_available_tools

    repo = _get_managed_repo()
    interactive = args.agent_id is None

    if interactive:
        print()
        print(f"  {_c('╔══════════════════════════════════════════╗', _CYAN)}")
        print(f"  {_c('║', _CYAN)}   {_c('Create a Managed Agent', _BOLD)}             {_c('║', _CYAN)}")
        print(f"  {_c('╚══════════════════════════════════════════╝', _CYAN)}")
        print()
        print(f"  {_c('Agents are described by role, goal and backstory,', _DIM)}")
        print(f"  {_c('which together become the system prompt.', _DIM)}")
        print()

        # Identity
        print(f"  {_c('─── Identity ───', _YELLOW)}")
        agent_id = _prompt("Agent ID (unique slug, e.g. 'market-researcher-01')")
        while not agent_id:
            agent_id = _prompt("Agent ID (required)")

        name = _prompt("Display name", agent_id.replace("-", " ").title())

        # persona
        print(f"\n  {_c('─── Persona ───', _YELLOW)}")
        print(f"  {_c('Be specific and specialised – avoid generic roles.', _DIM)}")
        print()

        role = _prompt("Role (e.g. 'Senior UX Researcher specializing in user interview analysis')")
        while not role:
            role = _prompt("Role (required)")

        goal = _prompt("Goal (e.g. 'Uncover actionable user insights by analyzing interview data')")
        while not goal:
            goal = _prompt("Goal (required)")

        print()
        backstory = _prompt_multiline(
            "Backstory",
            "Give depth to the agent: experience, working style, values."
        )
        while not backstory:
            backstory = _prompt_multiline("Backstory (required)")

        # LLM
        print(f"\n  {_c('─── LLM Configuration ───', _YELLOW)}")
        llm_config_name = _prompt(
            "LLM config name (leave empty for bus default)",
            ""
        ) or None

        # Options
        print(f"\n  {_c('─── Agent Options ───', _YELLOW)}")
        verbose = _prompt_yes_no("Verbose mode?", False)
        max_iter_str = _prompt("Max iterations", "25")
        max_iter = int(max_iter_str) if max_iter_str.isdigit() else 25
        memory = _prompt_yes_no("Enable memory?", True)

        # Tools
        print(f"\n  {_c('─── Tools ───', _YELLOW)}")
        print(f"  {_c('Bind tools to this agent.', _DIM)}")
        print()
        available = list_available_tools()
        from agentic_bus.agents.tools import TOOL_CATALOGUE
        tools: list[str] = _checkbox_picker(
            items=available,
            title="Select tools to bind",
            descriptions={n: e.description for n, e in TOOL_CATALOGUE.items()},
        )

        # Capabilities
        print(f"\n  {_c('─── Capabilities ───', _YELLOW)}")
        print(f"  {_c('Capabilities define what this agent can do on the bus.', _DIM)}")
        print(f"  {_c('You can add more later with: agbus agent add-capability', _DIM)}")
        print()
        capabilities: list[dict] = []
        while True:
            add_cap = _prompt_yes_no(
                "Add a capability?" if not capabilities else "Add another capability?",
                not bool(capabilities)
            )
            if not add_cap:
                break
            cap_id = _prompt("  Capability ID (e.g. 'market_analysis')")
            cap_desc = _prompt("  Description")
            cap_output = _prompt("  Expected output description", "")
            cap_domains = _prompt("  Tags (comma-separated)", "")
            cap_cost = _prompt("  Estimated cost per invocation ($)", "0.0")
            cap_latency = _prompt("  Estimated latency (seconds)", "0.0")

            # Output fields – structured output definition
            output_fields: list[dict] = []
            define_fields = _prompt_yes_no("  Define structured output fields?", False)
            if define_fields:
                print(f"    {_c('Supported types: str, int, float, bool, list, dict', _DIM)}")
                while True:
                    fname = _prompt("    Field name (blank to finish)")
                    if not fname:
                        break
                    ftype = _prompt("    Field type", "str")
                    fdesc = _prompt("    Field description", "")
                    output_fields.append({
                        "name": fname,
                        "type": ftype,
                        "description": fdesc,
                    })
                    print(f"    {_c('✓', _GREEN)} Field {_c(fname, _CYAN)} ({ftype})")
                if output_fields:
                    print(f"    {_c(str(len(output_fields)), _BOLD)} output field(s) defined")

            capabilities.append({
                "capability_id": cap_id,
                "description": cap_desc,
                "expected_output": cap_output,
                "supported_data_domains": [d.strip() for d in cap_domains.split(",") if d.strip()],
                "estimated_cost": float(cap_cost) if cap_cost else 0.0,
                "estimated_latency": float(cap_latency) if cap_latency else 0.0,
                "output_fields": output_fields,
            })
            print(f"  {_c('✓', _GREEN)} Capability {_c(cap_id, _CYAN)} queued")

        # Status
        print(f"\n  {_c('─── Status ───', _YELLOW)}")
        activate_now = _prompt_yes_no("Activate agent immediately?", False)
        status = ManagedAgentStatus.ACTIVE if activate_now else ManagedAgentStatus.DRAFT

    else:
        # Non-interactive: all from CLI args
        agent_id = args.agent_id
        name = args.name or agent_id.replace("-", " ").title()
        role = args.role
        goal = args.goal
        backstory = args.backstory
        llm_config_name = args.llm_config or None
        verbose = args.verbose
        max_iter = args.max_iter
        memory = not args.no_memory
        tools = [t.strip() for t in args.tools.split(",") if t.strip()] if args.tools else []
        capabilities = []
        status = (
            ManagedAgentStatus.ACTIVE if args.activate
            else ManagedAgentStatus.DRAFT
        )

    # Create
    try:
        agent = repo.create(
            agent_id=agent_id,
            name=name,
            role=role,
            goal=goal,
            backstory=backstory,
            llm_config_name=llm_config_name,
            verbose=verbose,
            max_iter=max_iter,
            memory=memory,
            tools=tools,
            capabilities=capabilities,
            status=status,
            created_by=f"cli:{os.getenv('USER', 'admin')}",
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print()
    print(f"  {_c('✓', _GREEN)} Managed agent {_c(agent.agent_id, _BOLD)} created ({agent.status.value})")
    if agent.status == ManagedAgentStatus.DRAFT:
        print(f"    Activate with: {_c(f'agbus agent activate {agent.agent_id}', _CYAN)}")
    print(f"    Add capabilities: {_c(f'agbus agent add-capability {agent.agent_id}', _CYAN)}")
    print()


def cmd_agent_activate(args: argparse.Namespace) -> None:
    """Activate a managed agent."""
    from agentic_bus.core.persistence.models import ManagedAgentStatus
    from agentic_bus.core.persistence.managed_agent_repository import ManagedAgentNotFoundError

    repo = _get_managed_repo()
    try:
        agent = repo.set_status(args.agent_id, ManagedAgentStatus.ACTIVE)
    except ManagedAgentNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ Managed agent {_c(agent.agent_id, _BOLD)} activated")
    print(f"  Start server with: {_c(f'agbus agent start {agent.agent_id}', _CYAN)}")


def cmd_agent_disable(args: argparse.Namespace) -> None:
    """Disable a managed agent."""
    from agentic_bus.core.persistence.models import ManagedAgentStatus
    from agentic_bus.core.persistence.managed_agent_repository import ManagedAgentNotFoundError

    repo = _get_managed_repo()
    try:
        agent = repo.set_status(args.agent_id, ManagedAgentStatus.DISABLED)
    except ManagedAgentNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ Managed agent {_c(agent.agent_id, _BOLD)} disabled")


def cmd_agent_start(args: argparse.Namespace) -> None:
    """Start a managed agent as an independent server process.

    The agent connects to the coordinator via WebSocket and registers its
    capabilities.  It then listens for intents and executes tasks.
    Press Ctrl+C to stop.
    """
    from agentic_bus.agents.managed_server import run_managed_agent_sync

    coordinator_uri = args.coordinator_uri or os.getenv("AGBUS_WS_URI")
    print(f"Starting managed agent {_c(args.agent_id, _BOLD)} ...")

    try:
        run_managed_agent_sync(args.agent_id, coordinator_uri=coordinator_uri)
    except KeyboardInterrupt:
        print(f"\n✓ Managed agent {_c(args.agent_id, _BOLD)} stopped")


def cmd_agent_add_capability(args: argparse.Namespace) -> None:  # noqa: C901
    """Add a capability to a managed agent."""
    from agentic_bus.core.persistence.managed_agent_repository import ManagedAgentNotFoundError

    repo = _get_managed_repo()
    interactive = args.capability_id is None

    if interactive:
        print()
        print(f"  {_c('Add capability to', _BOLD)} {_c(args.agent_id, _CYAN)}")
        print()
        capability_id = _prompt("Capability ID (e.g. 'market_analysis')")
        while not capability_id:
            capability_id = _prompt("Capability ID (required)")
        description = _prompt("Description")
        expected_output = _prompt("Expected output description", "")
        domains_str = _prompt("Tags (comma-separated)", "")
        cost_str = _prompt("Estimated cost per invocation ($)", "0.0")
        latency_str = _prompt("Estimated latency (seconds)", "0.0")

        # Output fields – structured output definition
        output_fields: list[dict] = []
        define_fields = _prompt_yes_no("Define structured output fields?", False)
        if define_fields:
            print(f"  {_c('Supported types: str, int, float, bool, list, dict', _DIM)}")
            while True:
                fname = _prompt("  Field name (blank to finish)")
                if not fname:
                    break
                ftype = _prompt("  Field type", "str")
                fdesc = _prompt("  Field description", "")
                output_fields.append({
                    "name": fname,
                    "type": ftype,
                    "description": fdesc,
                })
                print(f"  {_c('✓', _GREEN)} Field {_c(fname, _CYAN)} ({ftype})")
            if output_fields:
                print(f"  {_c(str(len(output_fields)), _BOLD)} output field(s) defined")
    else:
        capability_id = args.capability_id
        description = args.description or ""
        expected_output = args.expected_output or ""
        domains_str = args.domains or ""
        cost_str = args.cost or "0.0"
        latency_str = args.latency or "0.0"
        output_fields = []
        # Support --output-field name:type:description on the command line
        for raw in (args.output_fields or []):
            parts = raw.split(":", 2)
            output_fields.append({
                "name": parts[0],
                "type": parts[1] if len(parts) > 1 else "str",
                "description": parts[2] if len(parts) > 2 else "",
            })

    try:
        cap = repo.add_capability(
            agent_id=args.agent_id,
            capability_id=capability_id,
            description=description,
            expected_output=expected_output,
            supported_data_domains=[d.strip() for d in domains_str.split(",") if d.strip()],
            estimated_cost=float(cost_str),
            estimated_latency=float(latency_str),
            output_fields=output_fields if output_fields else None,
        )
    except ManagedAgentNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"✓ Capability {_c(cap.capability_id, _CYAN)} added to {_c(args.agent_id, _BOLD)}")


def cmd_agent_remove_capability(args: argparse.Namespace) -> None:
    """Remove a capability from a managed agent."""
    repo = _get_managed_repo()
    if repo.remove_capability(args.agent_id, args.capability_id):
        print(f"✓ Capability {_c(args.capability_id, _CYAN)} removed from {_c(args.agent_id, _BOLD)}")
    else:
        print(f"Error: capability {args.capability_id!r} not found on agent {args.agent_id!r}.",
              file=sys.stderr)
        sys.exit(1)


def cmd_agent_tools(args: argparse.Namespace) -> None:
    """List the tools that can be bound to managed agents."""
    from agentic_bus.agents.tools import TOOL_CATALOGUE

    print()
    print(f"  {_c('Available Tools', _BOLD)}")
    print(f"  {'─' * 72}")
    print(f"  {_c('TOOL', _DIM):<36s}  {_c('DESCRIPTION', _DIM)}")
    print(f"  {'─' * 36}  {'─' * 34}")
    for name in sorted(TOOL_CATALOGUE):
        desc = TOOL_CATALOGUE[name].description
        print(f"    {_c(name, _CYAN):<36s}  {desc}")
    print()
    print(f"  {len(TOOL_CATALOGUE)} tool(s) available")
    print(f"  {_c('Add your own with agentic_bus.agents.tools.register_tool()', _DIM)}")
    print()


# -- llm ---------------------------------------------------------------------

def _get_llm_repo():
    from agentic_bus.core.persistence.database import init_db
    from agentic_bus.core.persistence.llm_repository import LLMConfigRepository

    _require_configuration()
    init_db()
    return LLMConfigRepository()


def _mask_api_key(key: str | None) -> str:
    """Mask an API key for display."""
    if not key:
        return "—"
    if len(key) > 8:
        return key[:4] + "…" + key[-4:]
    return "***"


def _print_llm_config_row(cfg) -> None:
    """Print one LLM config as a compact table row."""
    current = _c("● ACTIVE", _GREEN) if cfg.is_current else _c("  inactive", _DIM)
    print(
        f"  {_c(cfg.name, _BOLD):<30s}  "
        f"{cfg.provider:<12s}  "
        f"{cfg.model:<30s}  "
        f"{current}"
    )


def _print_llm_config_detail(cfg) -> None:
    """Print full LLM config details."""
    print()
    print(f"  {_c('Name', _BOLD)}:          {cfg.name}")
    print(f"  {_c('Provider', _BOLD)}:      {cfg.provider}")
    print(f"  {_c('Model', _BOLD)}:         {cfg.model}")
    print(f"  {_c('Temperature', _BOLD)}:   {cfg.temperature}")
    print(f"  {_c('API Key', _BOLD)}:       {_mask_api_key(cfg.api_key)}")
    print(f"  {_c('Active', _BOLD)}:        {'Yes' if cfg.is_current else 'No'}")
    print(f"  {_c('Created by', _BOLD)}:    {cfg.created_by}")
    print(f"  {_c('Created at', _BOLD)}:    {_ts(cfg.created_at)}")
    print(f"  {_c('Updated at', _BOLD)}:    {_ts(cfg.updated_at)}")
    extra = cfg.extra_config or {}
    if extra:
        print(f"  {_c('Extra config', _BOLD)}:")
        for k, v in extra.items():
            display_v = _mask_api_key(str(v)) if "key" in k.lower() else v
            print(f"    {k}: {display_v}")
    print()


# ---------------------------------------------------------------------------
# Scope vocabulary (RFC 0003)
# ---------------------------------------------------------------------------


def _scope_repo():
    from agentic_bus.core.persistence.database import init_db
    from agentic_bus.core.persistence.scope_repository import ScopeRepository

    init_db()
    return ScopeRepository()


def cmd_scope_list(args: argparse.Namespace) -> None:
    """Show the scope catalogue."""
    entries = _scope_repo().catalogue_entries()

    if not entries:
        print()
        print("  The scope catalogue is empty.")
        print(f"  Add one with {_c('agbus scope add carrier:quote', _BOLD)}, or let a")
        print("  development coordinator catalogue what agents declare.")
        print()
        return

    print()
    print(f"  {_c('SCOPE', _DIM):<34s}  {_c('SOURCE', _DIM):<10s}  {_c('DESCRIPTION', _DIM)}")
    print(f"  {'─' * 34}  {'─' * 10}  {'─' * 34}")
    for entry in entries:
        source = entry.created_by
        # A catalogue that grew by accident is worth being able to see at a
        # glance, so an operator can review what nobody actually decided.
        coloured = _c(source, _YELLOW) if source == "auto" else source
        print(f"  {entry.name:<34s}  {coloured:<10s}  {entry.description or '—'}")
    print()
    print(f"  {len(entries)} scope(s)")
    print()


def cmd_scope_add(args: argparse.Namespace) -> None:
    """Add a scope to the catalogue."""
    repo = _scope_repo()
    try:
        added = repo.add_scope(args.name, args.description or "", created_by="admin")
    except ValueError as exc:
        print()
        print(f"  {_c('✗', _RED)} {exc}")
        print("  A scope is segments separated by ':', optionally ending in '*'.")
        print()
        raise SystemExit(1)

    print()
    if added:
        print(f"  {_c('✓', _GREEN)} Scope {_c(args.name, _BOLD)} catalogued")
    else:
        print(f"  Scope {_c(args.name, _BOLD)} was already catalogued")
    print()


def cmd_scope_remove(args: argparse.Namespace) -> None:
    """Remove a scope, and any binding that granted it."""
    repo = _scope_repo()
    if not repo.remove_scope(args.name):
        print()
        print(f"  Scope {_c(args.name, _BOLD)} is not in the catalogue")
        print()
        raise SystemExit(1)
    print()
    print(f"  {_c('✓', _GREEN)} Scope {_c(args.name, _BOLD)} removed")
    print()


def cmd_scope_bind(args: argparse.Namespace) -> None:
    """Grant catalogued scopes to one agent's capability."""
    repo = _scope_repo()
    try:
        newly = repo.bind(args.agent_id, args.capability, args.scopes, bound_by="admin")
    except ValueError as exc:
        print()
        print(f"  {_c('✗', _RED)} {exc}")
        print(f"  Catalogue: {', '.join(repo.catalogue()) or '(empty)'}")
        print()
        raise SystemExit(1)

    print()
    if newly:
        print(
            f"  {_c('✓', _GREEN)} Granted {_c(', '.join(newly), _BOLD)} to "
            f"{args.agent_id}:{args.capability}"
        )
    else:
        print("  Already granted; nothing changed")
    print()


def cmd_scope_unbind(args: argparse.Namespace) -> None:
    """Revoke one granted scope."""
    repo = _scope_repo()
    if not repo.unbind(args.agent_id, args.capability, args.scope):
        print()
        print(f"  {args.agent_id}:{args.capability} does not hold {args.scope}")
        print()
        raise SystemExit(1)
    print()
    print(f"  {_c('✓', _GREEN)} Revoked {_c(args.scope, _BOLD)}")
    print()


def cmd_scope_granted(args: argparse.Namespace) -> None:
    """Show what an agent actually holds."""
    bindings = _scope_repo().granted_for_agent(args.agent_id)

    print()
    if not bindings:
        print(f"  {_c(args.agent_id, _BOLD)} holds no scopes.")
        print("  An unbound capability is granted nothing — that is the default,")
        print("  not an error. Grant one with:")
        print(f"    {_c('agbus scope bind ' + args.agent_id + ' <capability> <scope>', _CYAN)}")
        print()
        return

    print(f"  {_c(args.agent_id, _BOLD)}")
    for capability, scopes in sorted(bindings.items()):
        print(f"    {capability:<28s}  {', '.join(scopes)}")
    print()


def cmd_scope_requests(args: argparse.Namespace) -> None:
    """Show scopes agents asked for that nobody has catalogued."""
    pending = _scope_repo().pending_requests()

    if not pending:
        print()
        print("  No outstanding scope requests.")
        print()
        return

    print()
    print(f"  {_c('SCOPE', _DIM):<30s}  {_c('AGENT', _DIM):<26s}  {_c('ASKED', _DIM)}")
    print(f"  {'─' * 30}  {'─' * 26}  {'─' * 8}")
    for req in pending:
        print(f"  {req.scope:<30s}  {req.agent_id:<26s}  {req.request_count}×")
    print()
    print(f"  {len(pending)} request(s). These are agents telling you what they need.")
    print(f"  Catalogue one with {_c('agbus scope add <name>', _CYAN)}, then bind it.")
    print()


def cmd_llm_list(args: argparse.Namespace) -> None:
    """List all LLM configurations."""
    repo = _get_llm_repo()
    configs = repo.list_all()

    if not configs:
        print()
        print("  No LLM configurations found.")
        print(f"  Use {_c('agbus llm add', _BOLD)} to configure an LLM provider.")
        print()
        return

    print()
    print(f"  {_c('NAME', _DIM):<30s}  {_c('PROVIDER', _DIM):<12s}  "
          f"{_c('MODEL', _DIM):<30s}  {_c('STATUS', _DIM)}")
    print(f"  {'─' * 30}  {'─' * 12}  {'─' * 30}  {'─' * 12}")
    for cfg in configs:
        _print_llm_config_row(cfg)
    print()
    print(f"  {len(configs)} configuration(s)")
    print()


def cmd_llm_show(args: argparse.Namespace) -> None:
    """Show details for an LLM configuration."""
    repo = _get_llm_repo()
    cfg = repo.get_by_name(args.name)
    if cfg is None:
        print(f"Error: LLM configuration {args.name!r} not found.", file=sys.stderr)
        sys.exit(1)
    _print_llm_config_detail(cfg)


def cmd_llm_add(args: argparse.Namespace) -> None:  # noqa: C901
    """Add an LLM configuration (interactive or via flags)."""
    repo = _get_llm_repo()

    # If no name supplied, go interactive
    if not args.name:
        print()
        print(f"  {_c('─── Add LLM Configuration ───', _YELLOW)}")
        name = _prompt("Configuration name", "default")
        provider = _prompt_choice("LLM provider", _PROVIDERS, "openai")
        info = _PROVIDER_DEFAULTS[provider]
        model = _prompt("Model name", info["model"])
        temp = _prompt("Sampling temperature (0.0 = deterministic)", "0.0")

        api_key = None
        extra_config: dict[str, str] = {}
        if provider == "ollama":
            base_url = _prompt("Ollama base URL", info["key_hint"])
            extra_config["base_url"] = base_url
        else:
            key_val = _prompt(f"API key ({info['key_env']})", "", secret=False)
            if key_val:
                api_key = key_val

            if provider == "azure":
                for az_key, az_label, az_default in _AZURE_EXTRA_KEYS:
                    val = _prompt(az_label, az_default)
                    extra_config[az_key.lower()] = val

        activate = _prompt_yes_no("Set as active configuration?", True)
    else:
        name = args.name
        provider = args.provider or "openai"
        model = args.model or _PROVIDER_DEFAULTS.get(provider, {}).get("model", "gpt-4o-mini")
        temp = str(args.temperature) if args.temperature is not None else "0.0"
        api_key = args.api_key
        extra_config = {}
        if args.base_url:
            extra_config["base_url"] = args.base_url
        if args.azure_endpoint:
            extra_config["azure_openai_endpoint"] = args.azure_endpoint
        if args.azure_deployment:
            extra_config["azure_openai_deployment"] = args.azure_deployment
        if args.azure_api_version:
            extra_config["azure_openai_api_version"] = args.azure_api_version
        activate = args.activate

    try:
        cfg = repo.add(
            name=name,
            provider=provider,
            model=model,
            temperature=float(temp),
            api_key=api_key,
            extra_config=extra_config or None,
            is_current=activate,
            created_by=f"cli:{os.getenv('USER', 'admin')}",
        )
        print(f"  {_c('✓', _GREEN)} LLM configuration {_c(cfg.name, _BOLD)} added"
              f"{' and activated' if cfg.is_current else ''}")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_llm_activate(args: argparse.Namespace) -> None:
    """Activate an LLM configuration (make it current)."""
    repo = _get_llm_repo()
    try:
        cfg = repo.activate(args.name)
        print(f"  {_c('✓', _GREEN)} LLM configuration {_c(cfg.name, _BOLD)} is now active "
              f"(provider={cfg.provider}, model={cfg.model})")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_llm_update(args: argparse.Namespace) -> None:
    """Update an existing LLM configuration."""
    repo = _get_llm_repo()
    kwargs: dict[str, Any] = {}
    if args.provider:
        kwargs["provider"] = args.provider
    if args.model:
        kwargs["model"] = args.model
    if args.temperature is not None:
        kwargs["temperature"] = args.temperature
    if args.api_key:
        kwargs["api_key"] = args.api_key

    if not kwargs:
        print("Error: no fields to update. Use --provider, --model, --temperature, or --api-key.",
              file=sys.stderr)
        sys.exit(1)

    try:
        cfg = repo.update(args.name, **kwargs)
        print(f"  {_c('✓', _GREEN)} LLM configuration {_c(cfg.name, _BOLD)} updated")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_llm_remove(args: argparse.Namespace) -> None:
    """Remove an LLM configuration."""
    repo = _get_llm_repo()
    if not args.yes:
        answer = input(f"Delete LLM configuration {args.name!r}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return
    if repo.delete(args.name):
        print(f"  {_c('✓', _GREEN)} LLM configuration {_c(args.name, _BOLD)} deleted")
    else:
        print(f"Error: LLM configuration {args.name!r} not found.", file=sys.stderr)
        sys.exit(1)


# -- config ------------------------------------------------------------------

_CONFIG_KEYS: list[tuple[str, str, str]] = [
    # (env var, default, description)
    ("AGBUS_HOST", "0.0.0.0", "WebSocket bind address"),
    ("AGBUS_PORT", "8765", "WebSocket port"),
    ("AGBUS_LOG_LEVEL", "INFO", "Log level"),
    ("AGBUS_DATABASE_URL", "sqlite:///agbus_agents.db", "Database URL"),
    ("AGBUS_AGENT_AUTO_APPROVE", "false", "Auto-approve enrolments"),
    ("AGBUS_OIDC_ISSUER", "(none)", "OIDC issuer — set it and agents must authenticate"),
    ("AGBUS_REQUIRE_AGENT_AUTH", "false", "Demand a credential without an IdP"),
    ("AGBUS_SCOPE_CATALOGUE_ENFORCED", "false", "Refuse uncatalogued scopes instead of adding them"),
    ("AGBUS_SCOPE_ENFORCED", "(follows catalogue)", "Refuse a step the agent was not granted"),
    ("AGBUS_OIDC_AUDIENCE", "(none)", "OIDC audience"),
    ("AGBUS_ADMIN_SUBJECTS", "(none)", "Admin OIDC subjects"),
    ("AGBUS_ADMIN_ROLE", "agbus:admin", "Admin role value"),
    ("AGBUS_ADMIN_ROLE_CLAIM", "roles", "Admin role claim key"),
    ("AGBUS_COORDINATOR_URI", "ws://localhost:8765", "Agent connection URI"),
]

# Sensitive keys whose values should be masked
_SENSITIVE_KEYS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
                   "AZURE_OPENAI_API_KEY", "AGBUS_DATABASE_URL"}


def _mask(key: str, value: str) -> str:
    if key not in _SENSITIVE_KEYS:
        return value
    if not value or value.startswith("("):
        return value
    # For DB URLs, mask the password portion
    if "@" in value:
        return "***@" + value.split("@", 1)[1]
    if len(value) > 8:
        return value[:4] + "…" + value[-4:]
    return "***"


def cmd_config_show(args: argparse.Namespace) -> None:
    """Display the resolved configuration."""
    print()
    print(f"  {_c('Agentic Bus Configuration', _BOLD)}")
    print(f"  {_c(f'Version: {_version()}', _DIM)}")
    print()
    print(f"  {_c('VARIABLE', _DIM):<36s}  {_c('VALUE', _DIM):<40s}  {_c('DESCRIPTION', _DIM)}")
    print(f"  {'─' * 36}  {'─' * 40}  {'─' * 30}")
    for key, default, desc in _CONFIG_KEYS:
        raw = os.getenv(key, "")
        val = raw if raw else default
        source = "" if raw else _c(" (default)", _DIM)
        display = _mask(key, val)
        print(f"  {key:<36s}  {display:<40s}  {desc}{source}")
    print()

    # Show active LLM configuration from database
    try:
        repo = _get_llm_repo()
        cfg = repo.get_current_or_none()
        if cfg:
            print(f"  {_c('Active LLM Configuration', _BOLD)} {_c('(from database)', _DIM)}")
            print(f"  {'─' * 50}")
            print(f"  {'Name':<20s}  {cfg.name}")
            print(f"  {'Provider':<20s}  {cfg.provider}")
            print(f"  {'Model':<20s}  {cfg.model}")
            print(f"  {'Temperature':<20s}  {cfg.temperature}")
            print(f"  {'API Key':<20s}  {_mask_api_key(cfg.api_key)}")
            print()
        else:
            print(f"  {_c('⚠ No active LLM configuration in database.', _YELLOW)}")
            print(f"  {_c('  Use', _DIM)} {_c('agbus llm add', _BOLD)} {_c('to configure an LLM provider.', _DIM)}")
            print()
    except Exception:
        pass


def cmd_config_init(args: argparse.Namespace) -> None:
    """Generate a starter .env file from the template."""
    target = Path(args.output)
    if target.exists() and not args.force:
        print(f"Error: {target} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    # Locate .env.example relative to the package
    example = Path(__file__).resolve().parent.parent.parent / ".env.example"
    if not example.exists():
        # Fallback: try cwd
        example = Path.cwd() / ".env.example"
    if not example.exists():
        print("Error: .env.example template not found.", file=sys.stderr)
        sys.exit(1)

    target.write_text(example.read_text())
    print(f"✓ Created {target}")
    print("  Edit it with your settings, then restart the coordinator.")


# -- conformance --------------------------------------------------------------

def cmd_conformance(args: argparse.Namespace) -> None:
    """Run the LIP conformance suite against a connecting agent.

    Speaks only the protocol, so the agent under test can be written in any
    language: start this, point the agent at the printed URI, and it reports
    per requirement whether the agent behaved as the specification says.
    """
    import asyncio as _asyncio

    from agentic_bus.conformance import run_agent_conformance, report_to_json
    from agentic_bus.core.protocol.envelope import MessageType
    from agentic_bus.testing import LocalBus

    async def _run() -> int:
        async with LocalBus(host=args.host, port=args.port) as bus:
            if not args.json:
                print()
                print(f"  {_c('LIP conformance suite', _BOLD)}")
                print(f"  Listening on {_c(bus.uri, _CYAN)}")
                print(f"  {_c('Point your agent at that URI. Waiting…', _DIM)}")
                print()

            loop = _asyncio.get_running_loop()
            deadline = loop.time() + args.wait
            while loop.time() < deadline:
                if bus.messages_of_type(MessageType.REGISTER):
                    break
                await _asyncio.sleep(0.1)
            else:
                print(
                    f"  {_c('✗ Error:', _RED)} no agent connected within "
                    f"{args.wait:.0f}s",
                    file=sys.stderr,
                )
                return 1

            # Let registration settle before driving the lifecycle.
            await _asyncio.sleep(0.3)
            report = await run_agent_conformance(bus=bus, timeout=args.timeout)

        if args.json:
            print(report_to_json(report))
        else:
            print(report.render())
        return 0 if report.is_conformant else 1

    sys.exit(_asyncio.run(_run()))


# -- help --------------------------------------------------------------------

def cmd_help(args: argparse.Namespace) -> None:
    """Display comprehensive help about Agentic Bus architecture and usage."""
    topic = args.topic if hasattr(args, "topic") else None
    
    if not topic or topic == "overview":
        _print_help_overview()
    elif topic == "architecture":
        _print_help_architecture()
    elif topic == "agents":
        _print_help_agents()
    elif topic == "persistence":
        _print_help_persistence()
    elif topic == "admin":
        _print_help_admin()
    elif topic == "quickstart":
        _print_help_quickstart()
    else:
        print(f"Error: unknown help topic '{topic}'", file=sys.stderr)
        print("Available topics: overview, architecture, agents, persistence, admin, quickstart", file=sys.stderr)
        sys.exit(1)


def _print_help_overview():
    print(textwrap.dedent(f"""
    {_c('═' * 70, _BOLD)}
    {_c('Agentic Bus – Agentic Bus Protocol', _BOLD)}
    {_c('═' * 70, _BOLD)}

    The Agentic Bus is a runtime that orchestrates {_c('liquid interfaces', _CYAN)}
    between requesters and provider agents. Unlike rigid APIs, Agentic Bus enables
    dynamic, semantic capability matching and on-the-fly composition.

    {_c('Core Concepts', _BOLD)}
    ─────────────
    • {_c('Semantic Discovery', _GREEN)}: Agents describe capabilities in natural language
    • {_c('Dynamic Negotiation', _GREEN)}: Multi-round offer/accept protocol with fallback
    • {_c('IBAC Governance', _GREEN)}: Intention-Based Access Control for policy enforcement
    • {_c('Zero Residual Coupling', _GREEN)}: Sessions dissolve completely after execution
    • {_c('Observable Execution', _GREEN)}: Full audit trail with OpenTelemetry tracing

    {_c('Quick Start', _BOLD)}
    ───────────
      {_c('agbus help quickstart', _YELLOW)}       Show setup guide
      {_c('agbus config init', _YELLOW)}           Generate .env configuration
      {_c('agbus db init', _YELLOW)}               Create database tables
      {_c('agbus serve', _YELLOW)}                 Start the coordinator

    {_c('Help Topics', _BOLD)}
    ────────────
      {_c('agbus help overview', _DIM)}         This overview
      {_c('agbus help architecture', _DIM)}     Protocol architecture and components
      {_c('agbus help agents', _DIM)}           Agent registration and capabilities
      {_c('agbus help persistence', _DIM)}      Persistent agents and challenge auth
      {_c('agbus help admin', _DIM)}            Admin authorization and workflows
      {_c('agbus help quickstart', _DIM)}       Step-by-step setup guide

    {_c('Documentation', _BOLD)}
    ─────────────
      • Paper: Agentic Bus Protocol (§1-6)
      • AGENTS.md: Complete implementation guide (§1-19)
      • .env.example: All configuration options
    
    {_c('═' * 70, _BOLD)}
    """))


def _print_help_architecture():
    print(textwrap.dedent(f"""
    {_c('Agentic Bus Architecture', _BOLD)}
    {_c('═' * 70, _BOLD)}

    {_c('1. Session Lifecycle', _BOLD)}
    ────────────────────
      INTENT → DISCOVERY → NEGOTIATION → EXECUTION → DISSOLUTION

      • {_c('Intent Admission', _GREEN)}: Requester expresses objective Φ
      • {_c('Semantic Adjudication', _GREEN)}: LLM matches agents to intent
      • {_c('Offer/Accept', _GREEN)}: Agents propose capabilities + negotiate constraints
      • {_c('Dynamic Graph', _GREEN)}: LangGraph builds & executes composition
      • {_c('Mandatory Dissolution', _GREEN)}: All ephemeral state destroyed (R_c = 0)

    {_c('2. Core Subsystems', _BOLD)}
    ──────────────────
      • {_c('Transport', _CYAN)}: WebSocket with AgBusEnvelope framing
      • {_c('Registry', _CYAN)}: Hot-reloadable capability registry
      • {_c('IBAC Engine', _CYAN)}: Policy evaluation at 5 decision points
      • {_c('Session Manager', _CYAN)}: Phase transitions + audit logging
      • {_c('Graph Builder', _CYAN)}: LangGraph synthesis from composition plan
      • {_c('Execution Supervisor', _CYAN)}: Runtime governance + artifact gating

    {_c('3. Protocol Messages', _BOLD)}
    ───────────────────
      {_c('INTENT', _YELLOW)}    → Requester expresses objective
      {_c('OFFER', _YELLOW)}     → Agent proposes capability
      {_c('ACCEPT', _YELLOW)}    → Coordinator accepts offers
      {_c('REJECT', _YELLOW)}    → Coordinator rejects intent/offer
      {_c('EXECUTE', _YELLOW)}   → Coordinator triggers agent execution
      {_c('COMPLETE', _YELLOW)}  → Agent returns results
      {_c('DISSOLVE', _YELLOW)}  → Session termination

    {_c('4. Governance (IBAC)', _BOLD)}
    ───────────────────
      Evaluation Points:
        1. Intent Admission       (can requester submit this intent?)
        2. Offer Eligibility      (is agent allowed to participate?)
        3. Negotiation Acceptance (accept this offer?)
        4. Execution Authorization(allow task execution?)
        5. Artifact Emission      (allow result publication?)

    {_c('5. Persistence Modes', _BOLD)}
    ───────────────────
      • {_c('Ephemeral', _GREEN)}: Agent registers on connect, removed on disconnect
      • {_c('Persistent', _GREEN)}: Agent enrolls with Ed25519 key, admin approval,
                    challenge-response auth, survives disconnects

    {_c('═' * 70, _BOLD)}
    """))


def _print_help_agents():
    print(textwrap.dedent(f"""
    {_c('Agent Registration & Capabilities', _BOLD)}
    {_c('═' * 70, _BOLD)}

    {_c('1. Capability Declaration', _BOLD)}
    ───────────────────────
    Agents declare capabilities via {_c('AgentCapability', _CYAN)} objects:

      capability_id: str           Unique identifier
      description: str             Natural language description
      output_model: BaseModel      Pydantic model (auto-generates schema)
      required_scopes: list[str]   IBAC scopes needed
      supported_data_domains: [...] Data domains this capability handles
      estimated_cost: float        Monetary cost estimate
      estimated_latency: float     Latency estimate (seconds)

    {_c('2. Ephemeral Agents', _BOLD)}
    ──────────────────
    Quick development/testing – no persistence:

      • Connect via WebSocket
      • Send registration with capabilities
      • Coordinator accepts immediately
      • Removed on disconnect

    {_c('3. Persistent Agents', _BOLD)}
    ───────────────────
    Production-ready with approval workflow:

      • Generate Ed25519 keypair
      • Enrol with public key + metadata
      • Admin approves enrolment
      • On connect: challenge-response auth
      • Survives disconnects (marked offline)

    {_c('4. Hot-Reload', _BOLD)}
    ────────────
    Agents can update capabilities without coordinator restart:

      • Re-register with updated capabilities
      • Coordinator replaces in-memory record
      • Active sessions unaffected
      • New sessions see new capabilities

    {_c('5. Discovery', _BOLD)}
    ───────────
    Coordinator uses {_c('semantic adjudication', _CYAN)} (LLM-based):

      • Intent text + context → capability summaries
      • LLM scores each agent's relevance
      • Top-k candidates receive intent
      • Agents return offers with constraints

    {_c('Example: Python Agent', _BOLD)}
    ────────────────────

      from agentic_bus.agents.base import BaseAgent
      from pydantic import BaseModel

      class RouteOutput(BaseModel):
          route: list[str]
          distance_km: float

      class MyAgent(BaseAgent):
          def capabilities(self):
              return [AgentCapability(
                  capability_id="route-planner",
                  description="Plan optimal delivery routes",
                  output_model=RouteOutput,
                  supported_data_domains=["logistics"],
              )]

          async def execute_task(self, plan, scopes):
              # ... implement logic ...
              return RouteOutput(route=[...], distance_km=42.5)

    {_c('═' * 70, _BOLD)}
    """))


def _print_help_persistence():
    print(textwrap.dedent(f"""
    {_c('Persistent Agents & Challenge Authentication', _BOLD)}
    {_c('═' * 70, _BOLD)}

    {_c('1. Enrolment Flow', _BOLD)}
    ─────────────────
      {_c('1.', _YELLOW)} Agent generates Ed25519 keypair
      {_c('2.', _YELLOW)} Agent enrolls: sends agent_id + public_key_pem + metadata
      {_c('3.', _YELLOW)} Repository stores with status={_c('PENDING', _RED)}
      {_c('4.', _YELLOW)} Admin approves via {_c('agbus agent approve <id>', _CYAN)}
      {_c('5.', _YELLOW)} Status changes to {_c('APPROVED', _GREEN)}

    {_c('2. Challenge-Response Auth', _BOLD)}
    ─────────────────────────
      {_c('1.', _YELLOW)} Agent connects to coordinator
      {_c('2.', _YELLOW)} Coordinator generates 32-byte random nonce
      {_c('3.', _YELLOW)} Agent signs nonce with its private key
      {_c('4.', _YELLOW)} Coordinator verifies signature with stored public key
      {_c('5.', _YELLOW)} On success: agent marked online, allowed to participate

    {_c('3. Auto-Approval', _BOLD)}
    ──────────────
    For development environments:

      {_c('AGBUS_AGENT_AUTO_APPROVE=true', _YELLOW)}

    Enrolling agents are immediately approved (status={_c('APPROVED', _GREEN)}).

    {_c('4. Admin Commands', _BOLD)}
    ─────────────────
      {_c('agbus agent list --status pending', _CYAN)}   Show pending enrolments
      {_c('agbus agent show <id>', _CYAN)}               Inspect agent details
      {_c('agbus agent approve <id>', _CYAN)}            Approve enrolment
      {_c('agbus agent reject <id>', _CYAN)}             Reject enrolment
      {_c('agbus agent revoke <id>', _CYAN)}             Revoke approved agent
      {_c('agbus agent delete <id>', _CYAN)}             Permanently remove

    {_c('5. Database', _BOLD)}
    ──────────
    Configure via {_c('AGBUS_DATABASE_URL', _YELLOW)}:

      {_c('sqlite:///agbus_agents.db', _DIM)}                         (default)
      {_c('postgresql://user:pass@host:5432/agbus', _DIM)}
      {_c('mysql+pymysql://user:pass@host/agbus', _DIM)}

    Initialize tables:
      {_c('agbus db init', _CYAN)}

    {_c('6. Agent States', _BOLD)}
    ──────────────
      • {_c('PENDING', _YELLOW)}  → Awaiting admin approval
      • {_c('APPROVED', _GREEN)} → Can authenticate and connect
      • {_c('REJECTED', _RED)}  → Enrolment denied
      • {_c('REVOKED', _RED)}   → Previously approved, now blocked

    {_c('7. Disconnect Behavior', _BOLD)}
    ────────────────────
      • {_c('Ephemeral', _DIM)}: Fully removed from registry
      • {_c('Persistent', _DIM)}: Marked offline, remains discoverable

    {_c('═' * 70, _BOLD)}
    """))


def _print_help_admin():
    print(textwrap.dedent(f"""
    {_c('Admin Authorization & Workflows', _BOLD)}
    {_c('═' * 70, _BOLD)}

    {_c('1. Who is an Admin?', _BOLD)}
    ──────────────────
    An identity is admin if {_c('ANY', _BOLD)} of these are true:

      • OIDC {_c('sub', _CYAN)} claim is in {_c('AGBUS_ADMIN_SUBJECTS', _YELLOW)} (comma-separated)
      • OIDC token carries {_c('AGBUS_ADMIN_ROLE', _YELLOW)} inside {_c('AGBUS_ADMIN_ROLE_CLAIM', _YELLOW)}

    {_c('2. Configuration', _BOLD)}
    ───────────────
    {_c('.env example:', _DIM)}

      {_c('AGBUS_ADMIN_SUBJECTS', _YELLOW)}=alice@example.com,bob@example.com
      {_c('AGBUS_ADMIN_ROLE', _YELLOW)}=agbus:admin
      {_c('AGBUS_ADMIN_ROLE_CLAIM', _YELLOW)}=roles

    With this config:
      • Anyone with OIDC sub="alice@example.com" is admin
      • Anyone with OIDC token roles=["agbus:admin"] is admin

    {_c('3. CLI Admin Operations', _BOLD)}
    ───────────────────────
    The CLI bypasses OIDC auth (local filesystem access):

      {_c('agbus agent approve <id>', _CYAN)}    Approve pending agent
      {_c('agbus agent reject <id>', _CYAN)}     Reject pending agent
      {_c('agbus agent revoke <id>', _CYAN)}     Revoke approved agent
      {_c('agbus agent delete <id>', _CYAN)}     Permanently delete

    Approval is recorded with {_c('approved_by', _DIM)} = "cli:$USER"

    {_c('4. WebSocket Admin API', _BOLD)}
    ──────────────────────
    (Future) Admin operations via authenticated WebSocket:

      • Send OIDC token in connection handshake
      • Coordinator verifies admin status
      • Admin can approve/reject/revoke agents remotely

    {_c('5. Admin Service', _BOLD)}
    ───────────────
    The {_c('AdminService', _CYAN)} wraps {_c('AgentRepository', _DIM)} with authorization:

      from agentic_bus.coordinator.admin import AdminService
      
      service = AdminService()
      identity = ... # OIDCIdentity from verified token
      
      service.approve_agent("my-agent", identity)
      # Raises PermissionError if identity is not admin

    {_c('6. Production Deployment', _BOLD)}
    ───────────────────────
    Recommended setup:

      • Use real OIDC provider (Keycloak, Auth0, Google, etc.)
      • Set {_c('AGBUS_OIDC_ISSUER', _YELLOW)} and {_c('AGBUS_OIDC_AUDIENCE', _YELLOW)}
      • Configure {_c('AGBUS_ADMIN_SUBJECTS', _YELLOW)} with admin OIDC subs
      • OR: Configure role-based admin via {_c('AGBUS_ADMIN_ROLE', _YELLOW)}
      • Set {_c('AGBUS_AGENT_AUTO_APPROVE=false', _YELLOW)} (manual approval)

    {_c('═' * 70, _BOLD)}
    """))


def _print_help_quickstart():
    print(textwrap.dedent(f"""
    {_c('Agentic Bus – Quick Start Guide', _BOLD)}
    {_c('═' * 70, _BOLD)}

    {_c('Step 1: Install', _BOLD)}
    ──────────────
      {_c('pip install -e ".[dev]"', _CYAN)}          # Development mode
      {_c('pip install "agentic-bus"', _CYAN)}       # From PyPI (future)

    {_c('Step 2: Configure', _BOLD)}
    ────────────────
      {_c('agbus config init', _CYAN)}                  # Generate .env file
      {_c('vi .env', _DIM)}                           # Edit configuration

    {_c('Required:', _YELLOW)} Set {_c('OPENAI_API_KEY', _YELLOW)} (or choose different LLM provider)

    {_c('Step 3: Initialize Database', _BOLD)}
    ──────────────────────────
      {_c('agbus db init', _CYAN)}                      # Create tables

    {_c('Step 4: Start Coordinator', _BOLD)}
    ────────────────────────
      {_c('agbus serve', _CYAN)}                        # Starts on 0.0.0.0:8765

    {_c('Step 5: Run Example Agent', _BOLD)}
    ────────────────────────
      {_c('python -m agentic_bus.agents.examples.logistics_agent', _CYAN)}

    {_c('Step 6: Verify', _BOLD)}
    ─────────────
      {_c('agbus agent list', _CYAN)}                   # Should show connected agent

    {_c('Alternative: Persistent Agent', _BOLD)}
    ──────────────────────────
      {_c('1.', _YELLOW)} Generate Ed25519 keypair in your agent
      {_c('2.', _YELLOW)} Agent enrolls with public key
      {_c('3.', _YELLOW)} Approve: {_c('agbus agent approve <id>', _CYAN)}
      {_c('4.', _YELLOW)} Agent connects with challenge-response auth

    {_c('Environment Configuration', _BOLD)}
    ─────────────────────────
    {_c('Core:', _BOLD)}
      AGBUS_HOST              WebSocket bind address (default: 0.0.0.0)
      AGBUS_PORT              WebSocket port (default: 8765)
      AGBUS_LOG_LEVEL         Logging verbosity (default: INFO)

    {_c('LLM:', _BOLD)}
      AGBUS_LLM_PROVIDER      openai|anthropic|google|ollama|azure
      AGBUS_LLM_MODEL         Model name (provider-specific)
      OPENAI_API_KEY        Your OpenAI key

    {_c('Database:', _BOLD)}
      AGBUS_DATABASE_URL      SQLAlchemy connection string
      AGBUS_AGENT_AUTO_APPROVE  Auto-approve persistent agents (dev only)

    {_c('Admin:', _BOLD)}
      AGBUS_ADMIN_SUBJECTS    Comma-separated OIDC subs with admin access

    {_c('Testing', _BOLD)}
    ───────
      {_c('pytest tests/ -v', _CYAN)}                 # Run all tests

    {_c('Next Steps', _BOLD)}
    ──────────
      • Explore {_c('agentic_bus/agents/examples/', _DIM)}
      • Read {_c('AGENTS.md', _DIM)} for implementation details
      • See {_c('agbus.pdf', _DIM)} for protocol theory
      • Implement your own agent extending {_c('BaseAgent', _CYAN)}

    {_c('═' * 70, _BOLD)}
    """))


# ============================================================================
# Argument parser
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agbus",
        description="Agentic Bus – setup, administration & control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              agbus help                        Show comprehensive documentation
              agbus help quickstart             Step-by-step setup guide
              agbus serve                       Start the coordinator server
              agbus serve --host 127.0.0.1 -p 9000
              agbus db init                     Create database tables
              agbus agent list                  Show all persistent agents
              agbus agent list --status pending Show only pending agents
              agbus agent approve my-agent      Approve an enrolment
              agbus config show                 Display resolved config
              agbus config init                 Generate a .env file
        """),
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"%(prog)s {_version()}",
    )

    sub = parser.add_subparsers(dest="command", title="commands")

    # -- install (wizard) ----------------------------------------------------
    p_install = sub.add_parser(
        "install",
        help="Interactive setup wizard – configure, init DB, and start",
    )
    p_install.add_argument(
        "-o", "--output", type=str, default=".env",
        help="Output .env file path (default: .env)",
    )
    p_install.add_argument(
        "--force", action="store_true",
        help="Overwrite existing .env without asking",
    )
    p_install.set_defaults(func=cmd_install)

    # -- serve ---------------------------------------------------------------
    p_serve = sub.add_parser("serve", help="Start the coordinator server")
    p_serve.add_argument("--host", type=str, default=None, help="Bind address (default: $AGBUS_HOST or 0.0.0.0)")
    p_serve.add_argument("-p", "--port", type=int, default=None, help="Bind port (default: $AGBUS_PORT or 8765)")
    p_serve.set_defaults(func=cmd_serve)

    # -- db ------------------------------------------------------------------
    p_db = sub.add_parser("db", help="Database management")
    db_sub = p_db.add_subparsers(dest="db_command", title="db commands")

    p_db_init = db_sub.add_parser("init", help="Initialise database tables")
    p_db_init.set_defaults(func=cmd_db_init)

    # -- agent ---------------------------------------------------------------
    p_agent = sub.add_parser("agent", help="Manage agents")
    agent_sub = p_agent.add_subparsers(dest="agent_command", title="agent commands")

    p_list = agent_sub.add_parser("list", help="List all agents")
    p_list.add_argument("--status", type=str, default=None,
                        help="Filter by status (pending, approved, rejected, revoked, draft, active, disabled)")
    p_list.set_defaults(func=cmd_agent_list)

    p_show = agent_sub.add_parser("show", help="Show agent details")
    p_show.add_argument("agent_id", help="Agent identifier")
    p_show.set_defaults(func=cmd_agent_show)

    p_approve = agent_sub.add_parser("approve", help="Approve a pending agent")
    p_approve.add_argument("agent_id", help="Agent identifier")
    p_approve.set_defaults(func=cmd_agent_approve)

    p_reject = agent_sub.add_parser("reject", help="Reject a pending agent")
    p_reject.add_argument("agent_id", help="Agent identifier")
    p_reject.set_defaults(func=cmd_agent_reject)

    p_revoke = agent_sub.add_parser("revoke", help="Revoke an approved agent")
    p_revoke.add_argument("agent_id", help="Agent identifier")
    p_revoke.set_defaults(func=cmd_agent_revoke)

    p_delete = agent_sub.add_parser("delete", help="Delete an agent permanently")
    p_delete.add_argument("agent_id", help="Agent identifier")
    p_delete.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_delete.set_defaults(func=cmd_agent_delete)

    # -- agent create (managed agents) -----------------------------------------
    p_create = agent_sub.add_parser(
        "create",
        help="Create a new managed agent. Interactive if no args.",
    )
    p_create.add_argument("agent_id", nargs="?", default=None,
                          help="Agent identifier (interactive if omitted)")
    p_create.add_argument("--name", type=str, default=None, help="Display name")
    p_create.add_argument("--role", type=str, default=None, help="Agent role")
    p_create.add_argument("--goal", type=str, default=None, help="Agent goal")
    p_create.add_argument("--backstory", type=str, default=None, help="Agent backstory")
    p_create.add_argument("--llm-config", type=str, default=None,
                          help="Name of an LLM config to use (default: bus default)")
    p_create.add_argument("--verbose", action="store_true", default=False,
                          help="Enable verbose mode")
    p_create.add_argument("--max-iter", type=int, default=25,
                          help="Max iterations (default: 25)")
    p_create.add_argument("--no-memory", action="store_true", default=False,
                          help="Disable memory")
    p_create.add_argument("--tools", type=str, default=None,
                          help="Comma-separated list of tool names")
    p_create.add_argument("--activate", action="store_true", default=False,
                          help="Set status to 'active' immediately")
    p_create.set_defaults(func=cmd_agent_create)

    p_activate = agent_sub.add_parser("activate", help="Activate a managed agent")
    p_activate.add_argument("agent_id", help="Agent identifier")
    p_activate.set_defaults(func=cmd_agent_activate)

    p_disable = agent_sub.add_parser("disable", help="Disable a managed agent")
    p_disable.add_argument("agent_id", help="Agent identifier")
    p_disable.set_defaults(func=cmd_agent_disable)

    p_start = agent_sub.add_parser("start", help="Start a managed agent as an independent server")
    p_start.add_argument("agent_id", help="Agent identifier")
    p_start.add_argument("--coordinator-uri", type=str, default=None,
                         help="Coordinator WebSocket URI (default: ws://localhost:8765)")
    p_start.set_defaults(func=cmd_agent_start)

    p_add_cap = agent_sub.add_parser("add-capability",
                                     help="Add a capability to a managed agent")
    p_add_cap.add_argument("agent_id", help="Agent identifier")
    p_add_cap.add_argument("capability_id", nargs="?", default=None,
                           help="Capability ID (interactive if omitted)")
    p_add_cap.add_argument("--description", type=str, default=None,
                           help="Capability description")
    p_add_cap.add_argument("--expected-output", type=str, default=None,
                           help="Expected output description")
    p_add_cap.add_argument("--domains", type=str, default=None,
                           help="Tags (comma-separated)")
    p_add_cap.add_argument("--cost", type=str, default=None,
                           help="Estimated cost per invocation")
    p_add_cap.add_argument("--latency", type=str, default=None,
                           help="Estimated latency in seconds")
    p_add_cap.add_argument("--output-field", dest="output_fields", action="append",
                           metavar="NAME:TYPE:DESC",
                           help="Structured output field (repeatable). Format: name:type:description")
    p_add_cap.set_defaults(func=cmd_agent_add_capability)

    p_rm_cap = agent_sub.add_parser("remove-capability",
                                    help="Remove a capability from a managed agent")
    p_rm_cap.add_argument("agent_id", help="Agent identifier")
    p_rm_cap.add_argument("capability_id", help="Capability ID to remove")
    p_rm_cap.set_defaults(func=cmd_agent_remove_capability)

    p_tools = agent_sub.add_parser("tools",
                                   help="List tools agents can be given")
    p_tools.set_defaults(func=cmd_agent_tools)

    # -- llm -----------------------------------------------------------------
    p_scope = sub.add_parser("scope", help="Manage the scope vocabulary")
    scope_sub = p_scope.add_subparsers(dest="scope_command", title="scope commands")

    p_scope_list = scope_sub.add_parser("list", help="Show the scope catalogue")
    p_scope_list.set_defaults(func=cmd_scope_list)

    p_scope_add = scope_sub.add_parser("add", help="Add a scope to the catalogue")
    p_scope_add.add_argument("name", help="Scope name, e.g. carrier:quote")
    p_scope_add.add_argument("--description", type=str, default="",
                             help="What holding this permits")
    p_scope_add.set_defaults(func=cmd_scope_add)

    p_scope_rm = scope_sub.add_parser("remove", help="Remove a scope and its bindings")
    p_scope_rm.add_argument("name", help="Scope name")
    p_scope_rm.set_defaults(func=cmd_scope_remove)

    p_scope_bind = scope_sub.add_parser("bind", help="Grant scopes to a capability")
    p_scope_bind.add_argument("agent_id", help="Agent ID")
    p_scope_bind.add_argument("capability", help="Capability ID")
    p_scope_bind.add_argument("scopes", nargs="+", help="Catalogued scope names")
    p_scope_bind.set_defaults(func=cmd_scope_bind)

    p_scope_unbind = scope_sub.add_parser("unbind", help="Revoke a granted scope")
    p_scope_unbind.add_argument("agent_id", help="Agent ID")
    p_scope_unbind.add_argument("capability", help="Capability ID")
    p_scope_unbind.add_argument("scope", help="Scope name")
    p_scope_unbind.set_defaults(func=cmd_scope_unbind)

    p_scope_granted = scope_sub.add_parser("granted", help="Show what an agent holds")
    p_scope_granted.add_argument("agent_id", help="Agent ID")
    p_scope_granted.set_defaults(func=cmd_scope_granted)

    p_scope_req = scope_sub.add_parser("requests", help="Scopes agents asked for")
    p_scope_req.set_defaults(func=cmd_scope_requests)

    p_llm = sub.add_parser("llm", help="Manage LLM provider configurations")
    llm_sub = p_llm.add_subparsers(dest="llm_command", title="llm commands")

    p_llm_list = llm_sub.add_parser("list", help="List all LLM configurations")
    p_llm_list.set_defaults(func=cmd_llm_list)

    p_llm_show = llm_sub.add_parser("show", help="Show LLM configuration details")
    p_llm_show.add_argument("name", help="Configuration name")
    p_llm_show.set_defaults(func=cmd_llm_show)

    p_llm_add = llm_sub.add_parser("add", help="Add a new LLM configuration")
    p_llm_add.add_argument("--name", type=str, default=None,
                           help="Configuration name (interactive if omitted)")
    p_llm_add.add_argument("--provider", type=str, default=None,
                           help="LLM provider (openai, anthropic, google, ollama, azure)")
    p_llm_add.add_argument("--model", type=str, default=None,
                           help="Model name")
    p_llm_add.add_argument("--temperature", type=float, default=None,
                           help="Sampling temperature")
    p_llm_add.add_argument("--api-key", type=str, default=None,
                           help="API key")
    p_llm_add.add_argument("--base-url", type=str, default=None,
                           help="Base URL (for Ollama)")
    p_llm_add.add_argument("--azure-endpoint", type=str, default=None,
                           help="Azure OpenAI endpoint")
    p_llm_add.add_argument("--azure-deployment", type=str, default=None,
                           help="Azure deployment name")
    p_llm_add.add_argument("--azure-api-version", type=str, default=None,
                           help="Azure API version")
    p_llm_add.add_argument("--activate", action="store_true", default=False,
                           help="Set as the active configuration")
    p_llm_add.set_defaults(func=cmd_llm_add)

    p_llm_activate = llm_sub.add_parser("activate", help="Activate an LLM configuration")
    p_llm_activate.add_argument("name", help="Configuration name")
    p_llm_activate.set_defaults(func=cmd_llm_activate)

    p_llm_update = llm_sub.add_parser("update", help="Update an LLM configuration")
    p_llm_update.add_argument("name", help="Configuration name")
    p_llm_update.add_argument("--provider", type=str, default=None,
                              help="New LLM provider")
    p_llm_update.add_argument("--model", type=str, default=None,
                              help="New model name")
    p_llm_update.add_argument("--temperature", type=float, default=None,
                              help="New sampling temperature")
    p_llm_update.add_argument("--api-key", type=str, default=None,
                              help="New API key")
    p_llm_update.set_defaults(func=cmd_llm_update)

    p_llm_remove = llm_sub.add_parser("remove", help="Remove an LLM configuration")
    p_llm_remove.add_argument("name", help="Configuration name")
    p_llm_remove.add_argument("-y", "--yes", action="store_true",
                              help="Skip confirmation")
    p_llm_remove.set_defaults(func=cmd_llm_remove)

    # -- config --------------------------------------------------------------
    p_config = sub.add_parser("config", help="Configuration utilities")
    config_sub = p_config.add_subparsers(dest="config_command", title="config commands")

    p_cfg_show = config_sub.add_parser("show", help="Display resolved configuration")
    p_cfg_show.set_defaults(func=cmd_config_show)

    p_cfg_init = config_sub.add_parser("init", help="Generate a .env file from template")
    p_cfg_init.add_argument("-o", "--output", type=str, default=".env",
                            help="Output file path (default: .env)")
    p_cfg_init.add_argument("--force", action="store_true",
                            help="Overwrite if file exists")
    p_cfg_init.set_defaults(func=cmd_config_init)

    # -- help ----------------------------------------------------------------
    # -- conformance ---------------------------------------------------------
    p_conf = sub.add_parser(
        "conformance",
        help="Check an agent implementation against the LIP specification",
    )
    p_conf.add_argument(
        "--port", type=int, default=0,
        help="Port to listen on (default: pick a free one)",
    )
    p_conf.add_argument(
        "--host", type=str, default="127.0.0.1", help="Bind address",
    )
    p_conf.add_argument(
        "--wait", type=float, default=60.0,
        help="Seconds to wait for an agent to connect (default: 60)",
    )
    p_conf.add_argument(
        "--timeout", type=float, default=10.0,
        help="Seconds to allow for each protocol exchange (default: 10)",
    )
    p_conf.add_argument(
        "--json", action="store_true", help="Emit the report as JSON",
    )
    p_conf.set_defaults(func=cmd_conformance)

    p_help = sub.add_parser("help", help="Comprehensive documentation")
    p_help.add_argument("topic", nargs="?", default="overview",
                        choices=["overview", "architecture", "agents", "persistence", "admin", "quickstart"],
                        help="Help topic (default: overview)")
    p_help.set_defaults(func=cmd_help)

    return parser


#: Third-party modules that only the ``[server]`` extra installs. Used to turn
#: a bare ModuleNotFoundError into an instruction.
_SERVER_MODULES = frozenset({
    "sqlalchemy", "fastapi", "uvicorn", "jwt", "cryptography", "httpx",
    "langchain", "langchain_core", "langchain_openai", "langchain_anthropic",
    "langchain_google_genai", "langchain_ollama", "langgraph", "uvloop",
})

#: Modules belonging to the other extras.
_EXTRA_BY_MODULE = {
    "langchain_mcp_adapters": "mcp",
}


def _fail_missing_dependency(exc: ModuleNotFoundError) -> None:
    """Explain which extra provides a missing module, then exit.

    ``agbus`` ships with the base install, but most of its commands drive the
    coordinator, whose dependencies live behind ``[server]``. Without this the
    user just sees "No module named 'sqlalchemy'", which says nothing about
    how to fix it.
    """
    missing = (exc.name or "").split(".")[0]
    extra = _EXTRA_BY_MODULE.get(missing) or ("server" if missing in _SERVER_MODULES else None)

    print(file=sys.stderr)
    if extra is None:
        print(f"  {_c('✗ Error:', _RED)} missing dependency {missing!r}", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
    else:
        print(
            f"  {_c('✗ Error:', _RED)} this command needs the "
            f"{_c(f'[{extra}]', _BOLD)} extra, which is not installed.",
            file=sys.stderr,
        )
        print(f"  (missing module: {missing})", file=sys.stderr)
        print(file=sys.stderr)
        # Built outside the f-string: escaped quotes inside an f-string
        # expression are a syntax error before Python 3.12, and this project
        # supports 3.11.
        command = 'pip install "agentic-bus[{}]"'.format(extra)
        print(f"  Install it with: {_c(command, _BOLD)}", file=sys.stderr)
    print(file=sys.stderr)
    sys.exit(1)


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    try:
        args.func(args)
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except ModuleNotFoundError as exc:
        _fail_missing_dependency(exc)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
