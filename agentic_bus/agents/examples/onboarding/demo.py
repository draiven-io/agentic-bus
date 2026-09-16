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
    "Preciso da lista de clientes que entraram ontem no CRM, e que seja "
    "enviado o e-mail de boas-vindas para eles."
)


async def main() -> None:
    from agentic_bus import submit_intent

    uri = os.getenv("AGBUS_COORDINATOR_URI", "ws://localhost:8765")

    print()
    print(f"  intent: {INTENT}")
    print()

    result = await submit_intent(
        INTENT,
        requester_id="onboarding-demo",
        # Structured arguments the agents read. Never the intent prose: taking
        # the model out of an agent buys nothing if attacker-influenced text
        # still travels into the tool call.
        context={
            "filtros": {"cadastrado_desde": "ontem"},
            "modelo": {"doc_id": "welcome-pt-br"},
        },
        coordinator_uri=uri,
        timeout=90.0,
    )

    if result.reject:
        print(f"  recusado: {result.reject.reason}")
        print()
        return

    print("  resultado:")
    print(json.dumps(result.result, indent=2, ensure_ascii=False, default=str))
    print()


if __name__ == "__main__":
    asyncio.run(main())
