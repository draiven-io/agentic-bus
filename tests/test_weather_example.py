"""The weather example from the talk deck, run through ``LocalBus``.

The demo starts this agent live in front of an audience, so the test checks
the two things the demo relies on: it registers with the capability the slide
shows, and executing it returns the slide's answer.
"""

from __future__ import annotations

from agentic_bus.agents.examples.weather_agent import WeatherAgent
from agentic_bus.testing import LocalBus


async def test_weather_agent_answers_through_the_bus():
    async with LocalBus() as bus:
        agent = await bus.add_agent(WeatherAgent(agent_id="weather-01"))

        assert agent.capability_ids == ["forecast"]

        result = await bus.execute(agent.agent_id, {"city": "São Carlos"})

        assert result.status == "success"
        assert result.artifacts[0]["forecast"] == "ensolarado"
