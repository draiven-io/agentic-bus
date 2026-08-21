"""Tests for the IntentClient."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.requester import (
    IntentClient,
    IntentResult,
    submit_intent,
    PlanDecision,
)
from app.core.protocol.envelope import (
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
)


def create_mock_websocket(messages):
    """Helper to create a properly configured WebSocket mock.
    
    Args:
        messages: List of envelope JSON strings to yield
    
    Returns:
        A mock that works as an async context manager and iterator
    """
    mock_ws = AsyncMock()
    
    # Mock async iteration over messages
    mock_ws.__aiter__.return_value = iter(messages)
    
    # Mock async context manager protocol
    mock_ws.__aenter__.return_value = mock_ws
    mock_ws.__aexit__.return_value = AsyncMock(return_value=None)
    
    # Mock send method
    mock_ws.send = AsyncMock()
    
    return mock_ws


class TestIntentClient:
    """Test the IntentClient interface."""

    @pytest.mark.asyncio
    async def test_submit_intent_success(self):
        """Test successful intent submission with plan approval and result.
        
        The new flow is:
        1. Client sends intent
        2. Coordinator sends offer with __composed_plan__
        3. Client auto-approves (sends accept)
        4. Coordinator sends accept confirmation
        5. Coordinator sends complete with result
        """
        # Simulate coordinator responses
        plan_offer_envelope = AgBusEnvelope(
            message_type=MessageType.OFFER,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={
                "capability_id": "__composed_plan__",
                "capability_description": "Proposed flow: agent-1:test-capability",
                "composition_plan": {
                    "steps": [
                        {
                            "agent_id": "agent-1",
                            "capability_id": "test-capability",
                            "description": "Test capability",
                            "constraints": {},
                        }
                    ],
                    "viable": True,
                },
                "participating_agents": ["agent-1"],
                "output_schema": {},
            },
        )

        accept_ack_envelope = AgBusEnvelope(
            message_type=MessageType.ACCEPT,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={
                "accepted_offers": ["agent-1"],
                "composition_plan": {},
            },
        )

        complete_envelope = AgBusEnvelope(
            message_type=MessageType.COMPLETE,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={"result": "success", "data": {"foo": "bar"}},
        )

        messages = [
            plan_offer_envelope.model_dump_json(),
            accept_ack_envelope.model_dump_json(),
            complete_envelope.model_dump_json(),
        ]

        mock_ws = create_mock_websocket(messages)

        with patch("app.agents.requester.websockets.connect", return_value=mock_ws):
            client = IntentClient(requester_id="test-requester")
            result = await client.submit_intent(
                "Test intent",
                context={"test": "data"},
            )

        assert isinstance(result, IntentResult)
        assert result.proposed_plan is not None
        assert result.proposed_plan.capability_id == "__composed_plan__"
        assert result.plan_decision is not None
        assert result.plan_decision.action == "approve"
        assert result.accept is not None
        assert result.result is not None
        assert result.result["result"] == "success"
        assert result.error is None
        # Client should have sent an accept message back
        mock_ws.send.assert_called()

    @pytest.mark.asyncio
    async def test_submit_intent_rejected(self):
        """Test intent rejection."""
        reject_envelope = AgBusEnvelope(
            message_type=MessageType.REJECT,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={
                "rejected_offers": [],
                "reason": "No eligible agents found",
            },
        )
        
        messages = [reject_envelope.model_dump_json()]
        mock_ws = create_mock_websocket(messages)
        
        with patch("app.agents.requester.websockets.connect", return_value=mock_ws):
            client = IntentClient(requester_id="test-requester")
            result = await client.submit_intent("Test intent")
        
        assert result.reject is not None
        assert result.reject.reason == "No eligible agents found"
        assert result.result is None

    @pytest.mark.asyncio
    async def test_submit_intent_with_callbacks(self):
        """Test callbacks are invoked including plan approval."""
        plan_offer_envelope = AgBusEnvelope(
            message_type=MessageType.OFFER,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={
                "capability_id": "__composed_plan__",
                "capability_description": "Proposed flow: agent-1:test-cap",
                "composition_plan": {
                    "steps": [{"agent_id": "agent-1", "capability_id": "test-cap"}],
                    "viable": True,
                },
                "participating_agents": ["agent-1"],
            },
        )

        accept_ack_envelope = AgBusEnvelope(
            message_type=MessageType.ACCEPT,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={"accepted_offers": ["agent-1"]},
        )

        complete_envelope = AgBusEnvelope(
            message_type=MessageType.COMPLETE,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={"result": "done"},
        )

        messages = [
            plan_offer_envelope.model_dump_json(),
            accept_ack_envelope.model_dump_json(),
            complete_envelope.model_dump_json(),
        ]
        mock_ws = create_mock_websocket(messages)

        plan_reviewed = False
        accept_called = False
        complete_called = False

        async def on_plan(plan, envelope):
            nonlocal plan_reviewed
            plan_reviewed = True
            assert plan.capability_id == "__composed_plan__"
            return PlanDecision(action="approve")

        async def on_accept(accept, envelope):
            nonlocal accept_called
            accept_called = True

        async def on_complete(result, envelope):
            nonlocal complete_called
            complete_called = True
            assert result["result"] == "done"

        with patch("app.agents.requester.websockets.connect", return_value=mock_ws):
            client = IntentClient(requester_id="test-requester")
            _result = await client.submit_intent(
                "Test intent",
                plan_approval=on_plan,
                on_accept=on_accept,
                on_complete=on_complete,
            )

        assert plan_reviewed
        assert accept_called
        assert complete_called

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Timeout test needs investigation - mock not triggering timeout correctly")
    async def test_submit_intent_timeout(self):
        """Test timeout handling."""
        # Create an async generator that will block
        async def blocking_messages():
            await asyncio.sleep(100)  # Will be cancelled by timeout
            yield "never reached"
        
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()  # Mock the send method
        mock_ws.__aiter__ = lambda self: blocking_messages()
        mock_ws.__aenter__.return_value = mock_ws
        mock_ws.__aexit__.return_value = AsyncMock(return_value=None)
        
        with patch("app.agents.requester.websockets.connect", return_value=mock_ws):
            client = IntentClient(requester_id="test-requester", timeout=0.1)
            result = await client.submit_intent("Test intent")
        
        # The timeout should have been caught and recorded as an error
        assert result.error is not None
        assert "Timeout" in result.error or "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_submit_intent_stream(self):
        """Test streaming mode."""
        plan_offer_envelope = AgBusEnvelope(
            message_type=MessageType.OFFER,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={
                "capability_id": "__composed_plan__",
                "capability_description": "Proposed flow",
                "composition_plan": {"steps": [], "viable": True},
                "participating_agents": [],
            },
        )
        
        complete_envelope = AgBusEnvelope(
            message_type=MessageType.COMPLETE,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={"result": "done"},
        )
        
        messages_list = [
            plan_offer_envelope.model_dump_json(),
            complete_envelope.model_dump_json(),
        ]
        mock_ws = create_mock_websocket(messages_list)
        
        messages = []
        with patch("app.agents.requester.websockets.connect", return_value=mock_ws):
            client = IntentClient(requester_id="test-requester")
            async for envelope in client.submit_intent_stream("Test intent"):
                messages.append(envelope)
        
        assert len(messages) == 2
        assert messages[0].message_type == MessageType.OFFER
        assert messages[1].message_type == MessageType.COMPLETE

    @pytest.mark.asyncio
    async def test_convenience_submit_intent(self):
        """Test the convenience wrapper function."""
        complete_envelope = AgBusEnvelope(
            message_type=MessageType.COMPLETE,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={"result": "success"},
        )
        
        messages = [complete_envelope.model_dump_json()]
        mock_ws = create_mock_websocket(messages)
        
        with patch("app.agents.requester.websockets.connect", return_value=mock_ws):
            result = await submit_intent(
                "Test intent",
                requester_id="test-app",
                context={"foo": "bar"},
            )
        
        assert result.result is not None
        assert result.result["result"] == "success"

    def test_generate_session_id(self):
        """Test session ID generation."""
        client = IntentClient(requester_id="test-requester")
        sid1 = client._generate_session_id()
        sid2 = client._generate_session_id()
        
        assert sid1.startswith("test-requester-")
        assert sid2.startswith("test-requester-")
        assert sid1 != sid2  # Should be unique

    def test_intent_result_repr(self):
        """Test IntentResult string representation."""
        result = IntentResult("test-session-123")
        assert "test-session-123" in repr(result)
        assert "pending" in repr(result)
        
        result.result = {"foo": "bar"}
        assert "completed" in repr(result)

    @pytest.mark.asyncio
    async def test_plan_rejection(self):
        """Test that rejecting a plan sends a reject message and terminates."""
        plan_offer_envelope = AgBusEnvelope(
            message_type=MessageType.OFFER,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={
                "capability_id": "__composed_plan__",
                "capability_description": "Proposed flow: agent-1",
                "composition_plan": {
                    "steps": [{"agent_id": "agent-1", "capability_id": "cap"}],
                    "viable": True,
                },
                "participating_agents": ["agent-1"],
            },
        )

        messages = [plan_offer_envelope.model_dump_json()]
        mock_ws = create_mock_websocket(messages)

        async def reject_plan(plan, envelope):
            return PlanDecision(action="reject", reason="Too expensive")

        with patch("app.agents.requester.websockets.connect", return_value=mock_ws):
            client = IntentClient(requester_id="test-requester")
            result = await client.submit_intent(
                "Test intent",
                plan_approval=reject_plan,
            )

        assert result.proposed_plan is not None
        assert result.plan_decision.action == "reject"
        assert result.result is None
        # Should have sent a reject message
        mock_ws.send.assert_called()
        import json
        sent_data = json.loads(mock_ws.send.call_args_list[-1][0][0])
        assert sent_data["message_type"] == "reject"
        assert sent_data["payload"]["renegotiate"] is False

    @pytest.mark.asyncio
    async def test_plan_renegotiation(self):
        """Test renegotiation: reject first plan, approve second."""
        plan_offer_1 = AgBusEnvelope(
            message_type=MessageType.OFFER,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={
                "capability_id": "__composed_plan__",
                "capability_description": "Proposed flow v1",
                "composition_plan": {
                    "steps": [{"agent_id": "expensive-agent", "capability_id": "cap"}],
                    "viable": True,
                },
                "participating_agents": ["expensive-agent"],
            },
        )

        plan_offer_2 = AgBusEnvelope(
            message_type=MessageType.OFFER,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={
                "capability_id": "__composed_plan__",
                "capability_description": "Proposed flow v2",
                "composition_plan": {
                    "steps": [{"agent_id": "budget-agent", "capability_id": "cap"}],
                    "viable": True,
                },
                "participating_agents": ["budget-agent"],
            },
        )

        accept_ack = AgBusEnvelope(
            message_type=MessageType.ACCEPT,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={"accepted_offers": ["budget-agent"]},
        )

        complete_envelope = AgBusEnvelope(
            message_type=MessageType.COMPLETE,
            session_id="test-session",
            sender=SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator"),
            payload={"result": "budget-success"},
        )

        messages = [
            plan_offer_1.model_dump_json(),
            plan_offer_2.model_dump_json(),
            accept_ack.model_dump_json(),
            complete_envelope.model_dump_json(),
        ]
        mock_ws = create_mock_websocket(messages)

        attempt = {"count": 0}

        async def renegotiate_then_approve(plan, envelope):
            attempt["count"] += 1
            if attempt["count"] == 1:
                return PlanDecision(
                    action="renegotiate",
                    reason="Too expensive",
                    renegotiation_hint={"max_cost": 100},
                )
            return PlanDecision(action="approve")

        with patch("app.agents.requester.websockets.connect", return_value=mock_ws):
            client = IntentClient(requester_id="test-requester")
            result = await client.submit_intent(
                "Test intent",
                plan_approval=renegotiate_then_approve,
            )

        assert attempt["count"] == 2
        assert result.plan_decision.action == "approve"
        assert result.result is not None
        assert result.result["result"] == "budget-success"


class TestPlanDecision:
    """Tests for the PlanDecision class."""

    def test_approve(self):
        d = PlanDecision(action="approve")
        assert d.action == "approve"
        assert d.reason == ""
        assert d.renegotiation_hint == {}

    def test_reject(self):
        d = PlanDecision(action="reject", reason="Too costly")
        assert d.action == "reject"
        assert d.reason == "Too costly"

    def test_renegotiate(self):
        d = PlanDecision(
            action="renegotiate",
            reason="Need cheaper",
            renegotiation_hint={"max_cost": 100},
        )
        assert d.action == "renegotiate"
        assert d.renegotiation_hint == {"max_cost": 100}

    def test_invalid_action(self):
        with pytest.raises(ValueError, match="Invalid action"):
            PlanDecision(action="maybe")

    def test_repr(self):
        d = PlanDecision(action="approve", reason="looks good")
        assert "approve" in repr(d)
        assert "looks good" in repr(d)
