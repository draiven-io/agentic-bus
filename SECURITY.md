# Security Policy

## Reporting a vulnerability

Report vulnerabilities privately to **dhiogo.correa@draiven.io**, or through
[GitHub's private advisory form](https://github.com/draiven-io/agentic-bus/security/advisories/new).
Please do not open a public issue.

Include a description of the issue, the affected component, reproduction
steps, and the impact you believe it has. Expect an acknowledgement within
five working days.

## Supported versions

Agentic Bus is pre-1.0. Fixes land on `main` and in the next release; there
is no backport branch yet.

## Known limitations

These are properties of the current design rather than bugs. They are listed
here so that nobody deploys the runtime believing it offers a guarantee it
does not.

### IBAC combines a probabilistic layer with a deterministic one

`agentic_bus/core/ibac/engine.py` evaluates every intention against two
layers, and takes the stricter outcome:

- The **grounded layer** evaluates rules deterministically in code.
- The **semantic layer** asks the configured model whether an intention
  violates a policy expressed in natural language — which is what lets a rule
  like *"do not disclose confidential information to competitors"* be
  enforced without enumerating every competitor.

The layers are ANDed, never short-circuited: a grounded rule can still deny
something the model approved. That is the property the grounded layer exists
to provide, and it only holds because a semantic ALLOW does not end the
evaluation.

**Evaluation fails closed.** No model configured, an unreachable provider, a
call that raises, a malformed or unparseable answer, an unreadable rule
store — every one of these denies. An evaluation that did not happen is not
permission. (An empty rule set is different: that is a completed evaluation
that found nothing prohibiting the intention, and it allows.)

What is still true, and worth stating plainly:

- **The semantic layer is exposed to prompt injection.** Intent text,
  capability descriptions and upstream agent output all reach its prompt.
  The prompt tells the model to treat that text as data and to deny when it
  contains instructions, but no prompt makes a model injection-proof.
  Consequently: **a policy you cannot afford to have bypassed must be
  expressed as a grounded rule**, not left to the semantic layer alone. The
  test suite asserts that a grounded denial survives an injected semantic
  approval.
- **Semantic decisions are not reproducible.** The same intention may not
  produce the same semantic outcome twice, so a semantic ALLOW is not
  evidence that the same request would be allowed again.
- **Decisions are not signed.** A recorded decision cannot yet be
  independently verified after the fact.
- **Approved constraints are not yet enforced at execution.** IBAC records
  the scope it authorised, but the execution path does not yet check it, so
  IBAC currently gates whether an intention starts rather than bounding what
  it may touch. Until that lands, treat an ALLOW as admission, not as a
  capability.

**Grounded rules are a boundary. Semantic rules are defence in depth.** Keep
enforcing hard limits — credentials, network egress, spend, data residency —
in the infrastructure the agents run on.

### Agent-supplied content is trusted input to coordination

Capability descriptions, offers and execution results are written by
registered agents and feed directly into semantic discovery, negotiation and
result synthesis. An approved-but-hostile agent can attempt to influence
routing by how it describes itself. Approve enrolments deliberately;
`AGBUS_AGENT_AUTO_APPROVE=true` is a development convenience and is not
appropriate for a shared deployment.

### Transport and authentication

- Run the coordinator behind TLS. The WebSocket server does not terminate TLS
  itself.
- The default `DevVerifier` accepts any token. Configure OIDC
  (`AGBUS_OIDC_ISSUER`, `AGBUS_OIDC_AUDIENCE`) for anything beyond local
  development.
- Admin REST endpoints are authorised from OIDC claims; `AGBUS_ADMIN_SUBJECTS`
  and `AGBUS_ADMIN_ROLE` govern who is an administrator.

### Credentials

LLM provider credentials are stored in the database, not in `.env`. They are
stored so the coordinator can use them at runtime — protect the database
accordingly, and prefer a managed secret store in production deployments.
