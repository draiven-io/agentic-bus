"""A grant, enforced inside the agent and reconciled outside it.

The loop this closes: the coordinator grants, the agent's invocation path
checks, the completion reports what was actually called, and the coordinator
compares the two. Each half is testable alone; only together do they mean
anything.
"""

from __future__ import annotations

import asyncio

from agentic_bus import AgentCapability, BaseAgent
from agentic_bus.agents.scope_guard import require_scope, scope_is_held
from agentic_bus.core.protocol.envelope import (
    MessageType,
    SenderInfo,
    SenderKind,
    build_envelope,
)
from agentic_bus.core.transport.local import LocalTransport
from agentic_bus.testing import LocalBus


class Refunder(BaseAgent):
    """An agent whose work requires a scope, checked where the work happens."""

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(capability_id="refund", required_scopes=["payments:refund"])
        ]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        require_scope("payments:refund")
        return {"refunded": payload.get("order_id", "?")}


class Adaptive(BaseAgent):
    """Chooses a narrower answer rather than failing, when unauthorised."""

    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability(capability_id="report")]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        if scope_is_held("customer:pii"):
            return {"rows": ["name", "email", "phone"]}
        return {"rows": ["name"], "redacted": True}


async def _execute(bus: LocalBus, agent_id: str, *, scopes: list[str]):
    """Authorise execution with a grant, and wait for the completion."""
    return await bus.execute(
        agent_id,
        {"order_id": "A-1"},
        authorized_scopes=scopes,
        capability_id="refund",
        timeout=5.0,
    )


class TestTheAgentEnforcesItsGrant:
    async def test_granted_work_runs(self):
        async with LocalBus() as bus:
            agent = Refunder(agent_id="refunder")
            await bus.add_agent(agent)

            complete = await _execute(bus, agent.agent_id, scopes=["payments:refund"])

            assert complete.status == "success"
            assert complete.metadata["used_scopes"] == ["payments:refund"]
            assert complete.metadata["denied_scopes"] == []

    async def test_ungranted_work_is_refused_by_the_agent(self):
        """The coordinator authorised execution; the grant still bounded it."""
        async with LocalBus() as bus:
            agent = Refunder(agent_id="refunder")
            await bus.add_agent(agent)

            complete = await _execute(bus, agent.agent_id, scopes=["carrier:quote"])

            assert complete.status == "denied"
            assert complete.artifacts[0]["scope"] == "payments:refund"

    async def test_the_attempt_is_reported_even_though_it_failed(self):
        """What it *tried* to do is the half worth having."""
        async with LocalBus() as bus:
            agent = Refunder(agent_id="refunder")
            await bus.add_agent(agent)

            complete = await _execute(bus, agent.agent_id, scopes=[])
            metadata = complete.metadata

            assert metadata["used_scopes"] == ["payments:refund"]
            assert metadata["denied_scopes"] == ["payments:refund"]

    async def test_an_empty_grant_authorises_nothing(self):
        async with LocalBus() as bus:
            agent = Refunder(agent_id="refunder")
            await bus.add_agent(agent)

            complete = await _execute(bus, agent.agent_id, scopes=[])

            assert complete.status == "denied"

    async def test_an_agent_can_narrow_instead_of_failing(self):
        async with LocalBus() as bus:
            agent = Adaptive(agent_id="reporter")
            await bus.add_agent(agent)

            complete = await _execute(bus, agent.agent_id, scopes=[])

            assert complete.status == "success"
            assert complete.artifacts[0]["redacted"] is True
            # The decision was still shaped by the grant, and recorded.
            assert "customer:pii" in complete.metadata["used_scopes"]


class TestTheCoordinatorReconciles:
    async def _runtime(self):
        from agentic_bus.coordinator.runtime import CoordinatorRuntime

        rt = CoordinatorRuntime(transport=LocalTransport())
        await rt.start()
        return rt

    def _completion(self, used: list[str], denied: list[str] | None = None):
        return build_envelope(
            MessageType.COMPLETE,
            SenderInfo(kind=SenderKind.AGENT, id="refunder"),
            "s1",
            {
                "status": "success",
                "artifacts": [{}],
                "metadata": {
                    "agent_id": "refunder",
                    "used_scopes": used,
                    "denied_scopes": denied or [],
                },
            },
        )

    async def test_use_beyond_the_grant_is_recorded_as_critical(self):
        runtime = await self._runtime()
        try:
            await runtime._reconcile_scope_usage(self._completion(["payments:write"]))

            entries = runtime.audit_log.list_all()
            exceeded = [e for e in entries if e.action == "scope.exceeded"]

            assert exceeded, "an agent exceeded its grant and nothing recorded it"
            assert exceeded[0].severity == "critical"
            assert exceeded[0].actor == "refunder"
            assert "payments:write" in exceeded[0].details
        finally:
            await runtime.stop()

    async def test_a_refusal_inside_the_agent_is_recorded_too(self):
        runtime = await self._runtime()
        try:
            await runtime._reconcile_scope_usage(
                self._completion(["payments:write"], denied=["payments:write"])
            )

            entries = runtime.audit_log.list_all()
            assert any(e.action == "scope.denied" for e in entries)
        finally:
            await runtime.stop()

    async def test_a_completion_reporting_nothing_is_not_a_finding(self):
        """Most agents declare no scopes and check none; that must stay quiet."""
        runtime = await self._runtime()
        try:
            await runtime._reconcile_scope_usage(self._completion([]))

            entries = runtime.audit_log.list_all()
            assert not [e for e in entries if e.action.startswith("scope.")]
        finally:
            await runtime.stop()


async def _eventually(predicate, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False
