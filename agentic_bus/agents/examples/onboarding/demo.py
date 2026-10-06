"""Submit the onboarding intent and print what the lifecycle did with it.

Usage::

    python -m agentic_bus.agents.examples.onboarding.demo

Requires ``agbus serve`` and ``run_agents`` to be up, and ``seed`` to have run
once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "WARNING"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

INTENT = (
    "I need the list of customers who signed up in the CRM yesterday, and "
    "the welcome email sent to them."
)


async def main() -> None:
    from agentic_bus import submit_intent

    uri = os.getenv("AGBUS_COORDINATOR_URI", "ws://localhost:8765")

    print()
    print(f"  intent: {INTENT}")
    print()

    # No context. The requester states what it wants and nothing about how
    # any step is parameterised — it does not know that step two will be a
    # document agent, nor what that agent calls its fields.
    #
    # Each capability publishes an `input_schema`; the coordinator composes
    # the parameters for every step from the intent and validates them against
    # that schema before dispatching. Passing a context here still works and
    # still reaches the agents, but needing to is the contract coming back.
    result = await submit_intent(
        INTENT,
        requester_id="onboarding-demo",
        coordinator_uri=uri,
        timeout=90.0,
    )

    if result.reject:
        print(f"  rejected: {result.reject.reason}")
        print()
        return

    print("  result:")
    print(json.dumps(result.result, indent=2, ensure_ascii=False, default=str))
    print()


if __name__ == "__main__":
    asyncio.run(main())
