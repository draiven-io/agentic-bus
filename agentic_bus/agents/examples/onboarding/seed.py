"""Seed the vocabulary, the bindings and the policies for the example.

Three things, and keeping them apart is the point:

**Catalogue** — the names this coordinator recognises. A property of the
deployment, not of any agent. An agent that declares a name outside it is not
refused; the name is recorded as a request for an operator to look at, and the
refusal carries the catalogue back so the implementer learns the right one.

**Bindings** — which of those names a capability actually holds. *This* is the
authority: an agent's declaration never is. A capability with no binding
declares whatever it likes and holds nothing.

**IBAC rules** — what is forbidden, named as combinations rather than
enumerated as a matrix. Two rules cover six cells here.

Usage::

    python -m agentic_bus.agents.examples.onboarding.seed
"""

from __future__ import annotations

import logging
import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


SCOPES: list[tuple[str, str]] = [
    ("crm:read", "Read the CRM customer base"),
    ("doc:read", "Read documents and templates in the repository"),
    ("email:send", "Send email on behalf of the organisation"),
]

#: capability -> scopes. The binding is the authority.
BINDINGS: list[tuple[str, str, list[str]]] = [
    ("crm-reader", "crm.find_customers", ["crm:read"]),
    ("sharepoint-reader", "doc.find_template", ["doc:read"]),
    ("email-sender", "email.send_template", ["email:send"]),
]


RULES: list[dict] = [
    {
        "rule_id": "onboarding-deny-destructive",
        "name": "Refuse destructive intents",
        "description": (
            "An intent that asks to delete, purge or wipe records is refused "
            "before any agent is consulted. Nothing downstream gets the chance "
            "to read it charitably."
        ),
        "priority": 10,
        "action": "deny",
        "evaluation_points": ["intent_admission"],
        "conditions": {
            "intent_keywords": ["delete", "purge", "wipe", "drop table", "truncate"],
        },
    },
    {
        "rule_id": "onboarding-bulk-export-needs-a-person",
        "name": "Bulk export requires human confirmation",
        "description": (
            "Extracting the customer base out of the workflow — CSV, "
            "spreadsheet, dump — requires a person to confirm. Sending "
            "communication to those customers is not an export: the recipient "
            "is the subject of the data, and treating the two cases as one "
            "would block the legitimate work along with the risk."
        ),
        "priority": 20,
        "action": "deny",
        "evaluation_points": ["intent_admission"],
        "conditions": {
            "intent_patterns": [r"(?i)\b(export\w*|csv|spreadsheet|dump)\b"],
            "require_human_approval": True,
        },
    },
    {
        "rule_id": "onboarding-cap-the-composition",
        "name": "Cap the size of the composition",
        "description": (
            "An onboarding plan means reading customers, finding a template "
            "and sending. Needing much more than that means the intent was "
            "understood some other way — and the time to notice is before "
            "executing, not after."
        ),
        "priority": 30,
        "action": "deny",
        "evaluation_points": ["negotiation_acceptance"],
        "conditions": {"max_agents": 4},
    },
]


def main() -> None:
    from agentic_bus.core.persistence.database import init_db
    from agentic_bus.core.persistence.ibac_repository import IBACRuleRepository
    from agentic_bus.core.persistence.scope_repository import ScopeRepository

    init_db()

    scopes = ScopeRepository()
    # add_scope returns False when the name is already catalogued, so seeding
    # is re-runnable and the count stays honest on the second pass.
    added = sum(
        scopes.add_scope(name, description=description, created_by="onboarding-seed")
        for name, description in SCOPES
    )

    bound = 0
    for agent_id, capability, names in BINDINGS:
        bound += len(scopes.bind(agent_id, capability, names, bound_by="onboarding-seed"))

    rules = IBACRuleRepository()
    created = skipped = 0
    for rule in RULES:
        try:
            rules.add(
                rule["rule_id"],
                rule["name"],
                description=rule["description"],
                priority=rule["priority"],
                action=rule["action"],
                evaluation_points=rule["evaluation_points"],
                conditions=rule["conditions"],
                created_by="onboarding-seed",
            )
            created += 1
        except ValueError:
            skipped += 1

    print()
    print(f"  catalogue: {added} scope(s) added, {len(SCOPES) - added} already present")
    print(f"  bindings : {bound} new grant(s)")
    print(f"  policies : {created} created, {skipped} already present")
    print()
    print("  Check with:  agbus scope granted crm-reader")
    print()


if __name__ == "__main__":
    main()
