"""Base provider agent framework (§20 of AGENTS.md).

Each provider agent MUST:
1. Authenticate using OIDC.
2. Register capabilities dynamically.
3. Receive intent and offer requests.
4. Produce offers.
5. Execute tasks only after explicit ``execute`` message.
6. Emit completion messages.
7. Support cancellation.

This module provides a base class ``BaseAgent`` that handles the protocol
handshake and message routing, allowing concrete agents to focus on
capability logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from agentic_bus.core.protocol.envelope import (
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
    IntentPayload,
    OfferPayload,
    CompletePayload,
    EventPayload,
    build_envelope,
)
from agentic_bus.core.transport.ws import WSClient, WSPeer
from agentic_bus.core.registry.capability_registry import AgentCapability, AgentRegistration
from agentic_bus.core.telemetry.tracing import agbus_span, inject_trace_context

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for Agentic Bus provider agents.

    Subclasses must implement:
    - ``capabilities()``: return the agent's capability descriptors.  Each
      ``AgentCapability`` can carry an ``output_model`` (a Pydantic class)
      that automatically derives the ``output_schema`` JSON Schema — the
      requester sees the shape of every answer before execution begins.
    - ``execute_task(payload, context)``: execute the authorised task.

    Offer generation is handled automatically by ``generate_offer`` based on
    the metadata already declared in each ``AgentCapability``.  Subclasses
    may override it for advanced scenarios but this is not required.
    """

    def __init__(
        self,
        agent_id: str,
        coordinator_uri: str = "ws://localhost:8765",
        version: str = "0.1.0",
        semantic_description: str = "",
    ):
        self.agent_id = agent_id
        self.coordinator_uri = coordinator_uri
        self.version = version
        self.semantic_description = semantic_description
        self._client: WSClient | None = None
        self._peer: WSPeer | None = None
        self._running = False

    # -----------------------------------------------------------------------
    # Abstract methods – implement in subclasses
    # -----------------------------------------------------------------------

    @abstractmethod
    def capabilities(self) -> list[AgentCapability]:
        """Return the list of capabilities this agent exposes."""
        ...

    @abstractmethod
    async def execute_task(
        self,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a task and return the result."""
        ...

    # -----------------------------------------------------------------------
    # Answer validation – assigned agents validate execution output
    # -----------------------------------------------------------------------

    async def validate_answer(
        self,
        answer: dict[str, Any],
        intent_text: str,
        context: dict[str, Any],
        ibac_rules_summary: str = "",
    ) -> dict[str, Any]:
        """Validate an execution answer against this agent's expertise and IBAC rules.

        Called by the coordinator when this agent is the *assigned validator*
        for an intent.  External agents SHOULD override this method with
        domain-specific validation logic.

        Args:
            answer: The synthesised execution output to validate.
            intent_text: The original intent text.
            context: Session context including prior validation feedback.
            ibac_rules_summary: Human-readable summary of applicable IBAC rules.

        Returns:
            A dict with:
            - ``"approved"`` (bool): whether the answer passes validation.
            - ``"reason"`` (str): explanation of the decision.
            - ``"suggestions"`` (list[str]): optional improvement suggestions
              that will be fed back into the renegotiation loop.
        """
        # Default implementation: approve everything.
        # External agents MUST override this for meaningful validation.
        return {
            "approved": True,
            "reason": "Default validation — no domain-specific checks implemented.",
            "suggestions": [],
        }

    # -----------------------------------------------------------------------
    # Default offer generation
    # -----------------------------------------------------------------------

    async def generate_offer(
        self,
        intent: IntentPayload,
        capability: AgentCapability,
    ) -> OfferPayload:
        """Build an ``OfferPayload`` from the capability descriptor.

        All cost, latency, artifact, and constraint information is already
        declared on ``AgentCapability``, so agents typically don't need to
        override this.  The method is intentionally *not* abstract — override
        only when custom negotiation logic is needed.
        """
        return OfferPayload(
            capability_id=capability.capability_id,
            capability_description=capability.description,
            constraints=capability.operational_constraints,
            expected_artifacts=capability.expected_artifacts,
            estimated_cost=capability.estimated_cost,
            estimated_latency=capability.estimated_latency,
            required_scopes=capability.required_scopes,
            output_schema=capability.output_schema,
        )

    # -----------------------------------------------------------------------
    # Event emission — agents can send progress updates during execution
    # -----------------------------------------------------------------------

    async def send_event(
        self,
        session_id: str,
        summary: str,
        *,
        category: str = "agent",
        detail: dict[str, Any] | None = None,
        progress: float | None = None,
    ) -> None:
        """Send a progress / status event to the coordinator.

        The coordinator will forward the event to the requester over
        WebSocket, providing real-time visibility into agent execution.

        Use this inside ``execute_task`` to report intermediate progress,
        log messages, or partial results.

        Args:
            session_id: The session this event belongs to.
            summary: Human-readable description of the progress.
            category: Event category (``"agent"``, ``"info"``, ``"warning"``, etc.).
            detail: Arbitrary structured data to accompany the event.
            progress: Optional progress indicator between 0.0 and 1.0.
        """
        if not self._peer:
            logger.debug("Cannot send event — not connected")
            return

        event_env = build_envelope(
            MessageType.EVENT,
            SenderInfo(kind=SenderKind.AGENT, id=self.agent_id),
            session_id,
            EventPayload(
                category=category,
                summary=summary,
                detail=detail or {},
                agent_id=self.agent_id,
                progress=progress,
            ),
            inject_trace_context(),
        )
        try:
            await self._peer.send_envelope(event_env)
        except Exception:
            logger.debug("Failed to send event for session %s", session_id)

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to the coordinator, authenticate, and register capabilities."""
        self._client = WSClient(
            uri=self.coordinator_uri,
            on_message=self._on_message,
        )

        # Connect with OIDC token in header (dev mode: JSON identity)
        auth_token = json.dumps({"sub": self.agent_id, "iss": "dev"})
        self._peer = await self._client.connect(
            extra_headers={"Authorization": f"Bearer {auth_token}"}
        )
        self._running = True
        logger.info("Agent %s connected to coordinator", self.agent_id)

        # Register capabilities
        await self._register()

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.disconnect()
        logger.info("Agent %s disconnected", self.agent_id)

    async def run_forever(self) -> None:
        """Block until the agent is stopped."""
        await self.start()
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    # -----------------------------------------------------------------------
    # Registration
    # -----------------------------------------------------------------------

    async def _register(self) -> None:
        """Send capability registration to the coordinator."""
        caps = self.capabilities()

        registration = AgentRegistration(
            agent_id=self.agent_id,
            version=self.version,
            capabilities=caps,
            semantic_description=self.semantic_description,
            required_scopes=[s for c in caps for s in c.required_scopes],
            supported_data_domains=[d for c in caps for d in c.supported_data_domains],
        )

        # Send registration as a special payload in an intent-like envelope
        # (The coordinator recognises registrations by sender kind + payload shape)
        env = build_envelope(
            message_type=MessageType.COMPLETE,  # Re-use complete as registration ack vehicle
            sender=SenderInfo(kind=SenderKind.AGENT, id=self.agent_id),
            session_id="__registration__",
            payload={"registration": registration.model_dump()},
            trace=inject_trace_context(),
        )
        if self._peer:
            await self._peer.send_envelope(env)
        logger.info("Agent %s registered %d capabilities", self.agent_id, len(caps))

    # -----------------------------------------------------------------------
    # Message handling
    # -----------------------------------------------------------------------

    async def _on_message(self, envelope: AgBusEnvelope, peer: WSPeer) -> None:
        """Route messages from the coordinator."""
        with agbus_span(
            f"agent.{self.agent_id}.handle.{envelope.message_type}",
            attributes={"session_id": envelope.session_id},
        ):
            if envelope.message_type == MessageType.INTENT:
                await self._handle_intent(envelope)
            elif envelope.message_type == MessageType.EXECUTE:
                await self._handle_execute(envelope)
            elif envelope.message_type == MessageType.DISSOLVE:
                await self._handle_dissolve(envelope)
            else:
                logger.debug(
                    "Agent %s ignoring message type %s",
                    self.agent_id,
                    envelope.message_type,
                )

    async def _handle_intent(self, envelope: AgBusEnvelope) -> None:
        """Respond to an intent with offers for each matching capability."""
        intent = IntentPayload.model_validate(envelope.payload)

        for cap in self.capabilities():
            try:
                offer = await self.generate_offer(intent, cap)

                offer_env = build_envelope(
                    MessageType.OFFER,
                    SenderInfo(kind=SenderKind.AGENT, id=self.agent_id),
                    envelope.session_id,
                    offer,
                    inject_trace_context(),
                )
                if self._peer:
                    await self._peer.send_envelope(offer_env)
                    logger.info(
                        "Agent %s sent offer for capability %s",
                        self.agent_id,
                        cap.capability_id,
                    )
            except Exception:
                logger.exception(
                    "Agent %s failed to generate offer for %s",
                    self.agent_id,
                    cap.capability_id,
                )

    async def _handle_execute(self, envelope: AgBusEnvelope) -> None:
        """Execute the authorised task and emit a complete message."""
        payload = envelope.payload
        execution_plan = payload.get("execution_plan", {})
        context = execution_plan.get("context", {})

        await self.send_event(
            envelope.session_id,
            f"Agent '{self.agent_id}' starting task execution…",
            category="agent",
        )

        try:
            result = await self.execute_task(execution_plan, context)
            status = "success"
            await self.send_event(
                envelope.session_id,
                f"Agent '{self.agent_id}' task completed successfully",
                category="agent",
                detail={"status": "success"},
            )
        except Exception as exc:
            logger.exception("Agent %s execution failed", self.agent_id)
            result = {"error": str(exc)}
            status = "error"
            await self.send_event(
                envelope.session_id,
                f"Agent '{self.agent_id}' task failed: {exc}",
                category="error",
                detail={"error": str(exc)},
            )

        complete_env = build_envelope(
            MessageType.COMPLETE,
            SenderInfo(kind=SenderKind.AGENT, id=self.agent_id),
            envelope.session_id,
            CompletePayload(
                status=status,
                artifacts=[result],
                metadata={"agent_id": self.agent_id},
            ),
            inject_trace_context(),
        )
        if self._peer:
            await self._peer.send_envelope(complete_env)

    async def _handle_dissolve(self, envelope: AgBusEnvelope) -> None:
        """Clean up any session-specific state upon dissolution."""
        logger.info(
            "Agent %s received dissolve for session %s",
            self.agent_id,
            envelope.session_id,
        )
        # Subclasses can override to clean up resources
