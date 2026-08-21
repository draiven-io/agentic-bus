"""Tests for the Agentic Bus protocol envelope."""

from app.core.protocol.envelope import (
    LIP_PROTOCOL_VERSION,
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
    IntentPayload,
    OfferPayload,
    AcceptPayload,
    DissolvePayload,
    TraceContext,
    build_envelope,
    PAYLOAD_TYPES,
)
from app.core.protocol.export_schemas import SCHEMA_DIR, build_schemas, check


class TestMessageTypes:
    """Verify that all Agentic Bus message types are defined per §4.1.1."""

    def test_all_types_exist(self):
        expected = {"intent", "offer", "accept", "reject", "execute", "complete", "dissolve", "event"}
        actual = {m.value for m in MessageType}
        assert actual == expected

    def test_payload_type_mapping(self):
        for mt in MessageType:
            assert mt in PAYLOAD_TYPES


class TestAgBusEnvelope:
    """Test the common message envelope (§8 of AGENTS.md)."""

    def test_default_fields(self):
        env = AgBusEnvelope(
            message_type=MessageType.INTENT,
            sender=SenderInfo(kind=SenderKind.REQUESTER, id="user-1"),
        )
        assert env.message_id  # auto-generated UUID
        assert env.timestamp  # auto-generated ISO-8601
        assert env.session_id == ""
        assert env.trace.trace_id == ""

    def test_serialisation_roundtrip(self):
        env = AgBusEnvelope(
            session_id="sess-1",
            message_type=MessageType.OFFER,
            sender=SenderInfo(kind=SenderKind.AGENT, id="agent-1", oidc_subject="sub-1"),
            trace=TraceContext(trace_id="abc", span_id="def"),
            payload={"capability_id": "route_opt"},
        )
        raw = env.model_dump_json()
        restored = AgBusEnvelope.model_validate_json(raw)
        assert restored.session_id == "sess-1"
        assert restored.sender.oidc_subject == "sub-1"
        assert restored.payload["capability_id"] == "route_opt"


class TestBuildEnvelope:
    """Test the convenience factory."""

    def test_build_with_pydantic_payload(self):
        sender = SenderInfo(kind=SenderKind.COORDINATOR, id="coord")
        payload = IntentPayload(intent_text="ship container", requested_outputs=["route"])
        env = build_envelope(MessageType.INTENT, sender, "s-1", payload)
        assert env.message_type == MessageType.INTENT
        assert env.payload["intent_text"] == "ship container"
        assert env.session_id == "s-1"

    def test_build_with_dict_payload(self):
        sender = SenderInfo(kind=SenderKind.AGENT, id="a-1")
        env = build_envelope(MessageType.COMPLETE, sender, "s-2", {"status": "ok"})
        assert env.payload["status"] == "ok"


class TestIntentPayload:
    def test_defaults(self):
        p = IntentPayload(intent_text="reduce costs by 15%")
        assert p.context == {}
        assert p.requested_outputs == []
        assert p.ibac_claims_requested == []


class TestOfferPayload:
    def test_full_offer(self):
        p = OfferPayload(
            capability_id="route_opt",
            capability_description="Optimise routes",
            estimated_cost=0.05,
            estimated_latency=2.0,
            required_scopes=["logistics:read"],
        )
        assert p.estimated_cost == 0.05
        assert p.required_scopes == ["logistics:read"]
        assert p.output_schema == {}

    def test_offer_with_output_schema(self):
        schema = {
            "title": "RouteOutput",
            "type": "object",
            "properties": {
                "distance_km": {"type": "number"},
            },
        }
        p = OfferPayload(
            capability_id="route_opt",
            capability_description="Optimise routes",
            output_schema=schema,
        )
        assert p.output_schema == schema
        assert p.output_schema["title"] == "RouteOutput"


class TestAcceptPayload:
    def test_accept_with_output_schema(self):
        schema = {"title": "MergedOutput", "type": "object"}
        p = AcceptPayload(
            offer_ids=["o-1"],
            execution_plan={"steps": []},
            output_schema=schema,
        )
        assert p.output_schema == schema

    def test_accept_default_output_schema(self):
        p = AcceptPayload(
            offer_ids=["o-1"],
            execution_plan={"steps": []},
        )
        assert p.output_schema == {}


class TestDissolvePayload:
    def test_default_reason(self):
        p = DissolvePayload()
        assert p.reason == "session_complete"


class TestProtocolVersion:
    """Every message carries the wire-format version it conforms to.

    Without it a peer has no way to tell a message it cannot parse from one
    it merely disagrees with, which makes evolving the protocol a breaking
    change by default.
    """

    def test_envelope_defaults_to_current_version(self):
        env = build_envelope(
            MessageType.INTENT,
            SenderInfo(kind=SenderKind.REQUESTER, id="req-1"),
            "session-1",
            IntentPayload(intent_text="do the thing"),
        )
        assert env.protocol_version == LIP_PROTOCOL_VERSION

    def test_version_survives_serialisation(self):
        env = build_envelope(
            MessageType.INTENT,
            SenderInfo(kind=SenderKind.REQUESTER, id="req-1"),
            "session-1",
            IntentPayload(intent_text="do the thing"),
        )
        restored = AgBusEnvelope.model_validate_json(env.model_dump_json())
        assert restored.protocol_version == LIP_PROTOCOL_VERSION

    def test_messages_from_pre_versioning_peers_are_accepted(self):
        """An envelope without the field is read as the baseline version."""
        legacy = {
            "message_id": "m-1",
            "session_id": "s-1",
            "message_type": "intent",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "sender": {"kind": "requester", "id": "req-1"},
            "payload": {"intent_text": "hello"},
        }
        env = AgBusEnvelope.model_validate(legacy)
        assert env.protocol_version == "0.1.0"


class TestSchemaExport:
    """The published JSON Schemas are generated from these models.

    CI runs ``export_schemas --check``; this asserts the generator itself
    stays consistent so a drift failure means the models changed, not that
    the exporter broke.
    """

    def test_every_message_type_has_a_payload_schema(self):
        schemas = build_schemas()
        for message_type in MessageType:
            assert f"{message_type.value}-payload.json" in schemas

    def test_envelope_schema_is_identified_and_versioned(self):
        schema = build_schemas()["envelope.json"]
        assert schema["title"] == "LIP Message Envelope"
        assert schema["x-lip-version"] == LIP_PROTOCOL_VERSION
        assert LIP_PROTOCOL_VERSION in schema["$id"]
        assert "protocol_version" in schema["properties"]

    def test_committed_schemas_match_the_models(self):
        """Guards the same invariant as CI, so a local run catches drift too."""
        assert check(SCHEMA_DIR) == []
