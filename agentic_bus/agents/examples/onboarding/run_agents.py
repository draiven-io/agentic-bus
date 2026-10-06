"""Start the three onboarding agents against a running coordinator.

Usage::

    agbus serve                                                    # terminal 1
    python -m agentic_bus.agents.examples.onboarding.seed          # once
    python -m agentic_bus.agents.examples.onboarding.run_agents    # terminal 2
    python -m agentic_bus.agents.examples.onboarding.demo          # terminal 3

All three run in one process here because the example is about the protocol,
not about deployment. Nothing changes if they are three processes on three
machines: each connects on its own, authenticates on its own, and holds its
own credential.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    from agentic_bus.agents.examples.onboarding.agents import (
        CRMAgent,
        EmailAgent,
        SharePointAgent,
    )

    uri = os.getenv("AGBUS_COORDINATOR_URI", "ws://localhost:8765")
    agents = [CRMAgent(uri), SharePointAgent(uri), EmailAgent(uri)]

    for agent in agents:
        await agent.start()
        logger.info("started %s", agent.agent_id)

    print()
    print("  three agents up, one credential each:")
    for agent in agents:
        print(f"    {agent.agent_id:<20} {agent.capabilities()[0].required_scopes}")
    print()
    print("  Ctrl+C to stop.")
    print()

    try:
        await asyncio.Event().wait()
    finally:
        for agent in agents:
            await agent.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
