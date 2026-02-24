<p align="center">
  <img src="agentic_bus.png" alt="Agentic Bus" width="600" />
</p>

<h1 align="center">Agentic Bus</h1>

<p align="center">
  <strong>Reference implementation of the Liquid Interfaces Protocol</strong><br>
  A dynamic, negotiation-driven, multi-agent coordination runtime where interfaces are not static contracts — they are ephemeral relational events.
</p>

<p align="center">
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
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT" /></a>
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
| MCP | "What is available?" (local tool exposure) | "What should happen?" (global intent orchestration) — complementary to MCP |

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
├── app/                        # Python backend
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
└── tests/                      # Test suite (18 test files)
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

### Prerequisites

- Python **≥ 3.11**
- Node.js **≥ 18** (for the dashboard UI)
- An LLM provider API key (Azure OpenAI, OpenAI, Anthropic, Google Gemini, or Ollama)

### Installation

```bash
# Clone the repository
git clone https://github.com/draiven-io/agentic-bus.git
cd agentic-bus

# Install the Python backend in editable mode with dev dependencies
pip install -e ".[dev]"

# Interactive setup wizard (creates your .env file)
agbus install

# Install the dashboard UI dependencies
cd ui && npm install && cd ..
```

### Run

```bash
# Start the coordinator (WebSocket :8765 + Admin API :8766)
agbus serve

# In another terminal — start the dashboard UI
cd ui && npm run dev

# In another terminal — run a sample agent
python -m app.agents.examples.logistics_agent.agent
```

The dashboard will be available at **http://localhost:3000** and the Admin REST API at **http://localhost:8766/docs** (Swagger UI).

> **⚠️ Important:** Always run `agbus` commands from the `agentic-bus` directory where your `.env` file is located.

### Configuration

The `agbus install` wizard writes a `.env` file with your LLM provider settings. You can also configure it manually:

```env
# Azure OpenAI
AGBUS_LLM_PROVIDER=azure
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=your-deployment
```

<details>
<summary>Other supported providers</summary>

```env
# OpenAI
AGBUS_LLM_PROVIDER=openai
OPENAI_API_KEY=your-key

# Anthropic
AGBUS_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key

# Google Gemini
AGBUS_LLM_PROVIDER=google
GOOGLE_API_KEY=your-key

# Ollama (local)
AGBUS_LLM_PROVIDER=ollama
```

</details>

Run `agbus config show` to display your current resolved configuration.

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

The coordinator exposes a **FastAPI** admin REST API on port `8766` (configurable via `AGBUS_API_PORT`). Interactive Swagger documentation is available at `/docs`.

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

agbus config show                      # Display resolved configuration
agbus config init                      # Write a starter .env file
```

---

## 🧪 Testing

The project includes a comprehensive test suite with **18 test files** covering all subsystems:

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
