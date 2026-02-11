# AGENTS.md

## Reference implementation – Agentic Bus Protocol

This repository implements a **dynamic, negotiation-driven, multi-agent coordination runtime** inspired by the Agentic Bus Protocol.

The system must support:

- intent → discovery → offering → negotiation → accept / reject / renegotiation
- execution under governance
- mandatory dissolution of the interaction context

This is **not** a workflow engine.
This is a runtime that builds coordination structures dynamically for each intent.

As reference, you can always check the `agbus.md` paper that contains details about the protocol.

---

## 1. Non-negotiable technical constraints

- Transport: **WebSocket** (bidirectional, real-time)
- LLM framework: **langchain==1.2.9**
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

## 8. Agentic Bus message model

All messages are JSON with a common envelope.

```json
{
  "message_id": "uuid",
  "session_id": "uuid",
  "message_type": "intent|offer|accept|reject|execute|complete|dissolve",
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

All LLM usage MUST be implemented using:

```
langchain==1.2.9
```

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
/core
  /transport
  /protocol
  /session
  /registry
  /ibac
  /telemetry
  /auth

/coordinator
  /graph
  /negotiation
  /intent
  /execution

/agents
  /base
  /examples
```

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