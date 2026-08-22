# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **protocol** version (`LIP_PROTOCOL_VERSION`) is versioned separately
from this package; protocol changes are called out explicitly below.

## [Unreleased]

## [0.2.0] — 2026-08-22

The first release of the reference implementation as something you can build
an agent against. It is a breaking release in every dimension — package name,
protocol version, dependency set and authorization behaviour — and all of it
lands at once because none of it ever shipped: 0.1.0 is the only published
version, and it went up the day before.

### Changed — breaking

- **Managed agents run on LangGraph; CrewAI is gone.** LangGraph already
  orchestrates the coordinator, so a second agent framework bought nothing
  that could not be expressed with the one already present. What it cost was
  substantial: `crewai` and `crewai-tools` declare 87 direct requirements
  between them — including chromadb, litellm, onnxruntime, tokenizers and a
  second OpenTelemetry stack — to run what was, in the end, a single-agent
  single-task ReAct loop.

  Removed with it: the monkeypatch of CrewAI's private
  `LLM._get_native_provider` (the reason the pin was stuck at `<1.0` while
  upstream was on 1.15), and the `run_in_executor` thread offload that
  bridged its synchronous `kickoff()`. Execution is now async end to end, so
  cancelling a session reaches the running agent instead of stopping at the
  executor boundary.

- **The `[agents]` extra no longer exists.** Managed agents need nothing
  beyond `[server]`. Since `[agents]` only ever appeared in the unreleased
  0.2.0, nothing published is affected.

- **The tool catalogue is smaller and built in.** 31 re-exported
  `crewai_tools` classes are replaced by four tools implemented and tested
  here — `web_search` (Serper), `fetch_webpage`, `read_file`,
  `list_directory` — built on `langchain_core` and `httpx`, which the
  coordinator already depends on. Existing agents referencing old tool names
  will log a skipped-tool warning and run without them.

  `agentic_bus.agents.tools.register_tool()` is the extension point for
  anything else; supplying a domain tool is a better fit for a deployment
  than guessing at 31 from here.
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

### Changed — protocol

