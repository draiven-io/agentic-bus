<p align="center">
  <!-- Absolute URL so the logo also renders on PyPI, where the README
       is the project description and relative paths do not resolve. -->
  <img src="https://raw.githubusercontent.com/draiven-io/agentic-bus/main/agentic_bus.png" alt="Agentic Bus" width="600" />
</p>

<h1 align="center">Agentic Bus</h1>

<p align="center">
  <strong>Reference implementation of the Liquid Interfaces Protocol</strong><br>
  A dynamic, negotiation-driven, multi-agent coordination runtime where interfaces are not static contracts — they are ephemeral relational events.
</p>

<p align="center">
  <a href="#-see-it-work">See It Work</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-key-concepts">Key Concepts</a> •
  <a href="#-admin-dashboard-ui">Dashboard UI</a> •
  <a href="#-admin-rest-api">REST API</a> •
  <a href="#-cli-reference">CLI Reference</a> •
  <a href="#-testing">Testing</a> •
  <a href="#-contributing">Contributing</a> •
  <a href="#-license">License</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/agentic-bus/"><img src="https://img.shields.io/pypi/v/agentic-bus.svg" alt="PyPI" /></a>
  <a href="https://github.com/draiven-io/agentic-bus/actions/workflows/ci.yml"><img src="https://github.com/draiven-io/agentic-bus/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-≥3.11-blue.svg" alt="Python 3.11+" /></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/built%20with-LangGraph-orange" alt="LangGraph" /></a>
  <a href="https://nextjs.org"><img src="https://img.shields.io/badge/UI-Next.js%2016-black" alt="Next.js 16" /></a>
</p>

---

## 🧭 Overview

**Agentic Bus** introduces a coordination paradigm in which interfaces are **not** persistent technical artifacts, but **ephemeral relational events** that emerge through intention articulation and semantic negotiation at runtime.

Instead of pre-wired API contracts, a requesting agent simply states its intent in natural language — e.g., *"deliver this container within 200 km of the closed port, optimizing for cost and time"* — and the runtime **discovers** capable agents, **negotiates** terms, **composes** an execution graph, and **dissolves** everything once the task is complete, leaving zero technical debt.

> 📄 Read the full paper: [**lip.md**](lip.md) — *"Liquid Interfaces: A Dynamic Ontology for the Interoperability of Autonomous Systems"*

---

## 👀 See it work

A single sentence — *"a storm has closed the Port of Rotterdam, reroute our
refrigerated pharmaceuticals from Hamburg to Madrid within 5 days"* — decomposed,
negotiated across four agents that were never wired to each other, executed,
and dissolved.

**The plan, waiting for a human.** The coordinator has admitted the intent,
broken it into sub-intents, discovered which agents can serve them, collected
their offers and composed an execution graph — and stops there, because
committing to a carrier creates a contractual obligation.

<img src="https://raw.githubusercontent.com/draiven-io/agentic-bus/main/docs/images/01-negotiation-plan.png" alt="An execution plan awaiting approval, with its rationale and the agents that offered" width="100%" />

**Approved and carried out.** Every step green, agent quality scored, and the
session dissolved on completion — Invariant II: nothing outlives the
interaction that created it.

<img src="https://raw.githubusercontent.com/draiven-io/agentic-bus/main/docs/images/02-negotiation-complete.png" alt="The completed execution graph, timeline and synthesised result" width="100%" />

**Authorisation, at five points in the lifecycle.** IBAC judges the *purpose*
of a request, not the endpoint it targets — so the same intent is evaluated
again at admission, offer eligibility, negotiation, execution and artifact
emission, each time against what is known by then.

<img src="https://raw.githubusercontent.com/draiven-io/agentic-bus/main/docs/images/06-ibac.png" alt="IBAC policies across five evaluation points" width="100%" />

**And the run afterwards.** Which agents took part, what they cost, what was
produced, and every decision that allowed it.

