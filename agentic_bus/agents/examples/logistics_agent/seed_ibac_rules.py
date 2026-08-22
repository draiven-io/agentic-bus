"""Seed the logistics demo with IBAC policies.

The seeded agents show what a bus can *do*. These rules show what it will
*refuse to do*, which is the half that makes it deployable — an agent system
without governance is a demo, not infrastructure.

Each rule below is one a real logistics operator would recognise, and each
lands at a different point in the lifecycle, because that is the argument for
evaluating intent rather than endpoints: the same request is judged five
times, against what is known at each stage.

Usage::

    python -m agentic_bus.agents.examples.logistics_agent.seed_ibac_rules

Pre-requisites:
    - ``agbus db init`` has been run.
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


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

RULES: list[dict] = [
    {
        "rule_id": "deny-destructive-intents",
        "name": "Refuse destructive intents",
        "description": (
            "An intent asking for records to be deleted, purged or wiped is "
            "refused before any agent is asked to bid on it. Nothing "
            "downstream gets the chance to interpret it charitably."
        ),
        "priority": 10,
        "action": "deny",
        "evaluation_points": ["intent_admission"],
        "conditions": {
            "intent_keywords": ["delete", "purge", "wipe", "drop table", "erase"],
        },
    },
    {
        "rule_id": "deny-customer-pii-domain",
        "name": "Keep customer PII out of routing",
        "description": (
            "Route planning needs addresses, not identities. An agent that "
            "offers to work over the customer_pii domain is refused at "
            "offer eligibility, so the data never enters the plan."
        ),
        "priority": 20,
        "action": "deny",
        "evaluation_points": ["offer_eligibility"],
        "conditions": {
            "blocked_domains": ["customer_pii", "payment_card"],
        },
    },
    {
        "rule_id": "deny-payment-scopes",
        "name": "No agent may move money",
        "description": (
            "Negotiating a freight rate is not the same as paying it. Agents "
            "may quote and compare, but any offer requesting a payment write "
            "scope is refused."
        ),
        "priority": 20,
        "action": "deny",
        "evaluation_points": ["offer_eligibility", "execution_authorization"],
        "conditions": {
            "blocked_scopes": ["payments:write", "treasury:transfer"],
        },
    },
    {
        "rule_id": "cap-negotiation-fan-out",
        "name": "Cap agents per interaction",
        "description": (
            "A plan that recruits more than six agents is more likely to be a "
            "decomposition that went wrong than a genuinely complex request. "
            "The cap bounds both cost and blast radius."
        ),
        "priority": 50,
        "action": "deny",
        "evaluation_points": ["negotiation_acceptance"],
        "conditions": {"max_agents": 6},
    },
    {
        "rule_id": "human-approval-for-carrier-commitment",
        "name": "Human approval before committing to a carrier",
        "description": (
            "Booking capacity creates a contractual obligation. The plan may "
            "be built and priced autonomously, but a person authorises it "
            "before it executes."
        ),
        "priority": 30,
        "action": "allow",
        "evaluation_points": ["execution_authorization"],
        "conditions": {
            "require_human_approval": True,
            "intent_keywords": ["book", "commit", "reserve capacity", "confirm booking"],
        },
    },
]


def main() -> None:
    from agentic_bus.core.persistence.database import init_db
    from agentic_bus.core.persistence.ibac_repository import IBACRuleRepository

    init_db()
    repo = IBACRuleRepository()

    created = 0
    skipped = 0
    for rule in RULES:
        try:
            repo.add(
                rule["rule_id"],
                rule["name"],
                description=rule["description"],
                priority=rule["priority"],
                action=rule["action"],
                evaluation_points=rule["evaluation_points"],
                conditions=rule["conditions"],
                created_by="demo-seed",
            )
            created += 1
        except ValueError:
            # Already present: seeding is re-runnable on an existing database.
            skipped += 1

    print()
    print(f"  IBAC policies seeded: {created} created, {skipped} already present")
    print()
    print("  Inspect them in the dashboard under IBAC Rules, or:")
    print()
    print("    curl localhost:8766/api/admin/ibac/rules")
    print()


if __name__ == "__main__":
    main()
