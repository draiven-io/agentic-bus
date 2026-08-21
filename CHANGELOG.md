# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **protocol** version (`LIP_PROTOCOL_VERSION`) is versioned separately
from this package; protocol changes are called out explicitly below.

## [Unreleased]

### Fixed

- **Agents now reconnect.** When the connection dropped — a coordinator
  restart, a network blip, a proxy timeout — the receive loop exited while
  `run_forever` went on sleeping, so the agent was alive to a process
  supervisor and invisible to the bus, permanently. It now reconnects with
  exponential backoff and full jitter, and re-registers its capabilities each
  time (the coordinator's registry is per-connection, so a reconnect without
  re-registration is connected but undiscoverable). An agent started before
  its coordinator now retries instead of failing.
- **One slow task no longer blocks the whole agent.** Handlers were awaited
  inside the socket's receive loop, so a long `execute_task` stopped the agent
  reading anything else — including the `dissolve` telling it to stop. Intent
  and execute handling now dispatch onto their own tasks, bounded by
  `max_concurrent_tasks` (default 8).
- **`dissolve` cancels in-flight work.** It previously only logged, despite
  `BaseAgent` documenting that agents must support cancellation and the
  protocol specifying dissolution as *mandatory* cleanup. `execute_task` now
  receives `CancelledError` for the dissolved session only; other sessions
  keep running.

### Added

- `token_provider` on `BaseAgent`: supply a bearer token (sync or async) for
  coordinators running real OIDC. The dev identity was previously hardcoded,
  so the SDK could not authenticate against a secured bus at all. Called on
  every reconnection, so short-lived tokens refresh.
- `ReconnectPolicy` for tuning backoff, exported from the public API.
- `WSClient.wait_closed()` / `is_connected`, so a dropped connection is
  observable by the code that owns the client.

## [0.2.0]

### Changed — breaking

- **The importable package is now `agentic_bus`, not `app`.** `pip install
  agentic-bus` previously installed a top-level `app` package into
  site-packages, shadowing (or being shadowed by) the `app` module that
  nearly every FastAPI and Flask project has. Update imports:
  `from app.agents import BaseAgent` becomes
  `from agentic_bus import BaseAgent`.
- **The coordinator's dependencies moved behind a `[server]` extra.** The
  base install is now pydantic, websockets and OpenTelemetry — 13 packages
  in a clean venv, down from roughly 100 — which is all you need to write
  an agent. Running a coordinator needs
  `pip install "agentic-bus[server]"`; `agbus` reports this by name when
  the extra is missing.

### Added

- A real public API on the top-level package: `from agentic_bus import
  BaseAgent, AgentCapability, IntentClient, submit_intent` plus the
  protocol types. Writing an agent is now two methods against a documented
  surface rather than reaching into `app.*` internals.
- `tests/test_public_api.py`, which asserts the documented names are
  importable *and* that importing the package pulls in none of SQLAlchemy,
  FastAPI, LangChain, LangGraph, uvicorn or PyJWT — checked in a subprocess,
  since a development environment has every extra installed and would hide
  the regression.

## [0.1.0] — 2026-08-21

First release on PyPI.

### Added

- **`docker compose up` runs the whole stack with no API keys**: a local
  model (Ollama), the coordinator with the paper's four logistics agents
  seeded and running, and the dashboard on `:3000`. Previously the only way
  to see the bus run was a clone, two dependency installs, an LLM provider
  key, an interactive wizard and three manual processes.
- `[agents]`, `[mcp]` and `[all]` install extras. `crewai`/`crewai-tools`
  (managed agents) and `langchain-mcp-adapters` (MCP bridge) were used at
  runtime but declared nowhere, so `pip install agentic-bus` succeeded and
  then failed with a bare `ModuleNotFoundError` the first time you used
  either feature.
- `GET /health` — an unauthenticated, dependency-free liveness probe for
  container orchestrators. Reports the serving status and LIP protocol
  version; deliberately touches no database or LLM.
- A release workflow publishing to PyPI on a `v*` tag via Trusted Publishing
  (no stored API token), gated on the tag matching `pyproject.toml`.
- A CI job that builds both Docker images, validates the compose file, and
  asserts the lazily-imported extras are importable in the image.
- `protocol_version` on every message envelope (LIP `0.1.0`). Envelopes from
  pre-versioning peers are read as `0.1.0`, so the change is backwards
  compatible on the wire.
- Generated JSON Schemas for the envelope and every payload under `schemas/`,
  produced by `python -m app.core.protocol.export_schemas`. CI fails if they
  drift from the Pydantic models.
- `LICENSE` (MIT). The README and package metadata claimed MIT, but no
  licence text was ever committed — until now the code was, strictly,
  all rights reserved.
- Continuous integration: ruff, the test suite on Python 3.11/3.12/3.13, the
  protocol schema check, and the dashboard build.
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, and issue/PR templates.
- `SECURITY.md` documents the known limitations of LLM-evaluated IBAC.

### Changed

- `agbus agent list` rejects an unknown `--status` instead of reporting an
  empty result, which made a typo indistinguishable from "no agents".
- Package metadata now describes the project as the reference implementation
  of the **Liquid Interfaces Protocol**, with homepage, repository, spec and
  paper URLs for PyPI.
- Code comments that referred to "the Agentic Bus paper" now name the
  Liquid Interfaces paper (`lip.md`) consistently.

### Fixed

- The source distribution no longer ships the dashboard's `node_modules`.
  Hatchling's default sdist sweeps the project directory and honours only the
  *root* `.gitignore`, while `node_modules` is ignored by `ui/.gitignore` —
  so the archive was 86 MB across 25,741 files, over PyPI's 100 MB per-file
  limit. Now 243 KB across 113 files.
- The Swagger UI was documented at `/docs`; it is served at `/api/docs`.
- The README logo used a relative path, which does not render on PyPI where
  the README becomes the project description.
- `resolve_tools` no longer aborts agent creation when an optional tool's
  dependency chain fails to import. Only `ValueError` and `ImportError` were
  caught, so an incompatible transitive dependency surfacing as
  `AttributeError` took down the whole agent instead of skipping one tool.
- The test suite is hermetic. It previously inherited the developer's `.env`
  through `load_dotenv(find_dotenv(usecwd=True))` at import time and shared
  the host database, so 19 tests passed locally and failed on a clean
  checkout. Every test now gets a scrubbed environment and its own migrated
  database (`tests/conftest.py`).
- The install-wizard tests could hang the run indefinitely: a drifted answer
  list fell through to the final "Start the coordinator server now?" prompt,
  which defaults to *yes*, and booted a real coordinator. Exhausting the
  answers now raises instead.
- Test assertions that still expected LLM settings in `.env` now assert
  against the database, where the wizard has been writing them.