<img src="https://raw.githubusercontent.com/draiven-io/agentic-bus/main/docs/images/04-dashboard.png" alt="The coordinator dashboard" width="100%" />

<sub>Reproduce these against your own bus with
<code>node ui/scripts/capture-screenshots.mjs http://localhost:3000</code> — it drives a
real intent through a running coordinator rather than mocking one.</sub>

---

## ✨ Key Concepts

| Principle | Description |
|---|---|
| **Intent-first** | Coordination starts from a natural-language objective, not from an endpoint or schema. |
| **Negotiated** | Interfaces emerge through semantic negotiation at runtime — no prior contracts required. |
| **Ephemeral** | All coordination artifacts are dissolved after task completion — zero technical debt. |
| **Governed** | IBAC (Intention-Based Access Control) is enforced at every phase of the lifecycle. |

### How is this different?

| Paradigm | Focus | Agentic Bus Difference |
|---|---|---|
| REST / GraphQL | Static contracts & schemas | No pre-defined endpoints; interfaces emerge dynamically |
| Service Mesh | Syntactic routing between known services | Semantic discovery & negotiation among unknown agents |
| FIPA-ACL | Formal logic between rational agents | Probabilistic LLM-driven negotiation; tolerates heterogeneous reasoning |
| Smart Contracts | Immutable deterministic agreements | Ephemeral, adaptive contracts that dissolve post-execution |
| MCP | "What is available?" (tool exposure) | "What should happen?" (intent orchestration) — complementary; MCP servers join the bus via the MCP bridge |
| A2A | Agent-to-agent messaging over declared Agent Cards | A layer above: intent expressed before a counterparty is known, plus purpose-bound governance (IBAC). A2A can carry LIP as transport |

---

## 🏗️ Architecture

```
                          ┌──────────────┐
                          │   Dashboard  │  (Next.js 16 — ui/)
                          │   React UI   │
                          └──────┬───────┘
                                 │ REST
                                 ▼
Requester ──WebSocket──► Coordinator ──WebSocket──► Provider Agents
                              │  │
                         ┌────┘  └────┐
                    ┌────┴────┐  Admin REST API
                    │ LangGraph│  (FastAPI :8766)
                    └────┬────┘
                         │
               IBAC ◄────┤────► Registry
                         │
                    Telemetry (OTel)
                         │
                    Persistence (SQLAlchemy)
```

The **Coordinator** implements the full Agentic Bus session lifecycle:

1. **Accept & authenticate** WebSocket connections (OIDC)
2. **Open** intent sessions
3. **Discover** eligible agents via semantic adjudication
4. **Request** offers from matching agents
5. **Evaluate** offers through IBAC governance
6. **Negotiate & compose** offers into an execution plan
7. **Build** a LangGraph dynamically
8. **Supervise** execution with failure handling
9. **Dissolve** the session — all artifacts are ephemeral

### Project Layout

