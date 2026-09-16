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
    recall,
    recalled,
    remember,
    reset_snapshot,
    reset_staging,
    set_snapshot,
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


class TestReading:
    """The counterpart. The coordinator built a per-agent snapshot and put it
    on the `execute` since session memory existed; nothing received it, so a
    step could write to the shared store and no step could read it."""

    def test_a_key_in_the_snapshot_comes_back(self):
        token = set_snapshot({"crm.clientes": [{"id": 1}]})
        try:
            assert recall("crm.clientes") == [{"id": 1}]
        finally:
            reset_snapshot(token)

    def test_a_key_outside_it_is_a_miss_not_a_refusal(self):
        """The snapshot is already filtered to what the plan granted, so a key
        that was never delivered is simply absent."""
        token = set_snapshot({"crm.clientes": []})
        try:
            assert recall("rh.salarios", default="nada") == "nada"
        finally:
            reset_snapshot(token)

    def test_outside_an_execution_the_default_comes_back(self):
        assert recall("anything", default=42) == 42

    def test_recalled_hands_back_a_copy(self):
        token = set_snapshot({"a": 1})
        try:
            recalled()["b"] = 2
            assert "b" not in recalled()
        finally:
            reset_snapshot(token)

    def test_what_this_execution_staged_is_not_readable_back(self):
        """Staging is not storing.

        The coordinator applies staged writes through the agent's write policy
        after the execution, and a key the policy refuses never reaches anyone's
        snapshot. Reading one back here would report as stored something that
        may be about to be denied.
        """
        snapshot = set_snapshot({})
        staging = open_staging()
        try:
            remember("mine.key", "value")

            assert recall("mine.key") is None
            assert staged_writes() == {"mine.key": "value"}
        finally:
            reset_staging(staging)
            reset_snapshot(snapshot)

    async def test_concurrent_executions_do_not_share_a_snapshot(self):
        seen: dict[str, Any] = {}

        async def execution(name: str) -> None:
            token = set_snapshot({"who": name})
            try:
                await asyncio.sleep(0)
                seen[name] = recall("who")
            finally:
                reset_snapshot(token)

        await asyncio.gather(execution("a"), execution("b"))

        assert seen == {"a": "a", "b": "b"}


class TestTheAgentReceivesIt:
    async def test_the_snapshot_on_the_execute_reaches_execute_task(self):
        from agentic_bus.agents.base.agent import BaseAgent
        from agentic_bus.core.protocol.envelope import (
            MessageType,
            SenderInfo,
            SenderKind,
            build_envelope,
        )

        seen = {}

        class Agent(BaseAgent):
            def capabilities(self):
                return []

            async def execute_task(self, payload, context):
                seen["clientes"] = recall("crm.clientes")
                return {"ok": True}

        class Peer:
            peer_id = "p1"

            async def send_envelope(self, env):
                pass

        agent = Agent(agent_id="reader")
        agent._peer = Peer()

        await agent._handle_execute(
            build_envelope(
                MessageType.EXECUTE,
                SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
                "s1",
                {
                    "execution_plan": {"context": {}},
                    "authorized_scopes": [],
                    "memory_snapshot": {"crm.clientes": [{"id": 7}]},
                },
            )
        )

        assert seen["clientes"] == [{"id": 7}]

    async def test_one_execution_does_not_leak_into_the_next(self):
        from agentic_bus.agents.base.agent import BaseAgent
        from agentic_bus.core.protocol.envelope import (
            MessageType,
            SenderInfo,
            SenderKind,
            build_envelope,
        )

        seen: list = []

        class Agent(BaseAgent):
            def capabilities(self):
                return []

            async def execute_task(self, payload, context):
                seen.append(recall("k"))
                return {}

        class Peer:
            peer_id = "p1"

            async def send_envelope(self, env):
                pass

        agent = Agent(agent_id="reader")
        agent._peer = Peer()

        for snapshot in ({"k": "first"}, {}):
            await agent._handle_execute(
                build_envelope(
                    MessageType.EXECUTE,
                    SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
                    "s1",
                    {
                        "execution_plan": {"context": {}},
                        "authorized_scopes": [],
                        "memory_snapshot": snapshot,
                    },
                )
            )

        assert seen == ["first", None]
