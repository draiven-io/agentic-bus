"""Staging an execution's writes to the session's shared memory.

The coordinator has read ``memory_writes`` off a ``complete`` for as long as
session memory has existed, applying each through the agent's write policy and
counting what it refused. Nothing on the agent side ever put anything there,
and ``CompletePayload`` never declared the field — so an implementer reading
the schema could not have known to send it.

These tests carry the half that was missing. The ones that matter are the
staging surviving into the envelope, the batch being per-task so concurrent
executions cannot bleed into each other, and the drain happening on the
failure and refusal paths too — an execution that staged before it stopped
still said what it meant to write, and only the coordinator decides whether
any of it lands.
"""

from __future__ import annotations

import asyncio

import pytest

from agentic_bus.agents.memory import (
    open_staging,
    remember,
    reset_staging,
    staged_writes,
)
from agentic_bus.core.protocol.envelope import CompletePayload


class TestStaging:
    def test_a_staged_write_is_readable(self):
        token = open_staging()
        try:
            remember("shared.clientes", {"rows": 42})
            assert staged_writes() == {"shared.clientes": {"rows": 42}}
        finally:
            reset_staging(token)

    def test_outside_an_execution_nothing_is_staged(self):
        """Matching require_scope: a caller with no session is not one an
        attacker reached through the bus."""
        remember("shared.orphan", 1)

        assert staged_writes() == {}

    def test_the_last_value_for_a_key_wins(self):
        """The batch is what the execution ended up meaning to write, not a
        log of how it got there."""
        token = open_staging()
        try:
            remember("shared.count", 1)
            remember("shared.count", 2)
            assert staged_writes() == {"shared.count": 2}
        finally:
            reset_staging(token)

    def test_the_batch_cannot_be_edited_through_the_reader(self):
        token = open_staging()
        try:
            remember("shared.a", 1)
            staged_writes()["shared.b"] = 2
            assert "shared.b" not in staged_writes()
        finally:
            reset_staging(token)

    def test_closing_the_batch_ends_it(self):
        token = open_staging()
        remember("shared.a", 1)
        reset_staging(token)

        assert staged_writes() == {}

    async def test_concurrent_executions_do_not_share_a_batch(self):
        """The reason this is a context variable and not an attribute.

        Two tasks running in one agent must not write into each other's
        batch — the coordinator applies each against the policy of the agent
        that sent it, and a mixed batch would attribute a write to the wrong
        execution.
        """
        seen: dict[str, dict] = {}

        async def execution(name: str) -> None:
            token = open_staging()
            try:
                remember(f"shared.{name}", name)
                await asyncio.sleep(0)  # let the other task run
                seen[name] = staged_writes()
            finally:
                reset_staging(token)

        await asyncio.gather(execution("a"), execution("b"))

        assert seen["a"] == {"shared.a": "a"}
        assert seen["b"] == {"shared.b": "b"}


class TestThePayload:
    def test_complete_declares_the_field_the_coordinator_reads(self):
        """It did not, which is why nothing could legitimately send it."""
        assert "memory_writes" in CompletePayload.model_fields

    def test_it_defaults_to_nothing(self):
        assert CompletePayload().memory_writes == {}

    def test_it_survives_a_round_trip(self):
        payload = CompletePayload(memory_writes={"shared.k": [1, 2]})

        assert CompletePayload(**payload.model_dump()).memory_writes == {
            "shared.k": [1, 2]
        }


class TestTheAgentSendsThem:
    """End to end through BaseAgent's execute handler."""

    def _agent(self, work):
        from agentic_bus.agents.base.agent import BaseAgent

        class Agent(BaseAgent):
            def capabilities(self):
                return []

            async def execute_task(self, payload, context):
                return await work()

        return Agent(agent_id="writer")

    async def _complete_for(self, agent) -> CompletePayload:
        from agentic_bus.core.protocol.envelope import (
            MessageType,
            SenderInfo,
            SenderKind,
            build_envelope,
        )

        sent: list = []

        class Peer:
            peer_id = "p1"

            async def send_envelope(self, env):
                sent.append(env)

        agent._peer = Peer()

        envelope = build_envelope(
            MessageType.EXECUTE,
            SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            "session-1",
            {"execution_plan": {"context": {}}, "authorized_scopes": ["x:y"]},
        )
        await agent._handle_execute(envelope)

        completes = [e for e in sent if e.message_type == MessageType.COMPLETE]
        assert completes, "no complete was sent"
        return CompletePayload(**completes[-1].payload)

    async def test_a_staged_write_reaches_the_complete(self):
        async def work():
            remember("shared.result", {"rows": 3})
            return {"ok": True}

        payload = await self._complete_for(self._agent(work))

        assert payload.status == "success"
        assert payload.memory_writes == {"shared.result": {"rows": 3}}

    async def test_an_execution_that_staged_nothing_sends_nothing(self):
        async def work():
            return {"ok": True}

        payload = await self._complete_for(self._agent(work))

        assert payload.memory_writes == {}

    async def test_writes_staged_before_a_failure_still_travel(self):
        """The coordinator's policy decides what lands — not the agent, and
        not whether the agent happened to finish."""

        async def work():
            remember("shared.partial", 1)
            raise RuntimeError("broke halfway")

        payload = await self._complete_for(self._agent(work))

        assert payload.status == "error"
        assert payload.memory_writes == {"shared.partial": 1}

    async def test_writes_staged_before_a_refusal_still_travel(self):
        from agentic_bus.agents.scope_guard import require_scope

        async def work():
            remember("shared.before_refusal", 1)
            require_scope("not:granted")
            return {"unreachable": True}

        payload = await self._complete_for(self._agent(work))

        assert payload.status == "denied"
        assert payload.memory_writes == {"shared.before_refusal": 1}

    async def test_one_execution_does_not_leak_into_the_next(self):
        calls = {"n": 0}

        async def work():
            calls["n"] += 1
            if calls["n"] == 1:
                remember("shared.first", 1)
            return {"ok": True}

        agent = self._agent(work)
        first = await self._complete_for(agent)
        second = await self._complete_for(agent)

        assert first.memory_writes == {"shared.first": 1}
        assert second.memory_writes == {}