```
agentic-bus/
│
├── docker-compose.yml          # Full stack: Ollama + coordinator + dashboard
├── Dockerfile                  # Coordinator image
├── docker/                     # Container entrypoint
├── schemas/                    # Generated LIP JSON Schemas (see CONTRIBUTING)
│
├── agentic_bus/                # Python package
│   ├── cli.py                  # CLI entry point (agbus command)
│   ├── core/                   # Shared infrastructure
│   │   ├── protocol/           #   Message model & envelope
│   │   ├── transport/          #   WebSocket server / client
│   │   ├── session/            #   Session lifecycle management
│   │   ├── registry/           #   Dynamic capability registry
│   │   ├── ibac/               #   Intention-Based Access Control engine
│   │   ├── telemetry/          #   OpenTelemetry instrumentation
│   │   ├── auth/               #   OIDC authentication & admin auth
│   │   ├── llm/                #   Multi-provider LLM factory
│   │   └── persistence/        #   SQLAlchemy models & repositories
│   │       ├── models.py       #     DB models (agents, tenants, users, IBAC rules, LLM configs)
│   │       ├── repository.py   #     Agent repository
│   │       ├── tenant_repository.py
│   │       ├── user_repository.py
│   │       ├── ibac_repository.py
│   │       ├── llm_repository.py
│   │       └── managed_agent_repository.py
│   │
│   ├── coordinator/            # Coordination runtime
│   │   ├── server.py           #   Server entry point (WS + REST)
│   │   ├── runtime.py          #   Core coordinator runtime
│   │   ├── intent/             #   Intent admission & decomposition
│   │   ├── negotiation/        #   Offer collection, scoring, composition
│   │   ├── graph/              #   Dynamic LangGraph synthesis
│   │   ├── execution/          #   Supervised execution & failure handling
│   │   └── admin/              #   Admin REST API (FastAPI)
│   │       ├── api.py          #     All REST endpoints
│   │       ├── service.py      #     Business logic
│   │       ├── schemas.py      #     Pydantic DTOs
│   │       ├── serializers.py  #     Model → DTO serializers
│   │       └── audit.py        #     Audit logging
│   │
│   └── agents/                 # Agent SDK & examples
│       ├── base/               #   Base agent framework
│       ├── factory.py          #   Agent factory (CrewAI integration)
│       ├── managed_server.py   #   Managed agent server
│       ├── requester.py        #   Intent requester client
│       └── examples/           #   Sample provider agents
│           ├── logistics_agent/
│           └── intent_client_example.py
│
├── ui/                         # Admin Dashboard (Next.js 16)
│   ├── src/
│   │   ├── app/                #   App Router pages
│   │   │   ├── page.tsx        #     Dashboard home (stats overview)
│   │   │   ├── agents/         #     Agent management (persistent & managed)
│   │   │   ├── intent/         #     Intent session inspector
│   │   │   ├── ibac/           #     IBAC rule management
│   │   │   ├── audit/          #     Audit log viewer
│   │   │   ├── tenants/        #     Multi-tenant management
│   │   │   ├── users/          #     User administration
│   │   │   └── settings/       #     Coordinator & LLM settings
│   │   ├── components/         #   Reusable UI components (shadcn/ui)
│   │   ├── hooks/              #   Custom React hooks
│   │   │   ├── use-async.ts    #     Async data fetching
│   │   │   └── use-intent-ws.ts#     WebSocket intent streaming
│   │   └── lib/                #   Shared utilities
│   │       ├── api.ts          #     REST API client
│   │       ├── protocol.ts     #     Protocol type definitions
│   │       └── types.ts        #     TypeScript types
│   └── package.json
│
└── tests/                      # Test suite (22 modules, 411 tests)
    ├── test_admin.py
    ├── test_auth.py
    ├── test_cli.py
    ├── test_graph.py
    ├── test_ibac.py
    ├── test_ibac_rules.py
    ├── test_intent_client.py
    ├── test_llm_config.py
    ├── test_llm_factory.py
    ├── test_managed_agents.py
    ├── test_negotiation.py
    ├── test_persistence.py
    ├── test_protocol.py
    ├── test_registry.py
    ├── test_session.py
    ├── test_telemetry.py
    └── test_tenants_users.py
```

---

## 🚀 Quick Start

### Try it with no API keys

```bash
git clone https://github.com/draiven-io/agentic-bus.git && cd agentic-bus && docker compose up
```

That brings up a local model (Ollama), the coordinator with the paper's four
logistics agents already seeded and running, and the dashboard:

| | |
|---|---|
| **Dashboard** | http://localhost:3000 |
| **REST API** | http://localhost:8766/api/docs |
| **LIP bus** | ws://localhost:8765 |

Open the dashboard, go to **Intent**, and submit something like *"a storm has
closed the port — find me an alternative route and tell me what it costs"*.
You'll watch discovery, negotiation, plan approval, execution and dissolution
happen live.

