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

### IBAC decisions are made by a language model

The primary evaluation path in `app/core/ibac/engine.py` presents the active
rules and the request context to the configured LLM and asks it to decide.
That is what allows a natural-language rule such as *"prevent agents from
accessing internet websites"* to be enforced without a regex — and it is also
the exposure:

- **Prompt injection.** Intent text, capability descriptions and upstream
  agent outputs all reach the policy prompt. Content crafted to read as
  instruction can influence a decision.
- **Non-determinism.** The same request may not produce the same decision
  twice. Policy decisions are not reproducible from the record alone.
- **No cryptographic binding.** A decision is not signed, so it cannot be
  independently verified after the fact.

A deterministic path (`IBACEngine.evaluate`) exists for fast programmatic
checks and as a fallback when no LLM is configured.

**Treat IBAC as defence in depth, not as a security boundary.** Enforce hard
limits — credentials, network egress, spend, data residency — in the
infrastructure the agents run on. Do not rely on IBAC alone to keep an agent
away from something it must never reach.

A hybrid policy decision point — deterministic constraints as a hard gate,
LLM classification only within those bounds, plus signed and replayable
decision records — is the planned direction.

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
