"""Tests for ``agentic_bus.testing`` — the harness agent authors will use.

Written the way an agent author would write them, because that is the point:
if these read badly, the API is wrong.
"""

from __future__ import annotations

import asyncio

import pytest

from agentic_bus import AgentCapability, BaseAgent
from agentic_bus.testing import LocalBus


class WeatherAgent(BaseAgent):
    """The agent from the README."""

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="forecast",
                description="Weather forecast for a city",
                estimated_cost=0.01,
            )
        ]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        return {"forecast": "sunny", "city": payload.get("city", "")}


class SlowAgent(BaseAgent):
    def __init__(self, *args, duration: float = 5.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.duration = duration
        self.started = False
        self.cancelled = False

    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability(capability_id="slow", description="takes a while")]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        self.started = True
        try:
            await asyncio.sleep(self.duration)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {"done": True}


class FailingAgent(BaseAgent):
    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability(capability_id="boom", description="always fails")]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        raise RuntimeError("upstream API is down")


class TestTheReadmeExample:
    """The shape the documentation promises has to actually work."""

    async def test_execute_returns_the_agents_result(self):
        async with LocalBus() as bus:
            agent = await bus.add_agent(WeatherAgent(agent_id="weather-01"))

            result = await bus.execute(agent.agent_id, {"city": "Lisbon"})

            assert result.status == "success"
            assert result.artifacts[0]["forecast"] == "sunny"
            assert result.artifacts[0]["city"] == "Lisbon"

    async def test_no_coordinator_or_llm_is_involved(self):
        """The harness must work on the base install.

        Importing anything from the ``[server]`` extra here would mean an
        agent author cannot test an agent without installing a coordinator,
        which defeats the split between the base package and that extra.
        """
        import subprocess
        import sys

        code = (
            "import sys, json\n"
            "from agentic_bus.testing import LocalBus\n"
            "print(json.dumps(sorted(sys.modules)))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr

        import json

        loaded = set(json.loads(result.stdout))
        server_only = {"sqlalchemy", "fastapi", "uvicorn", "langchain", "langgraph"}
        assert not (server_only & loaded), f"harness pulled in {server_only & loaded}"


class TestRegistration:
    async def test_add_agent_waits_until_it_is_discoverable(self):
        """Returning early would make every test race its own setup."""
        async with LocalBus() as bus:
            agent = await bus.add_agent(WeatherAgent(agent_id="weather-01"))

            assert agent.agent_id == "weather-01"
            assert agent.capability_ids == ["forecast"]
            assert "weather-01" in bus.agents

    async def test_registration_details_are_inspectable(self):
        async with LocalBus() as bus:
            await bus.add_agent(
                WeatherAgent(
                    agent_id="weather-01",
                    semantic_description="European weather",
                )
            )

            registration = bus.registrations[0]
            assert registration.agent_id == "weather-01"
            assert registration.semantic_description == "European weather"

    async def test_refusal_can_be_exercised(self):
        """An agent author should be able to test what their agent does when
        the coordinator turns it away."""
        refusals: list[str] = []

        class WatchfulAgent(WeatherAgent):
            async def on_registration_refused(self, ack):
                refusals.append(ack.reason)

        async with LocalBus(
            accept_registrations=False, refusal_reason="awaiting approval"
        ) as bus:
            agent = WatchfulAgent(agent_id="weather-01")
            agent.coordinator_uri = bus.uri
            task = asyncio.create_task(agent.run_forever())

            for _ in range(100):
                if refusals:
                    break
                await asyncio.sleep(0.02)

            await agent.stop()
            task.cancel()

        assert refusals == ["awaiting approval"]

    async def test_add_agent_times_out_with_a_useful_message(self):
        async with LocalBus(accept_registrations=False) as bus:
            # The agent connects but is never admitted, so it never appears.
            with pytest.raises(TimeoutError, match="did not register"):
                await bus.add_agent(WeatherAgent(agent_id="ghost"), timeout=0.3)


class TestIntents:
    async def test_an_intent_collects_the_agents_offer(self):
        async with LocalBus() as bus:
            await bus.add_agent(WeatherAgent(agent_id="weather-01"))

            offers = await bus.send_intent("what is the weather in Lisbon?")

            assert len(offers) == 1
            assert offers[0].capability_id == "forecast"
            assert offers[0].estimated_cost == 0.01

    async def test_offers_arrive_from_every_registered_agent(self):
        async with LocalBus() as bus:
            await bus.add_agent(WeatherAgent(agent_id="weather-01"))
            await bus.add_agent(WeatherAgent(agent_id="weather-02"))

            offers = await bus.send_intent("weather?", expect_offers=2)

            assert len(offers) == 2

    async def test_missing_offers_are_returned_not_raised(self):
        """Fewer offers than hoped is something to assert on, not an error."""
        async with LocalBus() as bus:
            await bus.add_agent(WeatherAgent(agent_id="weather-01"))

            offers = await bus.send_intent("weather?", expect_offers=5, timeout=0.5)

            assert len(offers) == 1


class TestFailures:
    async def test_a_failing_task_is_reported_not_raised(self):
        """A task that fails is a normal outcome the agent reports."""
        async with LocalBus() as bus:
            agent = await bus.add_agent(FailingAgent(agent_id="boom-01"))

            result = await bus.execute(agent.agent_id)

            assert result.status == "error"
            assert "upstream API is down" in result.artifacts[0]["error"]

    async def test_execute_against_an_unknown_agent_says_who_is_registered(self):
        async with LocalBus() as bus:
            await bus.add_agent(WeatherAgent(agent_id="weather-01"))

            with pytest.raises(KeyError, match="weather-01"):
                await bus.execute("nonexistent")

    async def test_sending_with_no_agents_explains_why(self):
        async with LocalBus() as bus:
            with pytest.raises(RuntimeError, match="add_agent"):
                await bus.send_intent("nobody is listening")


class TestDissolution:
    async def test_dissolve_cancels_the_agents_work(self):
        async with LocalBus() as bus:
            slow = SlowAgent(agent_id="slow-01")
            await bus.add_agent(slow)

            session = "session-doomed"
            asyncio.create_task(
                bus.execute(slow.agent_id, session_id=session, timeout=5.0)
            )
            for _ in range(100):
                if slow.started:
                    break
                await asyncio.sleep(0.02)

            await bus.dissolve(session)

            for _ in range(150):
                if slow.cancelled:
                    break
                await asyncio.sleep(0.02)
            assert slow.cancelled, "dissolve did not reach execute_task"


class TestIntrospection:
    async def test_progress_events_are_available(self):
        async with LocalBus() as bus:
            agent = await bus.add_agent(WeatherAgent(agent_id="weather-01"))
            session = "session-1"

            await bus.execute(agent.agent_id, {"city": "Porto"}, session_id=session)

            events = bus.events(session_id=session)
            assert events, "the agent reported no progress at all"
            assert any("execution" in e.summary or e.category == "agent" for e in events)

    async def test_the_full_transcript_is_available(self):
        from agentic_bus.core.protocol.envelope import MessageType

        async with LocalBus() as bus:
            agent = await bus.add_agent(WeatherAgent(agent_id="weather-01"))
            await bus.execute(agent.agent_id, {"city": "Porto"})

            assert bus.messages_of_type(MessageType.REGISTER)
            assert bus.messages_of_type(MessageType.COMPLETE)
            assert all(
                e.protocol_version for e in bus.messages
            ), "every message should carry a protocol version"


class TestIsolation:
    async def test_two_buses_do_not_collide(self):
        """Port 0 means parallel tests get their own port."""
        async with LocalBus() as first, LocalBus() as second:
            assert first.port != second.port

            a = await first.add_agent(WeatherAgent(agent_id="a"))
            b = await second.add_agent(WeatherAgent(agent_id="b"))

            assert list(first.agents) == [a.agent_id]
            assert list(second.agents) == [b.agent_id]

    async def test_stopping_the_bus_stops_the_agents_it_started(self):
        bus = LocalBus()
        await bus.start()
        agent = WeatherAgent(agent_id="weather-01")
        await bus.add_agent(agent)

        await bus.stop()

        assert not agent.is_running, "the agent was left running"


class TestAuthentication:
    """Agent authors need to test their own ``token_provider``."""

    async def test_the_token_the_agent_sent_is_visible(self):
        async with LocalBus() as bus:
            await bus.add_agent(
                WeatherAgent(agent_id="weather-01", token_provider=lambda: "my-token")
            )

            assert bus.auth_headers == ["Bearer my-token"]

    async def test_an_async_token_provider_works(self):
        async def fetch() -> str:
            await asyncio.sleep(0)
            return "async-token"

        async with LocalBus() as bus:
            await bus.add_agent(WeatherAgent(agent_id="weather-01", token_provider=fetch))

            assert bus.auth_headers == ["Bearer async-token"]


class TestOlderCoordinators:
    async def test_an_agent_still_serves_without_an_acknowledgement(self):
        """A coordinator older than LIP 0.2.0 never sends ``registered``.

        The agent should warn and carry on, not refuse to run — which is what
        ``answer_registrations=False`` lets an author verify.
        """
        async with LocalBus(answer_registrations=False) as bus:
            # The bus still admits the agent — it just never says so. So the
            # ordinary add_agent() flow works, which is the point: an author
            # tests this the same way they test everything else.
            agent = await bus.add_agent(
                WeatherAgent(agent_id="weather-01", registration_timeout=0.2)
            )

            result = await bus.execute(agent.agent_id, {"city": "Faro"})
            assert result.status == "success"