> **On the local model.** The compose stack defaults to `qwen2.5:3b` so the
> first run is a ~2 GB download rather than a signup. It is enough to watch
> the full lifecycle, but negotiation quality scales with the model. For
> results worth judging the paradigm on, point the coordinator at a hosted
> model — set `AGBUS_BOOTSTRAP_LLM_PROVIDER`, `AGBUS_BOOTSTRAP_LLM_MODEL` and
> `AGBUS_BOOTSTRAP_LLM_API_KEY` in `docker-compose.yml`, or pick a larger
> local one with `AGBUS_DEMO_MODEL=qwen2.5:14b docker compose up`.

### Write an agent

```bash
pip install agentic-bus
```

That is a small install — pydantic, websockets and OpenTelemetry — because
writing an agent should not require a web framework, an ORM and an LLM stack.
An agent is two methods:

```python
from agentic_bus import AgentCapability, BaseAgent


class WeatherAgent(BaseAgent):
    def capabilities(self):
        return [AgentCapability(
            capability_id="forecast",
            description="Weather forecast for a city",
        )]

    async def execute_task(self, payload, context):
        return {"forecast": "sunny"}


WeatherAgent(agent_id="weather-01").run_forever()
```

It connects to a coordinator (`AGBUS_COORDINATOR_URI`, default
`ws://localhost:8765`), registers its capabilities, and from then on
participates in discovery, negotiation, IBAC governance and execution. You
never write an endpoint, a schema or a route.

The runtime handles the parts that bite in production:

- **Reconnects** with exponential backoff and jitter, and **re-registers** on
  every reconnect — a coordinator restart doesn't leave the agent silently
  orphaned.
- **Runs tasks concurrently** (bounded by `max_concurrent_tasks`, default 8),
  so one slow task doesn't stop the agent answering anything else.
- **Cancels in-flight work on `dissolve`**, so `execute_task` receives
  `CancelledError` and can clean up — the protocol's ephemerality guarantee
  is actually enforced, not just documented.

For a coordinator with real OIDC, supply a token provider. It's called on
every reconnect, so short-lived tokens refresh rather than going stale:

```python
WeatherAgent(
    agent_id="weather-01",
    token_provider=lambda: my_oidc_client.access_token(),   # may be async
)
```

Submitting an intent is the other half:

```python
from agentic_bus import submit_intent

result = await submit_intent("what's the weather in Lisbon?")
```

### Test it without any of the infrastructure

`agentic_bus.testing` ships a stand-in coordinator, so testing an agent needs
no Docker, no model provider and no network:

```python
from agentic_bus.testing import LocalBus

async def test_forecast():
    async with LocalBus() as bus:
        agent = await bus.add_agent(WeatherAgent(agent_id="weather-01"))

        result = await bus.execute(agent.agent_id, {"city": "Lisbon"})

        assert result.status == "success"
        assert result.artifacts[0]["forecast"] == "sunny"
```

It speaks LIP over a real socket rather than calling your handlers directly,
so serialisation, the receive loop and concurrency all take part — faking
those out is what lets connection-level bugs survive a green suite. You can
also drive intents (`send_intent`), tear sessions down (`dissolve`), inspect
the transcript (`messages`, `events`), check the token your agent sent
(`auth_headers`), and simulate a coordinator that refuses registration or
predates LIP 0.2.0.

It is not a coordinator: discovery and negotiation are LLM-driven in the real
runtime and are not reproduced, so tests stay deterministic. Use it to check
what your agent *does*, not how a coordinator would choose it.

### Check an implementation against the specification

`agbus conformance` drives a candidate agent over a real WebSocket and reports,
per requirement, whether it behaved as LIP says it must:

```bash
agbus conformance --port 9100
```

Point your agent at the printed URI. It speaks only the protocol, so the agent
under test can be written in any language — which is the point: a
specification becomes a standard when a second implementation can be built
from it and shown to interoperate.

Requirements are graded. A **MUST** failure means the implementation is not
conformant; a **SHOULD** failure is reported without failing the run. `--json`
emits a machine-readable report for CI.

