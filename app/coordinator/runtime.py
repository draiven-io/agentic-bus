"""Coordinator runtime – the top-level orchestration loop.

This module wires together all coordinator subsystems and implements the
full Agentic Bus session lifecycle:

  1. Accept & authenticate WebSocket connections
  2. Open intent sessions
  3. Discover eligible agents (semantic adjudication)
  4. Request offers
  5. Run IBAC on offers
  6. Negotiate and compose offers
  7. Build LangGraph dynamically
  8. Supervise execution
  9. Enforce governance
  10. Dissolve sessions

Per §19 of AGENTS.md, the coordinator is the authoritative runtime component
responsible for the entire session lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.protocol.envelope import (
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
    IntentPayload,
    OfferPayload,
    AcceptPayload,
    RejectPayload,
    DissolvePayload,
    build_envelope,
)
from app.core.transport.ws import WSServer, WSPeer
from app.core.session.manager import (
    SessionManager,
    SessionPhase,
    SessionState,
    NegotiationRecord,
)
from app.core.registry.capability_registry import (
    CapabilityRegistry,
    AgentRegistration,
    AgentCapability,
)
from app.core.ibac.engine import (
    IBACEngine,
    IBACRequest,
    IBACEvaluationPoint,
    IBACDecision,
)
from app.core.telemetry.tracing import agbus_span, inject_trace_context, init_telemetry
from app.core.auth.oidc import OIDCIdentity, DevVerifier
from app.core.auth.admin import AdminPolicy
from app.core.persistence.database import init_db
from app.core.persistence.repository import AgentRepository
from app.core.persistence.models import PersistentAgent
from app.coordinator.admin.service import AdminService
from app.coordinator.intent.processor import IntentProcessor
from app.coordinator.negotiation.engine import (
    SemanticAdjudicator,
    NegotiationEngine,
)
from app.coordinator.graph.builder import DynamicGraphBuilder, AgBusGraphState
from app.coordinator.execution.supervisor import ExecutionSupervisor

logger = logging.getLogger(__name__)

COORDINATOR_SENDER = SenderInfo(kind=SenderKind.COORDINATOR, id="coordinator")


class CoordinatorRuntime:
    """Top-level coordinator that implements the full Agentic Bus lifecycle.

    Usage::

        runtime = CoordinatorRuntime()
        await runtime.start()        # starts the WebSocket server
        ...
        await runtime.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        # Core subsystems
        self.sessions = SessionManager()
        self.registry = CapabilityRegistry()
        self.ibac = IBACEngine()
        self.agent_repo = AgentRepository()
        self.admin_policy = AdminPolicy.from_env()
        self.admin = AdminService(repo=self.agent_repo, policy=self.admin_policy)

        # LLM-dependent coordinator subsystems are lazily initialised.
        # The application CAN start without an LLM configured – the admin
        # must configure one via ``agbus llm add`` before processing intents.
        self._intent_processor: IntentProcessor | None = None
        self._adjudicator: SemanticAdjudicator | None = None
        self.negotiation = NegotiationEngine()
        self.graph_builder = DynamicGraphBuilder()
        self.supervisor = ExecutionSupervisor(
            session_manager=self.sessions,
            ibac_engine=self.ibac,
        )

        # Auth (dev mode by default – swap for OIDCVerifier in production)
        self._verifier = DevVerifier()

        # Transport
        self._server = WSServer(
            host=host,
            port=port,
            on_message=self._on_message,
        )

        # Peer tracking: peer_id -> OIDCIdentity
        self._identities: dict[str, OIDCIdentity] = {}
        # Agent peer mapping: agent_id -> peer_id
        self._agent_peers: dict[str, str] = {}
        # Session -> peer mapping for requesters
        self._session_requester_peers: dict[str, str] = {}

        # Telemetry
        init_telemetry("agentic-bus")

    # -----------------------------------------------------------------------
    # Lazy LLM-dependent subsystem accessors
    # -----------------------------------------------------------------------

    @property
    def intent_processor(self) -> IntentProcessor:
        """Return the intent processor, initialising the LLM on first use."""
        if self._intent_processor is None:
            self._intent_processor = IntentProcessor()
        return self._intent_processor

    @property
    def adjudicator(self) -> SemanticAdjudicator:
        """Return the semantic adjudicator, initialising the LLM on first use."""
        if self._adjudicator is None:
            self._adjudicator = SemanticAdjudicator(registry=self.registry)
        return self._adjudicator

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        # Initialise database tables (idempotent)
        init_db()
        # Pre-load approved persistent agents into the registry
        self._load_persistent_agents()
        await self._server.start()
        logger.info("Coordinator runtime started")

    async def stop(self) -> None:
        # Dissolve all active sessions
        for session in self.sessions.active_sessions():
            await self._dissolve_session(session.session_id)
        await self._server.stop()
        logger.info("Coordinator runtime stopped")

    # -----------------------------------------------------------------------
    # Message router
    # -----------------------------------------------------------------------

    async def _on_message(self, envelope: AgBusEnvelope, peer: WSPeer) -> None:
        """Route incoming Agentic Bus messages to the appropriate handler."""
        with agbus_span(
            f"agbus.message.{envelope.message_type}",
            attributes={
                "session_id": envelope.session_id,
                "message_type": envelope.message_type,
                "sender_id": envelope.sender.id,
            },
        ):
            handlers = {
                MessageType.INTENT: self._handle_intent,
                MessageType.OFFER: self._handle_offer,
                MessageType.ACCEPT: self._handle_accept,
                MessageType.REJECT: self._handle_reject,
                MessageType.COMPLETE: self._handle_complete,
            }
            handler = handlers.get(envelope.message_type)
            if handler:
                await handler(envelope, peer)
            else:
                logger.warning("Unhandled message type: %s", envelope.message_type)

    # -----------------------------------------------------------------------
    # Intent handling
    # -----------------------------------------------------------------------

    async def _handle_intent(self, envelope: AgBusEnvelope, peer: WSPeer) -> None:
        """Handle an incoming intent – the start of a Agentic Bus lifecycle."""
        with agbus_span("agbus.intent.admission"):
            intent = IntentPayload.model_validate(envelope.payload)

            # 1. Create session
            identity = self._identities.get(peer.peer_id)
            session = self.sessions.create(
                requester_id=envelope.sender.id,
                oidc_subject=identity.subject if identity else "",
            )
            session.intent = intent
            session.audit_log.append(envelope)
            self._session_requester_peers[session.session_id] = peer.peer_id

            # 2. IBAC – intent admission
            ibac_req = IBACRequest(
                evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
                requester_id=session.requester_id,
                requester_oidc_subject=session.requester_oidc_subject,
                intent_text=intent.intent_text,
                intent_context=intent.context,
                requested_scopes=intent.ibac_claims_requested,
            )
            ibac_result = self.ibac.evaluate(ibac_req)
            session.ibac_decisions.append(ibac_result.model_dump())

            if ibac_result.decision == IBACDecision.DENY:
                logger.warning("Intent denied by IBAC: %s", ibac_result.reason)
                reject_env = build_envelope(
                    MessageType.REJECT,
                    COORDINATOR_SENDER,
                    session.session_id,
                    RejectPayload(reason=f"Intent denied: {ibac_result.reason}"),
                    inject_trace_context(),
                )
                await peer.send_envelope(reject_env)
                await self._dissolve_session(session.session_id)
                return

            self.sessions.transition(session.session_id, SessionPhase.INTENT_RECEIVED)
            logger.info("Intent admitted for session %s", session.session_id)

            # 3. Decompose intent
            decomposition = await self.intent_processor.decompose(intent)
            session.composition_plan["decomposition"] = decomposition

            # 4. Discovery – semantic adjudication
            self.sessions.transition(session.session_id, SessionPhase.DISCOVERY)
            candidates = await self.adjudicator.discover(intent)
            session.discovered_agents = [c.agent_id for c in candidates]

            if not candidates:
                logger.warning("No eligible agents found for session %s", session.session_id)
                reject_env = build_envelope(
                    MessageType.REJECT,
                    COORDINATOR_SENDER,
                    session.session_id,
                    RejectPayload(reason="No eligible agents discovered"),
                    inject_trace_context(),
                )
                await peer.send_envelope(reject_env)
                await self._dissolve_session(session.session_id)
                return

            # 5. Request offers from discovered agents
            self.sessions.transition(session.session_id, SessionPhase.NEGOTIATION)
            await self._request_offers(session, candidates)

    # -----------------------------------------------------------------------
    # Offer handling
    # -----------------------------------------------------------------------

    async def _request_offers(self, session: SessionState, candidates: list) -> None:
        """Send intent to discovered agents to solicit offers."""
        for candidate in candidates:
            agent_peer_id = self._agent_peers.get(candidate.agent_id)
            if agent_peer_id is None:
                logger.warning("Agent %s has no active connection", candidate.agent_id)
                continue

            peer = self._server.get_peer(agent_peer_id)
            if peer is None:
                continue

            # Forward the intent to the agent
            intent_env = build_envelope(
                MessageType.INTENT,
                COORDINATOR_SENDER,
                session.session_id,
                session.intent or {},
                inject_trace_context(),
            )
            await peer.send_envelope(intent_env)

    async def _handle_offer(self, envelope: AgBusEnvelope, peer: WSPeer) -> None:
        """Handle an offer from a provider agent."""
        session = self.sessions.get(envelope.session_id)
        if session is None:
            logger.warning("Offer for unknown session %s", envelope.session_id)
            return

        offer = OfferPayload.model_validate(envelope.payload)
        session.audit_log.append(envelope)

        # IBAC – offer eligibility
        ibac_req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY,
            requester_id=session.requester_id,
            agent_id=envelope.sender.id,
            intent_text=session.intent.intent_text if session.intent else "",
            proposed_capabilities=[offer.capability_id],
            requested_scopes=offer.required_scopes,
        )
        ibac_result = self.ibac.evaluate(ibac_req)
        session.ibac_decisions.append(ibac_result.model_dump())

        record = NegotiationRecord(
            agent_id=envelope.sender.id,
            offer=offer,
            status="pending" if ibac_result.decision == IBACDecision.ALLOW else "rejected",
            rejection_reason="" if ibac_result.decision == IBACDecision.ALLOW else ibac_result.reason,
        )
        session.offers.append(record)

        # Check if we have enough offers to attempt negotiation convergence
        await self._try_converge(session)

    async def _try_converge(self, session: SessionState) -> None:
        """Attempt to converge negotiation after receiving offers.

        After convergence the coordinator composes the full execution plan
        and sends it to the requester as an ``offer`` for explicit approval.
        Execution does NOT begin until the requester sends ``accept``.
        """
        # Compute initial entropy (first time)
        if "initial_entropy" not in session.composition_plan:
            session.composition_plan["initial_entropy"] = (
                self.negotiation.compute_semantic_entropy(session.offers)
            )

        initial_entropy = session.composition_plan["initial_entropy"]

        # Auto-accept pending offers that passed IBAC (guardrail — not requester approval)
        for record in session.offers:
            if record.status == "pending":
                # IBAC – negotiation acceptance (guardrail gate)
                ibac_req = IBACRequest(
                    evaluation_point=IBACEvaluationPoint.NEGOTIATION_ACCEPTANCE,
                    requester_id=session.requester_id,
                    agent_id=record.agent_id,
                    intent_text=session.intent.intent_text if session.intent else "",
                    proposed_capabilities=[record.offer.capability_id],
                    requested_scopes=record.offer.required_scopes,
                )
                ibac_result = self.ibac.evaluate(ibac_req)
                session.ibac_decisions.append(ibac_result.model_dump())

                if ibac_result.decision == IBACDecision.ALLOW:
                    record.status = "accepted"
                    session.accepted_offers.append(record.agent_id)
                else:
                    record.status = "rejected"
                    record.rejection_reason = ibac_result.reason

        # Check convergence
        if self.negotiation.check_convergence(session.offers, initial_entropy):
            await self._propose_plan_to_requester(session)
            return

        # Check if fallback is needed
        round_num = session.composition_plan.get("round", 0) + 1
        session.composition_plan["round"] = round_num
        fallback = self.negotiation.needs_fallback(round_num, session.offers, initial_entropy)

        if fallback == "solidification":
            logger.warning("Negotiation failed for session %s – solidifying", session.session_id)
            await self._dissolve_session(session.session_id)
        elif fallback == "recursive_simplification":
            logger.info("Attempting recursive simplification for session %s", session.session_id)
            # In a full implementation this would re-decompose with a simpler intent

    async def _propose_plan_to_requester(self, session: SessionState) -> None:
        """Compose the full execution plan and send it to the requester for approval.

        The requester receives an ``offer`` message containing the complete
        LangGraph flow (all participating agents, their capabilities,
        topology, and merged output schema).  The requester MUST respond
        with ``accept`` to proceed or ``reject`` (optionally with
        ``renegotiate=True``) to abort or request changes.

        Execution is blocked until the requester explicitly approves.
        """
        plan = self.negotiation.compose_offers(session.offers)
        session.composition_plan.update(plan)

        if not plan.get("viable"):
            logger.warning("No viable composition for session %s", session.session_id)
            reject_env = build_envelope(
                MessageType.REJECT,
                COORDINATOR_SENDER,
                session.session_id,
                RejectPayload(reason="No viable execution plan could be composed"),
                inject_trace_context(),
            )
            requester_peer_id = self._session_requester_peers.get(session.session_id)
            if requester_peer_id:
                peer = self._server.get_peer(requester_peer_id)
                if peer:
                    await peer.send_envelope(reject_env)
            await self._dissolve_session(session.session_id)
            return

        # Build merged output schema
        merged_output_schema = self._build_merged_output_schema(plan)

        # Build a human-readable description of the flow
        participating_agents = [step["agent_id"] for step in plan.get("steps", [])]
        flow_description = " → ".join(
            f"{step['agent_id']}:{step['capability_id']}"
            for step in plan.get("steps", [])
        )

        # Send the full plan to the requester as an OFFER for approval
        from app.core.protocol.envelope import OfferPayload
        plan_offer = OfferPayload(
            capability_id="__composed_plan__",
            capability_description=f"Proposed execution flow: {flow_description}",
            composition_plan=plan,
            participating_agents=participating_agents,
            output_schema=merged_output_schema,
        )

        offer_env = build_envelope(
            MessageType.OFFER,
            COORDINATOR_SENDER,
            session.session_id,
            plan_offer,
            inject_trace_context(),
        )

        requester_peer_id = self._session_requester_peers.get(session.session_id)
        if requester_peer_id:
            peer = self._server.get_peer(requester_peer_id)
            if peer:
                await peer.send_envelope(offer_env)
                logger.info(
                    "Proposed execution plan to requester for session %s: %s",
                    session.session_id,
                    flow_description,
                )

        # Transition to awaiting approval – execution is blocked
        self.sessions.transition(session.session_id, SessionPhase.AWAITING_APPROVAL)

    async def _finalize_negotiation(self, session: SessionState) -> None:
        """Build the composition plan and proceed to execution.

        Called ONLY after the requester has explicitly approved the plan.
        """
        plan = session.composition_plan

        if not plan.get("viable"):
            logger.warning("No viable composition for session %s", session.session_id)
            await self._dissolve_session(session.session_id)
            return

        # Build and execute
        await self._build_and_execute(session)

    # -----------------------------------------------------------------------
    # Output schema merging
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_merged_output_schema(plan: dict[str, Any]) -> dict[str, Any]:
        """Merge per-step output schemas into a single composite schema.

        The merged schema uses JSON Schema ``properties`` keyed by
        ``<agent_id>:<capability_id>`` so the requester can locate each
        agent's contribution unambiguously.
        """
        steps: list[dict[str, Any]] = plan.get("steps", [])
        if not steps:
            return {}

        properties: dict[str, Any] = {}
        for step in steps:
            schema = step.get("output_schema")
            if schema:
                key = f"{step['agent_id']}:{step['capability_id']}"
                properties[key] = schema

        if not properties:
            return {}

        return {
            "type": "object",
            "description": "Merged output schema from all accepted agents",
            "properties": properties,
        }

    # -----------------------------------------------------------------------
    # Graph build & execution
    # -----------------------------------------------------------------------

    async def _build_and_execute(self, session: SessionState) -> None:
        """Dynamically build a LangGraph and execute it under supervision."""
        with agbus_span("agbus.graph.build", attributes={"session_id": session.session_id}):
            plan = session.composition_plan
            graph = self.graph_builder.build(plan)
            compiled = graph.compile()

        with agbus_span("agbus.execution.run", attributes={"session_id": session.session_id}):
            complete_env = await self.supervisor.execute(session, compiled)

        # Store results
        session.execution_results.append(complete_env.payload)
        session.audit_log.append(complete_env)

        # Send completion to requester
        requester_peer_id = self._session_requester_peers.get(session.session_id)
        if requester_peer_id:
            peer = self._server.get_peer(requester_peer_id)
            if peer:
                await peer.send_envelope(complete_env)

        # Mandatory dissolution (§16)
        await self._dissolve_session(session.session_id)

    # -----------------------------------------------------------------------
    # Completion & dissolution
    # -----------------------------------------------------------------------

    async def _handle_complete(self, envelope: AgBusEnvelope, peer: WSPeer) -> None:
        """Handle a complete message from an agent.
        
        Special case: If session_id is "__registration__", this is an agent
        registering its capabilities (§7 AGENTS.md – dynamic capability registry).
        """
        # Handle agent registration (special session_id)
        if envelope.session_id == "__registration__":
            await self._handle_agent_registration(envelope, peer)
            return
        
        # Handle normal task completion
        session = self.sessions.get(envelope.session_id)
        if session:
            session.audit_log.append(envelope)
            session.execution_results.append(envelope.payload)

    async def _handle_agent_registration(self, envelope: AgBusEnvelope, peer: WSPeer) -> None:
        """Handle agent capability registration (§7 AGENTS.md).
        
        Agents register by sending a COMPLETE message with session_id="__registration__"
        and payload containing their AgentRegistration.
        """
        try:
            payload = envelope.payload
            if "registration" not in payload:
                logger.warning("Registration message missing 'registration' key from %s", envelope.sender.id)
                return
            
            reg_data = payload["registration"]
            registration = AgentRegistration.model_validate(reg_data)
            
            # Register in the capability registry
            self.registry.register(registration)
            
            # Track the agent's peer connection for routing
            self._agent_peers[registration.agent_id] = peer.peer_id
            
            logger.info(
                "✅ Agent registered: %s (version %s) with %d capabilities",
                registration.agent_id,
                registration.version,
                len(registration.capabilities),
            )
            
            # Optionally persist to database
            try:
                persistent_agent = PersistentAgent(
                    agent_id=registration.agent_id,
                    version=registration.version,
                    semantic_description=registration.semantic_description,
                    capabilities=registration.model_dump()["capabilities"],
                    required_scopes=registration.required_scopes,
                    supported_data_domains=registration.supported_data_domains,
                )
                self.agent_repo.save(persistent_agent)
                logger.debug("Agent %s persisted to database", registration.agent_id)
            except Exception as e:
                logger.warning("Failed to persist agent %s: %s", registration.agent_id, e)
                
        except Exception as e:
            logger.exception("Failed to register agent from %s: %s", envelope.sender.id, e)

    async def _handle_accept(self, envelope: AgBusEnvelope, peer: WSPeer) -> None:
        """Handle an accept from the requester — the requester approves the plan.

        This is the critical gate: execution proceeds ONLY after the requester
        explicitly sends an ``accept`` message in response to the proposed
        execution plan (the ``offer`` with ``capability_id='__composed_plan__'``).
        """
        session = self.sessions.get(envelope.session_id)
        if session is None:
            logger.warning("Accept for unknown session %s", envelope.session_id)
            return

        session.audit_log.append(envelope)

        if session.phase != SessionPhase.AWAITING_APPROVAL:
            logger.warning(
                "Accept received in unexpected phase %s for session %s",
                session.phase,
                session.session_id,
            )
            return

        logger.info(
            "Requester approved execution plan for session %s",
            session.session_id,
        )

        # Acknowledge approval back to the requester
        accept_payload = AcceptPayload.model_validate(envelope.payload)
        merged_output_schema = self._build_merged_output_schema(session.composition_plan)

        ack_env = build_envelope(
            MessageType.ACCEPT,
            COORDINATOR_SENDER,
            session.session_id,
            AcceptPayload(
                accepted_offers=session.accepted_offers,
                composition_plan=session.composition_plan,
                output_schema=merged_output_schema,
            ),
            inject_trace_context(),
        )
        await peer.send_envelope(ack_env)

        # Now proceed to execution
        await self._finalize_negotiation(session)

    async def _handle_reject(self, envelope: AgBusEnvelope, peer: WSPeer) -> None:
        """Handle a reject — may trigger renegotiation or dissolution.

        If the requester sends ``reject`` with ``renegotiate=True``, the
        coordinator resets the negotiation phase and attempts a new
        discovery/negotiation cycle, optionally incorporating the hints
        provided in ``renegotiation_hint``.

        If ``renegotiate=False`` (default), the session is dissolved.
        """
        session = self.sessions.get(envelope.session_id)
        if session is None:
            logger.warning("Reject for unknown session %s", envelope.session_id)
            return

        session.audit_log.append(envelope)

        reject_payload = RejectPayload.model_validate(envelope.payload)

        if envelope.sender.kind == SenderKind.REQUESTER and reject_payload.renegotiate:
            logger.info(
                "Requester requested renegotiation for session %s: %s",
                session.session_id,
                reject_payload.reason,
            )
            await self._handle_renegotiation(session, reject_payload, peer)
        else:
            logger.info(
                "Requester rejected plan for session %s: %s — dissolving",
                session.session_id,
                reject_payload.reason,
            )
            await self._dissolve_session(session.session_id)

    async def _handle_renegotiation(
        self,
        session: SessionState,
        reject_payload: RejectPayload,
        peer: WSPeer,
    ) -> None:
        """Handle a renegotiation request from the requester.

        Resets negotiation state and re-runs discovery with the hints
        provided by the requester.
        """
        round_num = session.composition_plan.get("renegotiation_round", 0) + 1
        max_renegotiations = 3

        if round_num > max_renegotiations:
            logger.warning(
                "Max renegotiation rounds (%d) reached for session %s — dissolving",
                max_renegotiations,
                session.session_id,
            )
            reject_env = build_envelope(
                MessageType.REJECT,
                COORDINATOR_SENDER,
                session.session_id,
                RejectPayload(
                    reason=f"Max renegotiation rounds ({max_renegotiations}) exceeded",
                ),
                inject_trace_context(),
            )
            await peer.send_envelope(reject_env)
            await self._dissolve_session(session.session_id)
            return

        # Reset negotiation state but preserve intent and hints
        session.offers.clear()
        session.accepted_offers.clear()
        session.composition_plan = {
            "renegotiation_round": round_num,
            "renegotiation_hints": reject_payload.renegotiation_hint,
            "previous_reason": reject_payload.reason,
        }

        # If the requester provided hints, merge them into the intent context
        if reject_payload.renegotiation_hint and session.intent:
            session.intent.context.update(
                {"_renegotiation_hints": reject_payload.renegotiation_hint}
            )

        self.sessions.transition(session.session_id, SessionPhase.DISCOVERY)
        logger.info(
            "Renegotiation round %d for session %s — re-running discovery",
            round_num,
            session.session_id,
        )

        # Re-run discovery and offer solicitation
        candidates = await self.adjudicator.discover(session.intent)
        session.discovered_agents = [c.agent_id for c in candidates]

        if not candidates:
            reject_env = build_envelope(
                MessageType.REJECT,
                COORDINATOR_SENDER,
                session.session_id,
                RejectPayload(reason="No eligible agents found during renegotiation"),
                inject_trace_context(),
            )
            await peer.send_envelope(reject_env)
            await self._dissolve_session(session.session_id)
            return

        self.sessions.transition(session.session_id, SessionPhase.NEGOTIATION)
        await self._request_offers(session, candidates)

    async def _dissolve_session(self, session_id: str) -> None:
        """Mandatory dissolution – destroy all ephemeral state (§16 AGENTS.md / §5.1.2 paper).

        After dissolution, Residual Coupling R_c(A, B) = 0 (eq. 6).
        """
        with agbus_span("agbus.dissolution", attributes={"session_id": session_id}):
            session = self.sessions.get(session_id)
            if session is None:
                return

            # Emit dissolve to all participants
            dissolve_env = build_envelope(
                MessageType.DISSOLVE,
                COORDINATOR_SENDER,
                session_id,
                DissolvePayload(reason="session_complete"),
                inject_trace_context(),
            )

            # Notify requester
            requester_peer_id = self._session_requester_peers.pop(session_id, None)
            if requester_peer_id:
                peer = self._server.get_peer(requester_peer_id)
                if peer:
                    await peer.send_envelope(dissolve_env)

            # Notify agents
            for agent_id in session.discovered_agents:
                agent_peer_id = self._agent_peers.get(agent_id)
                if agent_peer_id:
                    peer = self._server.get_peer(agent_peer_id)
                    if peer:
                        await peer.send_envelope(dissolve_env)

            # Destroy session – all negotiated schemas, scopes, bindings gone
            final_snapshot = self.sessions.dissolve(session_id)
            if final_snapshot:
                logger.info(
                    "Session %s dissolved. Audit trail: %d messages",
                    session_id,
                    len(final_snapshot.audit_log),
                )

    # -----------------------------------------------------------------------
    # Persistent agent bootstrap
    # -----------------------------------------------------------------------

    def _load_persistent_agents(self) -> None:
        """Load all approved persistent agents from the DB into the registry.

        They are registered but marked as offline until they connect and
        pass challenge authentication.
        """
        for pa in self.agent_repo.list_approved():
            reg = self._persistent_agent_to_registration(pa)
            self.registry.register(reg)
            # Not online until they connect + authenticate
            self.registry.mark_offline(pa.agent_id)
        logger.info(
            "Loaded %d persistent agent(s) from database",
            len(self.agent_repo.list_approved()),
        )

    @staticmethod
    def _persistent_agent_to_registration(pa: PersistentAgent) -> AgentRegistration:
        """Convert a ``PersistentAgent`` DB record to an ``AgentRegistration``."""
        caps = [
            AgentCapability.model_validate(c)
            for c in (pa.capabilities_json or [])
        ]
        return AgentRegistration(
            agent_id=pa.agent_id,
            version=pa.version or "0.1.0",
            mode="persistent",
            capabilities=caps,
            semantic_description=pa.semantic_description or "",
            required_scopes=pa.required_scopes_json or [],
            supported_data_domains=pa.supported_domains_json or [],
        )

    # -----------------------------------------------------------------------
    # Disconnect handling
    # -----------------------------------------------------------------------

    async def handle_disconnect(self, peer_id: str) -> None:
        """Called when a WebSocket peer disconnects.

        Ephemeral agents are fully removed from the registry.
        Persistent agents are marked offline but remain discoverable.
        """
        # Find agent_id for this peer
        agent_id: str | None = None
        for aid, pid in self._agent_peers.items():
            if pid == peer_id:
                agent_id = aid
                break

        if agent_id is None:
            return

        self.registry.handle_disconnect(agent_id)
        self._agent_peers.pop(agent_id, None)
        self._identities.pop(peer_id, None)

    # -----------------------------------------------------------------------
    # Agent registration
    # -----------------------------------------------------------------------

    def register_agent(self, registration: AgentRegistration, peer_id: str) -> None:
        """Register a provider agent's capabilities and map it to a WS peer.

        For **ephemeral** agents this is all that's needed.
        For **persistent** agents the caller must have already authenticated
        via challenge–response (see ``authenticate_persistent_agent``).
        """
        self.registry.register(registration)
        self._agent_peers[registration.agent_id] = peer_id

        # Register a default executor that forwards to the agent via WS
        self.graph_builder.register_executor(
            registration.agent_id,
            self._make_ws_executor(registration.agent_id),
        )

    # -----------------------------------------------------------------------
    # Challenge–response authentication (persistent agents)
    # -----------------------------------------------------------------------

    def request_challenge(self, agent_id: str) -> bytes:
        """Generate a challenge nonce for a persistent agent.

        Raises ``ValueError`` if the agent is not enrolled or not approved.
        """
        return self.agent_repo.request_challenge(agent_id)

    def verify_challenge(self, agent_id: str, signature: bytes) -> bool:
        """Verify the agent's Ed25519 signature over the challenge nonce.

        On success the agent is considered authenticated and may call
        ``register_agent`` with ``mode='persistent'``.
        """
        return self.agent_repo.verify_challenge(agent_id, signature)

    def authenticate_persistent_agent(
        self, agent_id: str, signature: bytes, peer_id: str
    ) -> bool:
        """One-shot convenience: verify challenge + mark online.

        Returns ``True`` if authentication succeeds.
        """
        if not self.verify_challenge(agent_id, signature):
            return False
        # If already in registry (loaded at startup), just mark online
        if self.registry.get(agent_id) is not None:
            self.registry.mark_online(agent_id)
            self._agent_peers[agent_id] = peer_id
            self.graph_builder.register_executor(
                agent_id,
                self._make_ws_executor(agent_id),
            )
        return True

    def _make_ws_executor(self, agent_id: str):
        """Create a graph-node executor that delegates to a remote agent via WS."""

        async def _executor(state: AgBusGraphState) -> AgBusGraphState:
            peer_id = self._agent_peers.get(agent_id)
            if not peer_id:
                raise RuntimeError(f"Agent {agent_id} not connected")

            peer = self._server.get_peer(peer_id)
            if not peer:
                raise RuntimeError(f"Peer {peer_id} not found for agent {agent_id}")

            # Send execute message to agent
            execute_env = build_envelope(
                MessageType.EXECUTE,
                COORDINATOR_SENDER,
                state.get("session_id", ""),
                {
                    "execution_plan": {
                        "intent_text": state.get("intent_text", ""),
                        "context": state.get("context", {}),
                        "prior_results": state.get("step_results", {}),
                    },
                    "authorized_scopes": [],
                },
                inject_trace_context(),
            )
            await peer.send_envelope(execute_env)

            # Wait for complete message from agent (with timeout)
            try:
                response = await asyncio.wait_for(peer.recv_envelope(), timeout=120.0)
                results = dict(state.get("step_results", {}))
                results[agent_id] = response.payload
                return {**state, "step_results": results}
            except asyncio.TimeoutError:
                raise RuntimeError(f"Agent {agent_id} timed out during execution")

        return _executor
