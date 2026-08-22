"""The conformance suite, and this SDK's own conformance.

Two things are being tested here, and they matter for different reasons.

That `BaseAgent` passes is the useful headline: the reference implementation
should satisfy the specification it publishes, and if it does not, either the
code or the specification is wrong.

That the suite *fails* a deliberately broken agent matters more. A conformance
suite everything passes certifies nothing, so each check is exercised against
an implementation that violates exactly the requirement it covers.
"""

from __future__ import annotations

import asyncio


from agentic_bus import AgentCapability, BaseAgent
from agentic_bus.conformance import (
    REQUIREMENTS,
    Level,
    check_survives_missing_acknowledgement,
    report_to_json,
    run_agent_conformance,
)
from agentic_bus.core.protocol.envelope import (
    MessageType,
    SenderInfo,
    SenderKind,
    build_envelope,
)
from agentic_bus.testing import LocalBus


class WellBehavedAgent(BaseAgent):
    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="analysis", description="Analyse a dataset"
            )
        ]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        return {"analysed": True}


async def _report_for(agent: BaseAgent, *, timeout: float = 3.0):
    async with LocalBus() as bus:
        await bus.add_agent(agent)
        return await run_agent_conformance(bus=bus, timeout=timeout)


class TestTheReferenceImplementationConforms:
    """If the SDK fails its own specification, one of the two is wrong."""

    async def test_base_agent_is_conformant(self):
        report = await _report_for(WellBehavedAgent(agent_id="good-agent"))

        assert report.is_conformant, (
            "the reference SDK fails its own specification:\n" + report.render()
        )

    async def test_the_report_identifies_the_agent(self):
        report = await _report_for(WellBehavedAgent(agent_id="good-agent"))
        assert report.agent_id == "good-agent"

    async def test_registration_and_versioning_pass(self):
        report = await _report_for(WellBehavedAgent(agent_id="good-agent"))
        by_id = {r.requirement.id: r for r in report.results}

        for requirement_id in ("LIP-REG-001", "LIP-REG-002", "LIP-VER-001"):
            assert by_id[requirement_id].passed, by_id[requirement_id].detail

    async def test_it_survives_a_coordinator_that_never_acknowledges(self):
        result = await check_survives_missing_acknowledgement(
            lambda: WellBehavedAgent(
                agent_id="good-agent", registration_timeout=0.2
            )
        )
        assert result.passed, result.detail


class TestTheSuiteDetectsViolations:
    """A suite everything passes certifies nothing."""

    async def test_an_agent_with_no_capabilities_is_warned_about(self):
        class Capless(BaseAgent):
            def capabilities(self):
                return []

            async def execute_task(self, payload, context):
                return {}

        report = await _report_for(Capless(agent_id="capless"))
        by_id = {r.requirement.id: r for r in report.results}

        assert not by_id["LIP-REG-003"].passed
        # SHOULD, so it warns without failing the run.
        assert by_id["LIP-REG-003"].requirement.level == Level.SHOULD
        assert report.is_conformant

    async def test_a_malformed_frame_fails_the_envelope_requirement(self):
        async with LocalBus() as bus:
            agent = WellBehavedAgent(agent_id="good-agent")
            await bus.add_agent(agent)

            # Something that is not an envelope at all.
            await agent._peer.ws.send("this is not JSON")
            await asyncio.sleep(0.2)

            report = await run_agent_conformance(bus=bus, timeout=2.0)

        by_id = {r.requirement.id: r for r in report.results}
        assert not by_id["LIP-MSG-001"].passed
        assert not report.is_conformant, "a malformed frame is a MUST failure"

    async def test_an_undefined_performative_is_detected(self):
        async with LocalBus() as bus:
            agent = WellBehavedAgent(agent_id="good-agent")
            await bus.add_agent(agent)

            # Structurally valid, but not a performative the protocol defines.
            rogue = build_envelope(
                MessageType.EVENT,
                SenderInfo(kind=SenderKind.AGENT, id="good-agent"),
                "s1",
                {},
            ).model_dump()
            rogue["message_type"] = "improvise"
            import json as _json

            await agent._peer.ws.send(_json.dumps(rogue))
            await asyncio.sleep(0.2)

            report = await run_agent_conformance(bus=bus, timeout=2.0)

        by_id = {r.requirement.id: r for r in report.results}
        # An unknown performative fails envelope validation before it can be
        # counted as an unknown type — either way it must not pass silently.
        assert not (by_id["LIP-MSG-001"].passed and by_id["LIP-MSG-003"].passed)
        assert not report.is_conformant

    async def test_an_agent_that_never_registers_is_not_conformant(self):
        async with LocalBus() as bus:
            report = await run_agent_conformance(bus=bus, timeout=0.5)

        assert not report.is_conformant
        assert not report.agent_id


class TestReportShape:
    def test_every_requirement_has_a_level_and_a_reference(self):
        for requirement in REQUIREMENTS:
            assert requirement.level in (Level.MUST, Level.SHOULD)
            assert requirement.reference, f"{requirement.id} cites no section"

    def test_requirement_ids_are_unique(self):
        ids = [r.id for r in REQUIREMENTS]
        assert len(ids) == len(set(ids))

    async def test_every_requirement_appears_in_a_report(self):
        """A requirement nobody evaluates is documentation, not a check."""
        report = await _report_for(WellBehavedAgent(agent_id="good-agent"))

        reported = {r.requirement.id for r in report.results}
        missing = {r.id for r in REQUIREMENTS} - reported
        assert missing == set(), f"never evaluated: {sorted(missing)}"

    async def test_the_report_serialises(self):
        report = await _report_for(WellBehavedAgent(agent_id="good-agent"))
        import json as _json

        parsed = _json.loads(report_to_json(report))
        assert parsed["conformant"] is True
        assert parsed["protocol_version"]
        assert len(parsed["results"]) == len(REQUIREMENTS)

    async def test_the_rendered_report_names_failures(self):
        async with LocalBus() as bus:
            report = await run_agent_conformance(bus=bus, timeout=0.5)

        rendered = report.render()
        assert "NOT CONFORMANT" in rendered
        assert "LIP-REG-001" in rendered


class TestGrading:
    def test_only_must_failures_break_conformance(self):
        from agentic_bus.conformance import ConformanceReport

        report = ConformanceReport()
        report.record("LIP-REG-003", passed=False, detail="no capabilities")
        assert report.is_conformant, "a SHOULD failure must not fail the run"
        assert len(report.warnings) == 1

        report.record("LIP-REG-001", passed=False, detail="never registered")
        assert not report.is_conformant
        assert len(report.failures) == 1

    def test_skipped_checks_count_as_neither(self):
        from agentic_bus.conformance import ConformanceReport

        report = ConformanceReport()
        report.skip("LIP-EXE-002", "agent unreachable")
        assert report.is_conformant
        assert not report.failures
        assert not report.warnings