The reference SDK is tested against this suite, so if `BaseAgent` ever stops
satisfying the specification it publishes, our own build fails.

### Run a coordinator

The coordinator is a much heavier thing — LangGraph, FastAPI, SQLAlchemy, the
LLM providers — so it lives behind an extra:

```bash
pip install "agentic-bus[server]"
```

```bash
agbus install && agbus serve
```

`agbus install` is an interactive wizard: it writes a `.env` for the server
and database settings and stores your LLM provider in the database. To skip
the wizard, see [Configuration](#configuration) below.

### Install matrix

| Command | Gives you |
|---|---|
| `pip install agentic-bus` | Write agents, submit intents, speak LIP |
| `pip install "agentic-bus[server]"` | Run a coordinator (`agbus serve`), including the managed agents it hosts |
| `pip install "agentic-bus[mcp]"` | Bridge MCP servers onto the bus |
| `pip install "agentic-bus[all]"` | Everything |

Commands that need an extra you don't have say so, and name the extra.

### Develop against a checkout

```bash
git clone https://github.com/draiven-io/agentic-bus.git
cd agentic-bus
pip install -e ".[dev]"
```

```bash
agbus serve
```

```bash
cd ui && npm install && npm run dev
```

```bash
python -m agentic_bus.agents.examples.logistics_agent.agent
```

> **⚠️ Note:** run `agbus` from the directory containing your `.env`.

### Configuration

Configuration is split in two, deliberately:

| What | Where | Why |
|---|---|---|
| Server, database, OIDC | `.env` | Needed before the process can reach a database |
| LLM providers (and their API keys) | Database | Switchable at runtime without restarting the coordinator; credentials never sit in a file |

`agbus install` writes the `.env` and stores your first LLM provider in the
database. Add or switch providers later without touching either by hand:

```bash
agbus llm add --name prod --provider anthropic --model claude-sonnet-4-20250514 --api-key sk-ant-... --activate
```

```bash
agbus llm list
```

The `.env` covers the runtime itself:

```env
AGBUS_HOST=0.0.0.0
AGBUS_PORT=8765
AGBUS_DATABASE_URL=sqlite:///agbus_agents.db
AGBUS_AGENT_AUTO_APPROVE=false
```

<details>
<summary>Supported LLM providers</summary>

`openai`, `anthropic`, `google`, `azure`, and `ollama` (local, no API key).
Azure additionally needs an endpoint, deployment name and API version, which
`agbus install` and `agbus llm add` both prompt for.

</details>

Run `agbus config show` to display the resolved runtime configuration and the
active LLM provider.

---

## 🖥️ Admin Dashboard (UI)

The **Admin Dashboard** is a full-featured Next.js 16 application that provides a visual management interface for the entire Agentic Bus runtime. Built with **React 19**, **Tailwind CSS 4**, **shadcn/ui**, and **Recharts**.

### Pages

| Page | Description |
|---|---|
| **Dashboard** (`/`) | Real-time stats overview — active agents, sessions, recent audit events |
| **Agents** (`/agents`) | Manage persistent (self-enrolled) and managed (coordinator-created) agents; approve, reject, revoke, activate, disable |
| **Create Agent** (`/agents/create`) | Interactive form to create a new managed agent with capabilities and CrewAI tool selection |
| **Intent** (`/intent`) | Live intent session inspector with WebSocket streaming |
| **IBAC Rules** (`/ibac`) | Create, edit, and delete Intention-Based Access Control rules |
| **Audit Log** (`/audit`) | Searchable audit trail of all administrative actions |
| **Tenants** (`/tenants`) | Multi-tenant management — create tenants, assign agents to tenants |
| **Users** (`/users`) | User administration — create, edit, assign roles and tenants |
| **Settings** (`/settings`) | Coordinator configuration and LLM provider management |

### Running the UI

```bash
cd ui
npm install
npm run dev       # Development mode (http://localhost:3000)
npm run build     # Production build
npm run start     # Production server
```

---

## 🔌 Admin REST API

The coordinator exposes a **FastAPI** admin REST API on port `8766` (configurable via `AGBUS_API_PORT`). Interactive Swagger documentation is available at `/api/docs`, and an unauthenticated liveness probe at `/health`.

### Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/admin/stats` | Dashboard statistics |
| `GET` | `/api/admin/me` | Current authenticated user |
| | | |
| `GET` | `/api/admin/agents/persistent` | List persistent (self-enrolled) agents |
| `GET` | `/api/admin/agents/persistent/{id}` | Get a persistent agent |
| `POST` | `/api/admin/agents/persistent/{id}/approve` | Approve enrolment |
| `POST` | `/api/admin/agents/persistent/{id}/reject` | Reject enrolment |
| `POST` | `/api/admin/agents/persistent/{id}/revoke` | Revoke an agent |
| `DELETE` | `/api/admin/agents/persistent/{id}` | Delete an agent |
| | | |
| `GET` | `/api/admin/agents/managed` | List managed agents |
| `GET` | `/api/admin/agents/managed/{id}` | Get a managed agent |
| `POST` | `/api/admin/agents/managed` | Create a managed agent |
| `POST` | `/api/admin/agents/managed/{id}/activate` | Activate |
| `POST` | `/api/admin/agents/managed/{id}/disable` | Disable |
| `DELETE` | `/api/admin/agents/managed/{id}` | Delete |
| | | |
| `GET` | `/api/admin/agents/ephemeral` | List ephemeral (in-session) agents |
| `GET` | `/api/admin/agents/tools` | List available CrewAI tools |
| | | |
| `GET` | `/api/admin/sessions` | List active sessions |
| `GET` | `/api/admin/audit` | Query audit log |
| | | |
| `GET` | `/api/admin/tenants` | List tenants |
| `GET` | `/api/admin/tenants/{id}` | Get a tenant |
| `POST` | `/api/admin/tenants` | Create a tenant |
| `PUT` | `/api/admin/tenants/{id}` | Update a tenant |
| `DELETE` | `/api/admin/tenants/{id}` | Delete a tenant |
| `POST` | `/api/admin/tenants/{id}/agents/{agent_id}` | Assign agent to tenant |
| `DELETE` | `/api/admin/tenants/{id}/agents/{agent_id}` | Remove agent from tenant |
| | | |
| `GET` | `/api/admin/users` | List users |
| `GET` | `/api/admin/users/{id}` | Get a user |
| `POST` | `/api/admin/users` | Create a user |
| `PUT` | `/api/admin/users/{id}` | Update a user |
| `DELETE` | `/api/admin/users/{id}` | Delete a user |
| | | |
| `GET` | `/api/admin/ibac/rules` | List IBAC rules |
| `GET` | `/api/admin/ibac/rules/{id}` | Get an IBAC rule |
| `POST` | `/api/admin/ibac/rules` | Create an IBAC rule |
| `PUT` | `/api/admin/ibac/rules/{id}` | Update an IBAC rule |
| `DELETE` | `/api/admin/ibac/rules/{id}` | Delete an IBAC rule |
| | | |
| `GET` | `/api/admin/llm/configs` | List LLM configurations |
| `POST` | `/api/admin/llm/configs` | Create an LLM configuration |
| `POST` | `/api/admin/llm/configs/{name}/activate` | Activate a configuration |
| `PUT` | `/api/admin/llm/configs/{name}` | Update a configuration |
| `DELETE` | `/api/admin/llm/configs/{name}` | Delete a configuration |
| | | |
| `GET` | `/api/admin/settings` | Get coordinator settings |

---

## 💻 CLI Reference

```
agbus install                          # Interactive setup wizard
agbus serve                            # Start the coordinator server

agbus db init                          # Create / migrate database tables

agbus agent list                       # List all registered agents
agbus agent show  <id>                 # Inspect a single agent
agbus agent approve <id>               # Approve a pending enrolment
agbus agent reject  <id>               # Reject a pending enrolment
agbus agent revoke  <id>               # Revoke an approved agent
agbus agent delete  <id>               # Permanently remove an agent
agbus agent create                     # Create a managed agent (interactive)
agbus agent activate <id>              # Activate a managed agent
agbus agent disable <id>               # Disable a managed agent
agbus agent add-capability <id>        # Add capability to a managed agent
agbus agent remove-capability <id> <c> # Remove a capability
agbus agent tools                      # List available CrewAI tools

agbus llm list                         # List LLM configurations
agbus llm show <name>                  # Inspect one configuration
agbus llm add                          # Add a provider configuration
agbus llm activate <name>              # Make a configuration current
agbus llm update <name>                # Update a configuration
agbus llm remove <name>                # Delete a configuration

agbus config show                      # Display resolved configuration
agbus config init                      # Write a starter .env file

agbus help                             # Comprehensive documentation
agbus help quickstart                  # Step-by-step setup guide
```

---

## 🧪 Testing

The project includes a comprehensive test suite — **411 tests** across 22
modules — covering every subsystem.

The suite is **hermetic**: it ignores your `.env`, requires no API keys, and
never touches the network. Each test gets a scrubbed environment and its own
migrated database (see `tests/conftest.py`), so a green run on your machine
means a green run in CI.

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_negotiation.py

# Run with verbose output
pytest -v
```

### Test Coverage

| Test File | Subsystem |
|---|---|
| `test_protocol.py` | Message model & envelope |
| `test_session.py` | Session lifecycle |
| `test_registry.py` | Capability registry |
| `test_auth.py` | OIDC authentication |
| `test_ibac.py` | IBAC engine |
| `test_ibac_rules.py` | IBAC rule CRUD |
| `test_negotiation.py` | Negotiation engine |
| `test_graph.py` | LangGraph builder |
| `test_persistence.py` | Database persistence |
| `test_admin.py` | Admin REST API |
| `test_managed_agents.py` | Managed agent lifecycle |
| `test_llm_config.py` | LLM configuration management |
| `test_llm_factory.py` | Multi-provider LLM factory |
| `test_intent_client.py` | Intent requester client |
| `test_telemetry.py` | OpenTelemetry tracing |
| `test_cli.py` | CLI commands |
| `test_tenants_users.py` | Multi-tenant & user management |
| `test_agent_stats.py` | Agent scoring & latency priors |
| `test_execution_supervisor.py` | Supervised execution & failure handling |
| `test_mcp_bridge.py` | MCP server bridging |
| `test_session_memory.py` | Session memory policies |
| `test_validation.py` | Assigned-validator renegotiation loop |

---

## 🗺️ Roadmap

- [x] Admin Dashboard (Web UI)
- [x] Admin REST API (FastAPI)
- [x] Multi-tenant & user management
- [x] IBAC rule management
- [x] Audit logging
- [x] LLM configuration management
- [x] Managed agent lifecycle (CrewAI integration)
- [ ] Distributed coordinator clustering
- [ ] Persistent session replay & auditing
- [ ] Agent marketplace & trust scoring
- [ ] Plugin system for custom negotiation strategies
- [ ] Multi-modal intent support (voice, image, structured data)

---

## 🤝 Contributing

Contributions are welcome! Whether it's bug reports, feature requests, documentation improvements, or code contributions — we'd love your help.

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

Please make sure all tests pass before submitting:

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

---

## 📖 Citation

If you use Agentic Bus in your research, please cite:

```bibtex
@misc{desá2026liquidinterfacesdynamicontology,
      title={Liquid Interfaces: A Dynamic Ontology for the Interoperability of Autonomous Systems}, 
      author={Dhiogo de Sá and Carlos Schmiedel and Carlos Pereira Lopes},
      year={2026},
      eprint={2601.21993},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2601.21993}, 
}
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Made with ❤️ by <a href="https://draiven.io">Draiven</a>
</p>
