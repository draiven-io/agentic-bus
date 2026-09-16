# Onboarding: read the CRM, fetch a template, send the welcome mail

One intent, three agents, one credential each, none of them holding a model.

```
"Preciso da lista de clientes que entraram ontem no CRM, e que seja
 enviado o e-mail de boas-vindas para eles."
```

## Why three agents and not two

The obvious shape is two: one that reads the CRM, one that fetches the
template and sends the mail. Don't build that one.

An agent holding `doc:read` **and** `email:send` is the composition this
protocol exists to govern — read something, send it outside — rebuilt inside a
single process where no coordinator can see it. Split them and the combination
stays in the plan, which is where `negotiation_acceptance` can judge it.

**If an agent needs two scopes from two systems, it is usually two agents.**
One scope per agent is not purity; it is what keeps the composition in the
coordinator's field of view.

## What each one is

| Agent | Scope | Holds | Model |
|---|---|---|---|
| `crm-reader` | `crm:read` | the CRM credential | none |
| `sharepoint-reader` | `doc:read` | the document credential | none |
| `email-sender` | `email:send` | the mail credential — the egress point | none |

The agent that thinks is the requester's side. The agents that hold
credentials do not reason about text: `_pick_tool`-style dispatch, structured
arguments, no prompt to inject. Nothing in LIP enforces that — it is a
deployment discipline, and it is the one that matters most.

## Running it

```bash
agbus serve
```

```bash
python -m agentic_bus.agents.examples.onboarding.seed
```

```bash
python -m agentic_bus.agents.examples.onboarding.run_agents
```

```bash
python -m agentic_bus.agents.examples.onboarding.demo
```

`seed` runs once and is re-runnable. It writes three separate things:

- **the catalogue** — the names this coordinator recognises, a property of the
  deployment. An agent naming something outside it is not refused; the name is
  recorded as a request, and the refusal carries the catalogue back so the
  implementer learns the right one by being corrected.
- **the bindings** — which names a capability actually holds. *This* is the
  authority; an agent's declaration never is. Check it with
  `agbus scope granted crm-reader`, and note that
  `scopes.granted("email-sender", "crm.buscar_clientes")` returns nothing.
- **the policies** — what is forbidden, named as combinations rather than
  enumerated as a matrix.

## What to watch

**The scope is bound to the credential, not to a remembered call.** Each agent
holds its client as a `ScopedResource`, so there is no path to it that skips
the check, and the factory does not run until the check passes — a scope never
granted is a connection never opened.

**Working data travels through session memory; the artifact reports.** The CRM
agent stages the rows with `remember()` and returns a summary. The summary is
what gets validated against the `output_schema` its offer promised; the rows
are what the next step consumes.

**The template is classified `Publico`.** Sensitivity, not destination. The
recipients *are* external — they are customers — so an invariant reading only
"is the destination outside the tenant" would refuse the entire legitimate use
case. It does not fire here because the classification is not restricted, and
that is the interesting half: the mechanism letting something through for the
right reason is harder to build than the mechanism refusing it.

## What this example does not show

**Fact resolution.** `execution_authorization` is where the coordinator would
resolve `documento.classificacao` and whether a recipient is external, and
judge the two together. The invariant that reads those fields exists in the
engine, but nothing in the runtime populates them, so it never fires. There is
no fact-resolver agent yet.

**Per-recipient partitioning.** The send is one step for every recipient, so
the decision is all-or-nothing. Holding four addresses back while ninety-six
go out needs evaluation *inside* a step, which the coordinator has no notion
of.

**Reading session memory.** The coordinator builds a per-agent
`memory_snapshot` and puts it on the `execute`, but `_handle_execute` hands
only `execution_plan` and `context` to `execute_task`, so it does not arrive.
The sender reads `prior_results` instead.