- **LIP 0.2.0: agent registration is now a protocol act.** Agents send
  `register` and receive `registered`; previously they sent `complete` with
  `session_id="__registration__"` and a nested payload — a shape the
  specification never described, so an agent written from the spec alone
  would connect and never be discovered. See
  [RFC 0001](https://github.com/draiven-io/liquid-interfaces/blob/main/rfcs/0001-register-performative.md).
- **Registration can now fail visibly.** It was fire-and-forget, so a
  coordinator that refused an agent said nothing and the agent stayed
  connected believing it was live. `registered` carries `accepted`, a
  `reason`, the capabilities actually accepted (which may be a subset), and
  the coordinator's protocol version. `BaseAgent.on_registration_refused()`
  is the hook for reacting.
- **Compatibility is asymmetric — upgrade coordinators before agents.** A
  0.2.0 coordinator still accepts the deprecated form, so old agents keep
  working; a 0.2.0 agent cannot register with a 0.1.0 coordinator. A missing
  `registered` is never fatal: the agent warns and carries on, because
  refusing to run against an older coordinator is worse than running without
  confirmation.

### Security

- **An IBAC approval now produces a bounded capability, and it is checked.**
  Approval previously governed only whether execution *started*: the returned
  constraints went to the audit log and were dropped, and the execute message
  carried `authorized_scopes: []`. An intention approved for "analyse sales"
  and one approved for "export everything" produced identical authority.

  Authorising execution now issues a `Capability` — principals, purpose,
  scopes, constraints and an expiry — stored on the session and checked
  before **every** dispatch, not once at the start. A multi-step flow can
  outlive the approval that began it, and a composed plan can name an agent
  the approval never covered; both are now refused, with the reason emitted
  as an IBAC event and carried in the audit trail. `authorized_scopes` is
  populated from the capability.

- **The Intent Manifest separates what an agent claims from what the
  coordinator establishes.** Purpose-based authorization is only as strong as
  purpose attestation: a rule reading a field the governed component wrote
  constrains nothing, because the agent writes something that passes.
  `declared` carries intent text, stated purpose and requested scopes;
  `derived` carries the authenticated subject, the identity resolved from the
  connection, and resource facts. A new invariant layer reads only `derived`,
  and `IBACResult.relies_on_declared_input` records whether a decision was a
  boundary or a heuristic.

- **Sender impersonation is detected and denied.** `envelope.sender.id` is
  written by the sender and was used as the governed agent identity without
  being checked against the authenticated connection — which the coordinator
  already tracks. An agent could have policy evaluated, and recorded in the
  audit trail, under another agent's identity.

- Four call sites gated on `decision == IBACDecision.ALLOW`, which was safe
  against DENY but would have rejected the new `ALLOW_WITH_SCOPE`. They now
  use `is_allowed` like the rest.

- **IBAC fails closed.** Every failure path previously ended in ALLOW: the
  decision key defaulted to `"allow"`, so a truncated or malformed model
  response authorised the intention; an unconfigured provider, a failed call
  and an unreadable rule store all fell through to a permissive evaluator.
  All of them now deny. An evaluation that did not happen is not permission.

  An empty rule set is deliberately still an ALLOW — that is a completed
  evaluation which found nothing prohibiting the intention, not a failure,
  and denying there would make an unconfigured bus refuse everything.

- **The two policy layers are ANDed rather than short-circuited.** The
  grounded (deterministic) and semantic (model) layers both run on every
  intention and the stricter outcome wins, so a grounded rule can deny
  something the model approved. Previously whichever layer matched first
  returned, which meant a semantic ALLOW ended the evaluation and the
  grounded guarantees never applied — the one property the grounded layer
  exists to provide.

- **`require_human_approval` now blocks.** It was returned as a constraint on
  an ALLOW that nothing downstream read, so an intention requiring sign-off
  executed anyway. It is now its own decision, and does not permit execution.

- The IBAC prompt states that intent text is untrusted input and that
  instructions embedded in it are evidence of attempted evasion. This is
  mitigation, not a guarantee: the accompanying tests assert that a grounded
  denial survives a semantic approval obtained by injection.
- **All 91 Dependabot alerts resolved** (37 high, 48 moderate, 6 low). Every
  one was in `ui/package-lock.json`; none were Python. Next.js 16.1.6 →
  16.3.2 clears 28 directly and carries patched `postcss` and `sharp`;
  shadcn 3.8.5 → 4.19.0 clears the 33 that arrived through its bundled
  `@modelcontextprotocol/sdk` → `@hono/node-server` → `hono` chain. The rest
  were transitive and resolve with the regenerated lockfile. `npm audit` now
  reports zero.

### Added

- `tests/test_langgraph_agents.py`. Managed agents were previously untested
  at the execution level because exercising them meant standing up CrewAI; a
  LangGraph agent can be driven by a fake chat model, so building, tool
  binding, and running an agent are now covered without a provider.
- **`AGENTS.md` is back.** Nine modules cite it by section number for their
  normative behaviour, but it was committed once and removed in the second
  commit — so every one of those citations had been dangling since. Recovered
  from git history and brought current: the paper is `lip.md` not `agbus.md`,
  the LangChain pin is a range resolved at runtime rather than
  `langchain==1.2.9`, the message model covers LIP 0.2.0 including
  `register`/`registered` and `protocol_version`, and the module layout
  matches the `agentic_bus` package. Reframed as an *implementation guide* —
  the protocol specification lives in the liquid-interfaces repository, and
  `schemas/` is authoritative for the wire format.
- `tests/test_docs_references.py`, which fails if a docstring cites a section
  that does not exist, if section numbering develops gaps (renumbering breaks
  existing citations), or if the citation patterns stop matching anything.
  Nothing failed when the file disappeared, which is why nobody noticed.
- **`agentic_bus.testing`** — a stand-in coordinator so an agent can be
  tested with no Docker, no model provider and no network:

  ```python
  async with LocalBus() as bus:
      agent = await bus.add_agent(WeatherAgent(agent_id="weather-01"))
      result = await bus.execute(agent.agent_id, {"city": "Lisbon"})
  ```

  It speaks LIP over a real socket rather than calling handlers directly, so
  serialisation, the receive loop and concurrency all take part. Beyond
  `execute`, it can drive intents and collect offers, dissolve sessions,
  expose the full message transcript and progress events, report the token
  the agent sent, and simulate a coordinator that refuses registration or
  predates LIP 0.2.0. Works on the base install — asserted by a test, since
  an agent author should not need a coordinator to test an agent.
- `BaseAgent.is_running`, a public way to ask whether an agent is connected
  and serving.
- `LocalBus.send()` — the low-level escape hatch beneath `send_intent` and
  `execute`, for starting work you do not intend to wait for, or for message
  shapes those helpers do not cover.
- `token_provider` on `BaseAgent`: supply a bearer token (sync or async) for
  coordinators running real OIDC. The dev identity was previously hardcoded,
  so the SDK could not authenticate against a secured bus at all. Called on
  every reconnection, so short-lived tokens refresh.
- `ReconnectPolicy` for tuning backoff, exported from the public API.
- The coordinator URI is never written to the log. It may legitimately carry
  credentials (`ws://agent:pw@host:8765`) and the reconnect loop logs on every
  attempt, so anything unsafe there is written repeatedly. Log lines identify
  the agent instead; the target is already in its configuration. Connection
  errors, which routinely quote the URI they failed on, have any
  `user:password@` stripped from them by a sanitiser that is never handed the
  credential.
- `WSClient.wait_closed()` / `is_connected`, so a dropped connection is
  observable by the code that owns the client.
- A real public API on the top-level package: `from agentic_bus import
  BaseAgent, AgentCapability, IntentClient, submit_intent` plus the
  protocol types. Writing an agent is now two methods against a documented
  surface rather than reaching into `app.*` internals.
- `tests/test_public_api.py`, which asserts the documented names are
  importable *and* that importing the package pulls in none of SQLAlchemy,
  FastAPI, LangChain, LangGraph, uvicorn or PyJWT — checked in a subprocess,
  since a development environment has every extra installed and would hide
  the regression.

### Changed

- `IBACDecision` gains `ALLOW_WITH_SCOPE` and `REQUIRE_HUMAN_APPROVAL`, and a
  `permits_execution` property. `IBACResult.is_allowed` is now the supported
  way to gate on a decision — a check written as `decision == DENY` treats
  every outcome added later, including "evaluation failed", as permission.
  The three call sites in the coordinator and execution supervisor were doing
  exactly that and have been migrated.
- `IBACResult.decided_by` records which layer produced the outcome
  (`semantic`, `grounded`, `both`, or `fail-closed`), for audit.

### Fixed

- Three React anti-patterns the stricter React Compiler rules in
  `eslint-config-next` 16.3 surfaced in existing dashboard code: `useIsMobile`
  synced a media query through `setState` in an effect (now
  `useSyncExternalStore`, which also removes the first-paint flash); the
  agent-create form derived its display name in an effect that referenced a
  function before declaration (now derived during render); and `useAsync`
  passed a runtime value as a `useCallback` dependency list (the effect now
  owns the caller's dependencies).
- **An envelope with no `protocol_version` is read as `0.1.0` again.**
  Bumping the version constant silently changed what a legacy peer's message
  parsed as, since the field's default tracked the current version.
  `AgBusEnvelope.from_wire()` now applies the fixed `LIP_LEGACY_VERSION` when
  the field is absent, while envelopes we construct are still stamped with
  the current version. The transport parses through it.

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
