# Agentic Bus – Agentic Bus Protocol Reference Implementation

A **dynamic, negotiation-driven, multi-agent coordination runtime** that implements the
Agentic Bus Protocol as described in the Agentic Bus paper.

## Key Principles

- **Intent-first**: Coordination starts from a natural-language objective, not from an endpoint.
- **Negotiated**: Interfaces emerge through semantic negotiation at runtime.
- **Ephemeral**: All coordination artifacts are dissolved after task completion — zero technical debt.
- **Governed**: IBAC (Intention-Based Access Control) is enforced at every phase.

## Architecture

```
Requester ──WebSocket──► Coordinator ──WebSocket──► Provider Agents
                              │
                         ┌────┴────┐
                         │ LangGraph│  (dynamically synthesised)
                         └────┬────┘
                              │
                    IBAC ◄────┤────► Registry
                              │
                         Telemetry (OTel)
```

## Module Layout

```
core/           – Shared infrastructure
  protocol/     – Agentic Bus message model & envelope
  transport/    – WebSocket server / client
  session/      – Session lifecycle management
  registry/     – Dynamic capability registry
  ibac/         – Intention-Based Access Control
  telemetry/    – OpenTelemetry instrumentation
  auth/         – OIDC authentication

coordinator/    – Coordination runtime
  intent/       – Intent admission & decomposition
  negotiation/  – Offer collection, scoring, composition
  graph/        – Dynamic LangGraph synthesis
  execution/    – Supervised execution & failure handling

agents/         – Agent SDK and examples
  base/         – Base agent framework
  examples/     – Sample provider agents
```

## Quick Start

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Interactive setup (creates .env file)
agbus install

# 3. Navigate to the project directory (IMPORTANT!)
cd /path/to/agentic-bus

# 4. Run the coordinator
agbus serve

# In another terminal (from the same directory):
# 5. Run an example agent
python -m app.agents.examples.logistics_agent.agent
```

**⚠️ Important:** Always run `agbus` commands from the `agentic-bus` directory where your `.env` file is located. See [RUNNING.md](RUNNING.md) for details.

### Configuration

The `agbus install` command creates a `.env` file with your LLM provider settings. For Azure OpenAI:

```env
AGBUS_LLM_PROVIDER=azure
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=your-deployment
```

For more configuration options, see `.env.example` or run `agbus config show`.
