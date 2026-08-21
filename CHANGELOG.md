# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **protocol** version (`LIP_PROTOCOL_VERSION`) is versioned separately
from this package; protocol changes are called out explicitly below.

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
