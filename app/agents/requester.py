"""Intent client – simplified interface for submitting intentions to the Agentic Bus.

This module provides ``IntentClient``, a high-level abstraction for agents or
applications that need to submit intentions (act as requesters) to the coordinator.

The client handles:
- WebSocket connection management
- Message envelope construction
- Intent payload serialization
- Response handling and callbacks
- Session lifecycle tracking

Usage (simple)::

    from app.agents.requester import IntentClient
    
    client = IntentClient(requester_id="my-agent")
    result = await client.submit_intent(
        "Find the cheapest route from Shanghai to Rotterdam",
        context={"max_cost": 5000},
    )

Usage (with callbacks)::

    async def on_offer(offer):
        print(f"Received offer: {offer.capability_id}")
    
    async def on_complete(result):
        print(f"Result: {result}")
    
    client = IntentClient(requester_id="my-agent")
    await client.submit_intent(
        "Optimize logistics route",
        context={...},
        on_offer=on_offer,
        on_complete=on_complete,
    )

Usage (streaming)::

    client = IntentClient(requester_id="my-agent")
    async for message in client.submit_intent_stream(
        "Plan multi-modal route",
        context={...},
    ):
        print(f"Received: {message.message_type}")
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Awaitable

import websockets
from websockets.client import WebSocketClientProtocol

from app.core.protocol.envelope import (
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
    IntentPayload,
    OfferPayload,
    AcceptPayload,
    RejectPayload,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response callbacks
# ---------------------------------------------------------------------------

OfferCallback = Callable[[OfferPayload, AgBusEnvelope], Awaitable[None]]
AcceptCallback = Callable[[AcceptPayload, AgBusEnvelope], Awaitable[None]]
RejectCallback = Callable[[RejectPayload, AgBusEnvelope], Awaitable[None]]
CompleteCallback = Callable[[dict[str, Any], AgBusEnvelope], Awaitable[None]]
DissolveCallback = Callable[[dict[str, Any], AgBusEnvelope], Awaitable[None]]


# ---------------------------------------------------------------------------
# Plan approval
# ---------------------------------------------------------------------------

class PlanDecision:
    """The requester's decision after reviewing a proposed execution plan.

    Attributes:
        action: ``"approve"``, ``"reject"``, or ``"renegotiate"``.
        reason: Human-readable reason (used for reject/renegotiate).
        renegotiation_hint: Structured hints for the coordinator when
            ``action == "renegotiate"`` (e.g., excluded agents, cost limits).
    """

    __slots__ = ("action", "reason", "renegotiation_hint")

    def __init__(
        self,
        action: str = "approve",
        reason: str = "",
        renegotiation_hint: dict[str, Any] | None = None,
    ):
        if action not in ("approve", "reject", "renegotiate"):
            raise ValueError(f"Invalid action: {action!r}")
        self.action = action
        self.reason = reason
        self.renegotiation_hint = renegotiation_hint or {}

    def __repr__(self) -> str:
        return f"<PlanDecision action={self.action!r} reason={self.reason!r}>"


# Callback that receives the proposed plan and returns a decision.
# If None is provided, the client auto-approves (backward compatible).
PlanApprovalCallback = Callable[[OfferPayload, AgBusEnvelope], Awaitable[PlanDecision]]


# ---------------------------------------------------------------------------
# Intent result
# ---------------------------------------------------------------------------

class IntentResult:
    """Result of an intent submission (for non-streaming mode).
    
    Collects all offers, the proposed plan, the accept message, and the final result.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.offers: list[OfferPayload] = []
        self.proposed_plan: OfferPayload | None = None
        self.plan_decision: PlanDecision | None = None
        self.accept: AcceptPayload | None = None
        self.reject: RejectPayload | None = None
        self.result: dict[str, Any] | None = None
        self.dissolved: bool = False
        self.error: str | None = None

    def __repr__(self) -> str:
        status = "completed" if self.result else "rejected" if self.reject else "pending"
        return f"<IntentResult session={self.session_id} status={status} offers={len(self.offers)}>"


