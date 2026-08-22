# AGENTS.md — implementation guide

> **This is not the protocol specification.** The protocol lives in
> [draiven-io/liquid-interfaces](https://github.com/draiven-io/liquid-interfaces),
> and the JSON Schemas in [`schemas/`](schemas/) are authoritative for the
> wire format. This document records how *this implementation* is built: the
> constraints it holds itself to, and the shape its modules take.
>
> It is referenced by section number from docstrings throughout the codebase,
> so section numbering is stable — add sections, don't renumber them.

## Reference implementation – Liquid Interfaces Protocol (LIP)

This repository implements a **dynamic, negotiation-driven, multi-agent coordination runtime** for the Liquid Interfaces Protocol.

The system must support:

- intent → discovery → offering → negotiation → accept / reject / renegotiation
- execution under governance
- mandatory dissolution of the interaction context

This is **not** a workflow engine.
This is a runtime that builds coordination structures dynamically for each intent.

The paper is [`lip.md`](lip.md); the normative wire format is the
[LIP specification](https://github.com/draiven-io/liquid-interfaces/blob/main/spec/lip/README.md).

---

## 1. Non-negotiable technical constraints

- Transport: **WebSocket** (bidirectional, real-time)
- LLM framework: **LangChain** (`langchain>=1.0,<2.0`)
- Graph orchestration: **LangGraph**
- Observability: **OpenTelemetry**
- Authentication: **OIDC**
- Governance: **IBAC – Intention-Based Access Control**
- No static orchestration
- No hard-coded agent pipelines
- No pre-defined workflows
- All orchestration must be synthesized at runtime

---

## 2. Runtime roles

### Coordinator (mandatory)

The coordinator is the authoritative runtime component responsible for:

- session lifecycle
- intent routing
- agent discovery
- negotiation orchestration
- IBAC enforcement
- LangGraph synthesis
- execution supervision
- dissolution

### Provider Agents

Agents expose capabilities and:

- receive intents
- generate offers
- participate in negotiation
- execute tasks when authorized

### Requester

The requester submits an intent and receives:

- negotiation updates
- execution results
- final artifacts

---

## 3. Transport layer

All communication MUST use WebSockets.

The coordinator acts as the session hub.

Each connected peer must authenticate using OIDC before joining any session.

---

## 4. Authentication and identity

OIDC must be used for:

- user identity
- agent identity
- service identity

The system must extract and propagate:

- subject
- issuer
- audience
- scopes
- custom claims

OIDC claims MUST be attached to the session context and evaluated by IBAC.

---

## 5. OpenTelemetry

OpenTelemetry MUST be implemented across:

- WebSocket message handling
- intent lifecycle
- negotiation
- graph execution
- agent calls

Each message must propagate:

- trace_id
- span_id

Coordinator spans MUST form the root of each intent execution trace.

---

## 6. IBAC – Intention-Based Access Control

IBAC is mandatory and must be implemented as a first-class subsystem.

### IBAC evaluation points

IBAC MUST be evaluated at:

1. intent admission
2. offer eligibility
3. negotiation acceptance
4. execution authorization
5. artifact emission

### IBAC decision input

IBAC policies MUST receive:

- requester identity
- agent identity
- intent text
- structured intent context
- requested scopes
- proposed capabilities
- negotiated constraints
- data domains involved

### IBAC decision output

The IBAC engine must return:

- allow / deny
- optional constraints
- optional redactions
- optional negotiation requirements

IBAC decisions MUST be auditable and traced.

---

## 7. Dynamic capability registry

Agents MUST register themselves dynamically with:

- agent_id
- version
- capability descriptors
- semantic description
- required scopes
- supported data domains
- operational constraints

The registry MUST be in-memory and hot-reloadable.

No static capability lists.

---

## 8. LIP message model

All messages are JSON with a common envelope. The schemas under
[`schemas/`](schemas/) are generated from the Pydantic models and are
authoritative; this section is orientation, not the contract.

Agents join by sending `register` and waiting for `registered` — see
[RFC 0001](https://github.com/draiven-io/liquid-interfaces/blob/main/rfcs/0001-register-performative.md).
An envelope arriving without `protocol_version` is read as `0.1.0`.

```json
{
  "protocol_version": "0.2.0",
  "message_id": "uuid",
  "session_id": "uuid",
  "message_type": "register|registered|intent|offer|accept|reject|execute|complete|dissolve|event",
  "timestamp": "ISO-8601",
  "sender": {
    "kind": "requester|coordinator|agent",
    "id": "string",
    "oidc_subject": "string"
  },
  "trace": {
    "trace_id": "string",
    "span_id": "string"
  },
  "payload": {}
}
```

---

## 9. Intent message

```json
{
  "intent_text": "natural language objective",
  "context": {
    "constraints": {},
    "regulatory": {},
    "time": {},
    "budget": {}
  },
  "requested_outputs": [],
  "ibac_claims_requested": []
}
```

---

## 10. Offer message

```json
{
  "capability_id": "string",
  "capability_description": "natural language description",
  "constraints": {},
  "expected_artifacts": [],
  "estimated_cost": null,
  "estimated_latency": null,
  "required_scopes": []
}
```

---

## 11. Negotiation semantics

The coordinator MUST support:

- multiple parallel offers
- partial composition of offers
- renegotiation loops
- rejection with reasons
- renegotiation proposals

Negotiation continues until:

- a valid composition exists
- or negotiation is terminated

---

## 12. Coordinator orchestration using LangGraph

The coordinator MUST dynamically synthesize a LangGraph graph.

The graph MUST be built only after:

- IBAC validation
- negotiation convergence

### Graph construction rules

- each selected agent becomes one or more nodes
- negotiation output determines the topology
- dependencies are derived from the intent decomposition
- the coordinator MUST be able to rebuild the graph if renegotiation occurs

No static graphs.

No pre-declared DAGs.

---

## 13. LangChain usage

All LLM usage MUST go through LangChain (`langchain>=1.0,<2.0`), resolved
via `agentic_bus.core.llm.get_llm()` so the provider stays configurable at
runtime rather than pinned in code.

Agents may use:

- tools
- retrievers
- vector stores
- structured output parsers

The coordinator MUST NOT embed business logic inside prompts.
Orchestration is performed by LangGraph, not by prompting.

---

## 14. Execution phase

Only after:

- negotiation is finalized
- IBAC authorizes execution
- the graph is built

the coordinator may emit:

```
message_type = "execute"
```

Execution must be supervised.

Each node execution must be traced.

Failures must be propagated as structured negotiation failures, not as exceptions.

---

## 15. Completion phase

Agents must emit:

```
message_type = "complete"
```

Payload must include:

- status
- produced artifacts
- metadata

---

## 16. Mandatory dissolution

After completion (success or failure) the coordinator MUST:

- emit a `dissolve` message
- destroy all ephemeral graph state
- destroy negotiated schemas
- invalidate session artifacts

No negotiated structures may persist across sessions.

---

## 17. Everything must be dynamic

The following are forbidden:

- static pipelines
- fixed agent routing
- static prompt chains
- hard-coded dependency graphs
- pre-built orchestration templates

Everything must be discovered, negotiated and synthesized at runtime.

---

## 18. Minimal module structure

```
agentic_bus/
  __init__.py        public API for agent authors
  testing.py         LocalBus – stand-in coordinator for tests
  core/
    transport/  protocol/  session/  registry/
    ibac/  telemetry/  auth/  llm/  persistence/
  coordinator/
    graph/  negotiation/  intent/  execution/  validation/  admin/
  agents/
    base/  examples/
```

The package installs as `agentic_bus`. Only what `agentic_bus/__init__.py`
re-exports is public API; everything else may change without notice.

---

## 19. Coordinator responsibilities (summary)

The coordinator MUST:

- accept and authenticate WebSocket connections
- validate identity with OIDC
- open intent sessions
- discover eligible agents
- request offers
- run IBAC on offers
- negotiate and compose offers
- build LangGraph dynamically
- supervise execution
- enforce governance
- dissolve sessions

---

## 20. Agent responsibilities

Each agent MUST:

- authenticate using OIDC
- register capabilities dynamically
- receive intent and offer requests
- produce offers
- execute tasks only after explicit execute message
- emit completion messages
- support cancellation

---

## 21. Design objective

The system must behave as a:

**semantic coordination fabric** rather than a workflow engine.

The primary invariant is:

> Coordination is established through negotiation and governance, not through predefined integration contracts.