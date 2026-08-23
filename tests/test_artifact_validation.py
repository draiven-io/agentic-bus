"""Holding an agent to the shape its offer promised (RFC 0002).

Every offer in this protocol carries an `output_schema`, and until now nothing
ever read one. So an agent could promise `{"routes": [...]}`, deliver
`{"result": "ok"}`, and the interaction would proceed — until the next step
consumed the artifact and assumed a field that was not there.

The tests worth reading are the ones distinguishing three outcomes that are
easy to collapse into two:

    checked and matched   ·   checked and violated   ·   nothing was promised

The third is not a pass. Saying so in an audit trail is the difference between
"we verified this" and "nobody claimed anything".
"""

from __future__ import annotations

import pytest

from agentic_bus.core.artifacts import validate_artifacts
from agentic_bus.core.transport.local import LocalTransport

ROUTES_SCHEMA = {
    "type": "object",
    "required": ["routes"],
    "properties": {
        "routes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["carrier", "transit_hours"],
                "properties": {
                    "carrier": {"type": "string"},
                    "transit_hours": {"type": "number"},
                },
            },
        }
    },
}


class TestValidateArtifacts:
    def test_a_matching_artifact_passes(self):
        report = validate_artifacts(
            [{"routes": [{"carrier": "DB Schenker", "transit_hours": 70}]}],
            ROUTES_SCHEMA,
        )

        assert report.ok
        assert report.checked == 1
        assert not report.unchecked

    def test_a_missing_required_property_is_a_violation(self):
        """The case that motivated the RFC: promised routes, delivered a status."""
        report = validate_artifacts(
            [{"result": "ok"}], ROUTES_SCHEMA, agent_id="router", capability_id="route"
        )

        assert not report.ok
        assert "routes" in report.violations[0].reason
        assert report.violations[0].agent_id == "router"

    def test_a_wrong_type_inside_the_shape_is_caught(self):
        report = validate_artifacts(
            [{"routes": [{"carrier": "DB", "transit_hours": "seventy"}]}],
            ROUTES_SCHEMA,
        )

        assert not report.ok
        # The path locates the failure rather than just naming the artifact.
        assert "transit_hours" in report.violations[0].path

    def test_every_artifact_is_checked_not_just_the_first(self):
        report = validate_artifacts(
            [{"routes": []}, {"wrong": True}, {"routes": []}], ROUTES_SCHEMA
        )

        assert report.checked == 3
        assert len(report.violations) == 1
        assert report.violations[0].index == 1

    def test_no_schema_is_unchecked_not_passed(self):
        """Distinct facts, and collapsing them makes the log say more than it knows."""
        report = validate_artifacts([{"anything": True}], None)

        assert report.unchecked
        assert report.ok  # no violations, but nothing was verified
        assert "nothing to check" in report.summary()

    def test_an_empty_schema_is_also_unchecked(self):
        assert validate_artifacts([{"a": 1}], {}).unchecked

    def test_an_unusable_schema_is_the_agent_s_defect_not_the_artifact_s(self):
        """Blaming the artifact for a broken schema would blame the wrong thing."""
        report = validate_artifacts(
            [{"a": 1}], {"type": "not-a-real-type"}, agent_id="broken"
        )

        assert report.unchecked
        assert report.ok

    def test_the_summary_names_the_agent_and_the_promise(self):
        report = validate_artifacts(
            [{"result": "ok"}],
            ROUTES_SCHEMA,
            agent_id="route-optimizer-01",
            capability_id="alternative_routing",
        )

        summary = report.summary()
        assert "route-optimizer-01" in summary
        assert "alternative_routing" in summary


@pytest.fixture
async def runtime():
    from agentic_bus.coordinator.runtime import CoordinatorRuntime

    rt = CoordinatorRuntime(transport=LocalTransport())
    await rt.start()
    yield rt
    await rt.stop()


def _session_with_offer(runtime, *, schema, agent_id="router", capability_id="route"):
    """A session holding one accepted offer that promised *schema*."""
    from agentic_bus.core.protocol.envelope import OfferPayload
    from agentic_bus.core.session.manager import NegotiationRecord

    session = runtime.sessions.create(requester_id="u1")
    session.offers.append(
        NegotiationRecord(
            agent_id=agent_id,
            offer=OfferPayload(capability_id=capability_id, output_schema=schema),
            status="accepted",
        )
    )
    return session