# ---------------------------------------------------------------------------
# Intent client
# ---------------------------------------------------------------------------

class IntentClient:
    """High-level client for submitting intentions to the Agentic Bus.
    
    This client abstracts away the low-level WebSocket protocol and provides
    a simple, async/await-friendly API for agents that need to act as requesters.
    """

    def __init__(
        self,
        requester_id: str,
        coordinator_uri: str = "ws://localhost:8765",
        oidc_subject: str = "",
        timeout: float = 30.0,
    ):
        """Initialize the intent client.
        
        Args:
            requester_id: Unique identifier for this requester
            coordinator_uri: WebSocket URI of the coordinator
            oidc_subject: OIDC subject (for authenticated requesters)
            timeout: Default timeout for intent submission (seconds)
        """
        self.requester_id = requester_id
        self.coordinator_uri = coordinator_uri
        self.oidc_subject = oidc_subject
        self.timeout = timeout

    async def submit_intent(
        self,
        intent_text: str,
        *,
        context: dict[str, Any] | None = None,
        requested_outputs: list[str] | None = None,
        ibac_claims: list[str] | None = None,
        on_offer: OfferCallback | None = None,
        on_accept: AcceptCallback | None = None,
        on_reject: RejectCallback | None = None,
        on_complete: CompleteCallback | None = None,
        on_dissolve: DissolveCallback | None = None,
        plan_approval: PlanApprovalCallback | None = None,
        auto_approve: bool = True,
        timeout: float | None = None,
    ) -> IntentResult:
        """Submit an intent and wait for the result.
        
        This method blocks until the session is complete (receives a ``complete``
        or ``reject`` message) or the timeout expires.

        The coordinator will propose an execution plan (sent as an ``offer``
        with ``capability_id='__composed_plan__'``).  By default the client
        auto-approves this plan.  To review the plan before approval, provide
        a ``plan_approval`` callback or set ``auto_approve=False`` and
        provide an ``on_offer`` callback that sends acceptance manually.
        
        Args:
            intent_text: Natural language description of the intent
            context: Additional context data (domain-specific)
            requested_outputs: List of expected output artifacts
            ibac_claims: IBAC claims requested for this intent
            on_offer: Optional callback for each offer received
            on_accept: Optional callback when coordinator accepts offers
            on_reject: Optional callback if intent is rejected
            on_complete: Optional callback when execution completes
            on_dissolve: Optional callback when session dissolves
            plan_approval: Callback invoked when the coordinator proposes the
                full execution plan.  Must return a ``PlanDecision``.
                If ``None`` and ``auto_approve=True``, the plan is
                auto-approved.
            auto_approve: If ``True`` (default) and no ``plan_approval``
                callback is given, the plan is automatically approved.
            timeout: Override default timeout (seconds)
        
        Returns:
            IntentResult containing offers, result, or rejection
        """
        timeout = timeout or self.timeout
        session_id = self._generate_session_id()
        result = IntentResult(session_id)

        try:
            async with asyncio.timeout(timeout):
                async with websockets.connect(self.coordinator_uri) as ws:
                    # Send the intent
                    await self._send_intent(
                        ws,
                        session_id,
                        intent_text,
                        context,
                        requested_outputs,
                        ibac_claims,
                    )

                    # Process responses
                    async for message in ws:
                        envelope = AgBusEnvelope.model_validate_json(message)
                        
                        # Collect response
                        done = await self._process_message(
                            envelope,
                            result,
                            ws,
                            on_offer,
                            on_accept,
                            on_reject,
                            on_complete,
                            on_dissolve,
                            plan_approval,
                            auto_approve,
                        )
                        
                        if done:
                            break

        except asyncio.TimeoutError:
            result.error = f"Timeout after {timeout}s"
            logger.error("Intent %s timed out after %ss", session_id, timeout)
        except Exception as e:
            result.error = str(e)
            logger.exception("Intent %s failed: %s", session_id, e)

        return result

    async def submit_intent_stream(
        self,
        intent_text: str,
        *,
        context: dict[str, Any] | None = None,
        requested_outputs: list[str] | None = None,
        ibac_claims: list[str] | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[AgBusEnvelope]:
        """Submit an intent and stream all response messages.
        
        This generator yields every message received from the coordinator,
        allowing the caller to process responses incrementally.
        
        Args:
            intent_text: Natural language description of the intent
            context: Additional context data (domain-specific)
            requested_outputs: List of expected output artifacts
            ibac_claims: IBAC claims requested for this intent
            timeout: Override default timeout (seconds)
        
        Yields:
            AgBusEnvelope for each message received
        """
        timeout = timeout or self.timeout
        session_id = self._generate_session_id()

        try:
            async with asyncio.timeout(timeout):
                async with websockets.connect(self.coordinator_uri) as ws:
                    # Send the intent
                    await self._send_intent(
                        ws,
                        session_id,
                        intent_text,
                        context,
                        requested_outputs,
                        ibac_claims,
                    )

                    # Stream responses
                    async for message in ws:
                        envelope = AgBusEnvelope.model_validate_json(message)
                        yield envelope
                        
                        # Stop on terminal messages
                        if envelope.message_type in (MessageType.COMPLETE, MessageType.REJECT, MessageType.DISSOLVE):
                            break

        except asyncio.TimeoutError:
            logger.error("Intent %s stream timed out after %ss", session_id, timeout)
        except Exception as e:
            logger.exception("Intent %s stream failed: %s", session_id, e)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _send_intent(
        self,
        ws: WebSocketClientProtocol,
        session_id: str,
        intent_text: str,
        context: dict[str, Any] | None,
        requested_outputs: list[str] | None,
        ibac_claims: list[str] | None,
    ) -> None:
        """Construct and send an intent message."""
        sender = SenderInfo(
            kind=SenderKind.REQUESTER,
            id=self.requester_id,
            oidc_subject=self.oidc_subject,
        )

        payload = IntentPayload(
            intent_text=intent_text,
            context=context or {},
            requested_outputs=requested_outputs or [],
            ibac_claims_requested=ibac_claims or [],
        )

        envelope = AgBusEnvelope(
            message_type=MessageType.INTENT,
            sender=sender,
            session_id=session_id,
            payload=payload.model_dump(),
        )

        await ws.send(envelope.model_dump_json())
        logger.info("Intent sent: session=%s intent=%r", session_id, intent_text)

    async def _process_message(
        self,
        envelope: AgBusEnvelope,
        result: IntentResult,
        ws: WebSocketClientProtocol,
        on_offer: OfferCallback | None,
        on_accept: AcceptCallback | None,
        on_reject: RejectCallback | None,
        on_complete: CompleteCallback | None,
        on_dissolve: DissolveCallback | None,
        plan_approval: PlanApprovalCallback | None,
        auto_approve: bool,
    ) -> bool:
        """Process a single response message. Returns True if done."""
        msg_type = envelope.message_type

        try:
            if msg_type == MessageType.OFFER:
                offer = OfferPayload.model_validate(envelope.payload)

                # Distinguish between a composed plan offer and individual agent offers
                if offer.capability_id == "__composed_plan__":
                    # This is the coordinator's proposed execution plan
                    result.proposed_plan = offer
                    logger.info(
                        "Received proposed execution plan: %s",
                        offer.capability_description,
                    )

                    # Determine the requester's decision
                    if plan_approval is not None:
                        decision = await plan_approval(offer, envelope)
                    elif auto_approve:
                        decision = PlanDecision(action="approve")
                    else:
                        # No callback and not auto-approve — notify via on_offer
                        # and let the caller handle it externally
                        if on_offer:
                            await on_offer(offer, envelope)
                        # Don't send anything yet — the caller must use
                        # approve_plan / reject_plan manually
                        return False

                    result.plan_decision = decision
                    await self._send_plan_decision(ws, envelope.session_id, decision)

                    if decision.action == "reject":
                        return True  # done
                    elif decision.action == "renegotiate":
                        # Coordinator will re-propose — keep listening
                        return False
                    # action == "approve" — keep listening for accept/complete
                    return False
                else:
                    # Individual agent offer (informational)
                    result.offers.append(offer)
                    if on_offer:
                        await on_offer(offer, envelope)
                    logger.debug("Offer received: capability=%s", offer.capability_id)

            elif msg_type == MessageType.ACCEPT:
                accept = AcceptPayload.model_validate(envelope.payload)
                result.accept = accept
                if on_accept:
                    await on_accept(accept, envelope)
                logger.debug("Accept received: offers=%d", len(accept.accepted_offers))

            elif msg_type == MessageType.REJECT:
                reject = RejectPayload.model_validate(envelope.payload)
                result.reject = reject
                if on_reject:
                    await on_reject(reject, envelope)
                logger.info("Intent rejected: %s", reject.reason)
                return True  # done

            elif msg_type == MessageType.COMPLETE:
                result.result = envelope.payload
                if on_complete:
                    await on_complete(envelope.payload, envelope)
                logger.info("Intent completed: session=%s", envelope.session_id)
                return True  # done

            elif msg_type == MessageType.DISSOLVE:
                result.dissolved = True
                if on_dissolve:
                    await on_dissolve(envelope.payload, envelope)
                logger.info("Session dissolved: %s", envelope.session_id)
                return True  # done

        except Exception as e:
            logger.exception("Error processing %s message: %s", msg_type, e)

        return False  # not done

    async def _send_plan_decision(
        self,
        ws: WebSocketClientProtocol,
        session_id: str,
        decision: PlanDecision,
    ) -> None:
        """Send the requester's plan decision (approve/reject/renegotiate) to the coordinator."""
        sender = SenderInfo(
            kind=SenderKind.REQUESTER,
            id=self.requester_id,
            oidc_subject=self.oidc_subject,
        )

        if decision.action == "approve":
            payload = AcceptPayload(approval_note=decision.reason)
            envelope = AgBusEnvelope(
                message_type=MessageType.ACCEPT,
                sender=sender,
                session_id=session_id,
                payload=payload.model_dump(),
            )
            logger.info("Approving execution plan for session %s", session_id)
        else:
            # reject or renegotiate
            payload = RejectPayload(
                reason=decision.reason,
                renegotiation_hint=decision.renegotiation_hint,
                renegotiate=(decision.action == "renegotiate"),
            )
            envelope = AgBusEnvelope(
                message_type=MessageType.REJECT,
                sender=sender,
                session_id=session_id,
                payload=payload.model_dump(),
            )
            logger.info(
                "%s execution plan for session %s: %s",
                "Renegotiating" if decision.action == "renegotiate" else "Rejecting",
                session_id,
                decision.reason,
            )

        await ws.send(envelope.model_dump_json())

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        return f"{self.requester_id}-{timestamp}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

async def submit_intent(
    intent_text: str,
    requester_id: str = "anonymous",
    context: dict[str, Any] | None = None,
    requested_outputs: list[str] | None = None,
    coordinator_uri: str = "ws://localhost:8765",
    timeout: float = 30.0,
) -> IntentResult:
    """Convenience function to submit a single intent.
    
    This is a simplified, fire-and-forget interface for one-off intent submissions.
    For more control, use the ``IntentClient`` class directly.
    
    Example::
    
        result = await submit_intent(
            "Find cheapest route from Shanghai to Rotterdam",
            requester_id="my-app",
            context={"max_cost": 5000},
        )
        
        if result.result:
            print("Success:", result.result)
        elif result.reject:
            print("Rejected:", result.reject.reason)
    """
    client = IntentClient(requester_id=requester_id, coordinator_uri=coordinator_uri, timeout=timeout)
    return await client.submit_intent(
        intent_text,
        context=context,
        requested_outputs=requested_outputs,
    )
