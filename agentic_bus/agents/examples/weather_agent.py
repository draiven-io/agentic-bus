"""Example: the smallest useful agent — two methods, no endpoint, no schema.

This is the agent shown on slide 13 of the talk deck
(``docs/presentation/project/slides/agente.html``) and started live in the
demo's third moment. The capability strings are kept identical to the slide,
in Portuguese, so what the audience reads is exactly what runs.

Nothing wires it to anything: it registers, and the coordinator discovers it
when an intent asks for a forecast, e.g. *"Qual a previsão do tempo para São
Carlos amanhã?"*.

Run it against a coordinator (``docker compose up`` starts one)::

    python -m agentic_bus.agents.examples.weather_agent

Set ``AGBUS_COORDINATOR_URI`` to reach a coordinator other than
``ws://localhost:8765``.
"""

import asyncio
import os

from agentic_bus import AgentCapability, BaseAgent


class WeatherAgent(BaseAgent):
    def capabilities(self):
        return [AgentCapability(
            capability_id="forecast",
            description="Previsão do tempo por cidade",
        )]

    async def execute_task(self, payload, context):
        return {"forecast": "ensolarado"}


if __name__ == "__main__":
    agent = WeatherAgent(
        agent_id="weather-01",
        coordinator_uri=os.getenv("AGBUS_COORDINATOR_URI", "ws://localhost:8765"),
    )
    asyncio.run(agent.run_forever())