def _completion(runtime, session, artifacts, *, agent_id="router", capability_id="route"):
    from agentic_bus.core.protocol.envelope import (
        MessageType,
        SenderInfo,
        SenderKind,
        build_envelope,
    )

    return build_envelope(
        MessageType.COMPLETE,
        SenderInfo(kind=SenderKind.AGENT, id=agent_id),
        session.session_id,
        {
            "status": "success",
            "artifacts": artifacts,
            "metadata": {"agent_id": agent_id, "capability_id": capability_id},
        },
    )


class TestTheCoordinatorChecks:
    async def test_a_broken_promise_is_recorded_against_the_agent(self, runtime):
        session = _session_with_offer(runtime, schema=ROUTES_SCHEMA)
        envelope = _completion(runtime, session, [{"result": "ok"}])

        await runtime._validate_artifacts(envelope, session)

        entries = [
            e
            for e in runtime.audit_log.list_all()
            if e.action == "artifact.schema_violation"
        ]
        assert entries, "an artifact broke its promise and nothing recorded it"
        assert entries[0].actor == "router"

    async def test_a_kept_promise_is_silent(self, runtime):
        session = _session_with_offer(runtime, schema=ROUTES_SCHEMA)
        envelope = _completion(
            runtime, session, [{"routes": [{"carrier": "DB", "transit_hours": 70}]}]
        )

        await runtime._validate_artifacts(envelope, session)

        assert not [
            e
            for e in runtime.audit_log.list_all()
            if e.action == "artifact.schema_violation"
        ]

    async def test_an_agent_that_promised_nothing_is_not_reported(self, runtime):
        # In practice "declared nothing" is an empty dict: OfferPayload's
        # field is a dict with a default factory, not an optional.
        session = _session_with_offer(runtime, schema={})
        envelope = _completion(runtime, session, [{"anything": True}])

        await runtime._validate_artifacts(envelope, session)

        assert not [
            e
            for e in runtime.audit_log.list_all()
            if e.action == "artifact.schema_violation"
        ]

    async def test_the_right_promise_is_checked_when_an_agent_holds_several(
        self, runtime
    ):
        """Matching on agent alone would check against the wrong offer."""
        from agentic_bus.core.protocol.envelope import OfferPayload
        from agentic_bus.core.session.manager import NegotiationRecord

        session = _session_with_offer(runtime, schema=ROUTES_SCHEMA)
        session.offers.append(
            NegotiationRecord(
                agent_id="router",
                offer=OfferPayload(
                    capability_id="quote",
                    output_schema={"type": "object", "required": ["price"]},
                ),
                status="accepted",
            )
        )

        # Valid for "quote", invalid for "route" — and it says it is a quote.
        envelope = _completion(
            runtime, session, [{"price": 100}], capability_id="quote"
        )
        await runtime._validate_artifacts(envelope, session)

        assert not [
            e
            for e in runtime.audit_log.list_all()
            if e.action == "artifact.schema_violation"
        ]

    async def test_enforcement_fails_the_step(self, runtime):
        """Otherwise the next step consumes something nobody can rely on."""
        runtime._artifact_validation_enforced = True
        session = _session_with_offer(runtime, schema=ROUTES_SCHEMA)
        envelope = _completion(runtime, session, [{"result": "ok"}])

        await runtime._validate_artifacts(envelope, session)

        assert envelope.payload["status"] == "error"
        assert "schema_violation" in envelope.payload["metadata"]

    async def test_without_enforcement_the_step_stands_but_is_recorded(self, runtime):
        runtime._artifact_validation_enforced = False
        session = _session_with_offer(runtime, schema=ROUTES_SCHEMA)
        envelope = _completion(runtime, session, [{"result": "ok"}])

        await runtime._validate_artifacts(envelope, session)

        assert envelope.payload["status"] == "success"
        assert [
            e
            for e in runtime.audit_log.list_all()
            if e.action == "artifact.schema_violation"
        ]
