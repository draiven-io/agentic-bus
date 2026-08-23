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

from agentic_bus.core.protocol.envelope import (
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
    IntentPayload,
    OfferPayload,
    AcceptPayload,
    RejectPayload,
    DissolvePayload,
    EventPayload,
    RegisteredPayload,
    LIP_PROTOCOL_VERSION,
    build_envelope,
)
from agentic_bus.core.transport.base import Peer, Transport
from agentic_bus.core.transport.ws import WSServer
from agentic_bus.core.session.manager import (
    SessionManager,
    SessionPhase,
    SessionState,
    NegotiationRecord,
)
from agentic_bus.core.session.memory import (
    MemoryAccessPolicy,
    MemoryWriteRequest,
)
from agentic_bus.core.registry.capability_registry import (
    CapabilityRegistry,
    AgentRegistration,
    AgentCapability,
)
from agentic_bus.core.ibac.manifest import DeclaredIntent, DerivedFacts, IntentManifest
from agentic_bus.core.ibac.engine import (
    IBACEngine,
    IBACRequest,
    IBACEvaluationPoint,
)
from agentic_bus.core.telemetry.tracing import agbus_span, inject_trace_context, init_telemetry
from agentic_bus.core.auth.agent_auth import AgentAuthPolicy
from agentic_bus.core.auth.admin import AdminPolicy
from agentic_bus.core.persistence.database import init_db
from agentic_bus.core.persistence.models import AgentStatus
from agentic_bus.core.persistence.repository import AgentRepository
from agentic_bus.core.persistence.scope_repository import ScopeRepository
from agentic_bus.core.scopes import ScopePolicy
from agentic_bus.core.persistence.models import PersistentAgent, ManagedAgentStatus
from agentic_bus.agents.managed_server import ManagedAgentServer
from agentic_bus.coordinator.admin.service import AdminService
from agentic_bus.coordinator.intent.processor import IntentProcessor
from agentic_bus.coordinator.negotiation.engine import (
    SemanticAdjudicator,
    NegotiationEngine,
)
from agentic_bus.coordinator.graph.builder import DynamicGraphBuilder, AgBusGraphState
from agentic_bus.coordinator.execution.supervisor import ExecutionSupervisor
from agentic_bus.coordinator.validation.engine import AnswerValidationEngine, ValidationResult
from agentic_bus.coordinator.admin.audit import AuditLog
from agentic_bus.core.persistence.managed_agent_repository import ManagedAgentRepository
from agentic_bus.core.persistence.session_archive_repository import SessionArchiveRepository
from agentic_bus.core.persistence.mcp_server_repository import MCPServerRepository

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
        transport: Transport | None = None,
    ):
        """
        Parameters
        ----------
        host, port:
            Bind address for the default WebSocket transport. Ignored when
            *transport* is supplied.
        transport:
            Where peers arrive. Defaults to a WebSocket server, which is what
            you want when agents are separate processes. Pass a
            :class:`~agentic_bus.core.transport.local.LocalTransport` to run
            the coordinator as a library inside a host application, with no
            socket and no port.
        """
        # Core subsystems
        self.sessions = SessionManager()
        self.registry = CapabilityRegistry()
        self.ibac = IBACEngine()
        self.agent_repo = AgentRepository()
        self.admin_policy = AdminPolicy.from_env()
        self.admin = AdminService(repo=self.agent_repo, policy=self.admin_policy)
        self.managed_repo = ManagedAgentRepository()
        self.archive_repo = SessionArchiveRepository()
        self.mcp_repo = MCPServerRepository()
        self.audit_log = AuditLog()

        # User & tenant management
        from agentic_bus.core.persistence.user_repository import UserRepository
        from agentic_bus.core.persistence.tenant_repository import TenantRepository

        self.user_repo = UserRepository()
        self.tenant_repo = TenantRepository()

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
            max_retries=3,
        )
        self.validation_engine = AnswerValidationEngine(ibac_engine=self.ibac)

        # Validator registry: agent_id -> BaseAgent instance (for managed
        # agents that run in-process).  External agents are validated via WS.
        self._validator_agents: dict[str, Any] = {}

        # Admission control. The policy picks its own verifier: OIDC when an
        # issuer is configured, permissive otherwise. Previously a DevVerifier
        # was constructed here and never consulted, so a production deployment
        # with an IdP configured still authenticated nobody.
        self._auth = AgentAuthPolicy()
        # Scope vocabulary (RFC 0003): the catalogue belongs to this
        # deployment, and a grant comes from a binding rather than from an
        # agent having declared it.
        self.scope_repo = ScopeRepository()
        self._scopes = ScopePolicy()
        if self._scopes.auto_catalogues:
            logger.info(
                "Scope catalogue is permissive — unrecognised scopes are added "
                "on first sight. Set AGBUS_SCOPE_CATALOGUE_ENFORCED=true to "
                "refuse them instead."
            )
        if self._auth.is_development:
            logger.warning(
                "No AGBUS_OIDC_ISSUER configured — agent credentials are not "
                "cryptographically verified. Set one before exposing this bus."
            )

        # Transport. The coordination logic below never touches the wire —
        # it asks for a peer and sends an envelope — so the choice is the
        # caller's.
        if transport is not None:
            self._server: Transport = transport
            for attr, handler in (
                ("_on_message", self._on_message),
                ("_on_disconnect", self.handle_disconnect),
            ):
                # Both shipped transports take their handlers at construction,
                # but an injected one is built before the runtime exists, so
                # the wiring happens here instead.
                if getattr(transport, attr, None) is None:
                    setattr(transport, attr, handler)
        else:
            self._server = WSServer(
                host=host,
                port=port,
                on_message=self._on_message,
                on_disconnect=self.handle_disconnect,
                auth_handler=self._auth.authenticate,
            )

        # Agent peer mapping: agent_id -> peer_id
        self._agent_peers: dict[str, str] = {}
        # Session -> peer mapping for requesters
        self._session_requester_peers: dict[str, str] = {}
        # Managed agent tasks: agent_id -> asyncio.Task
        self._managed_tasks: dict[str, asyncio.Task] = {}
        # MCP bridge tracking: server_id -> asyncio.Task / agent instance
        self._mcp_bridge_tasks: dict[str, asyncio.Task] = {}
        self._mcp_bridge_agents: dict[str, Any] = {}
        # Pending execution completions: (session_id, agent_id) -> Future
        self._pending_completions: dict[tuple[str, str], asyncio.Future[AgBusEnvelope]] = {}

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
        # Start the WebSocket server BEFORE spawning managed agents so
        # they can connect back immediately.
        await self._server.start()
        # Start active managed agents as independent server tasks
        await self._start_managed_agents()
        # Start active MCP bridge agents
        await self._start_mcp_bridges()
        self.audit_log.log(
            action="system.startup",
            actor="coordinator",
            target="coordinator",
            target_type="system",
            details=f"Coordinator runtime started on {self._server.description}",
            severity="info",
        )
        logger.info("Coordinator runtime started")

    async def stop(self) -> None:
        # Stop all MCP bridge tasks
        await self._stop_all_mcp_bridges()
        # Stop all managed agent tasks
        await self._stop_all_managed_agents()
        # Dissolve all active sessions
        for session in self.sessions.active_sessions():
            await self._dissolve_session(session.session_id)
        await self._server.stop()
        logger.info("Coordinator runtime stopped")

    # -----------------------------------------------------------------------
    # Message router
    # -----------------------------------------------------------------------

    async def _on_message(self, envelope: AgBusEnvelope, peer: Peer) -> None:
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
                MessageType.REGISTER: self._handle_register,
                MessageType.INTENT: self._handle_intent,
                MessageType.OFFER: self._handle_offer,
                MessageType.ACCEPT: self._handle_accept,
                MessageType.REJECT: self._handle_reject,
                MessageType.COMPLETE: self._handle_complete,
                MessageType.EVENT: self._handle_agent_event,
            }
            handler = handlers.get(envelope.message_type)
            if handler:
                await handler(envelope, peer)
            else:
                logger.warning("Unhandled message type: %s", envelope.message_type)

    # -----------------------------------------------------------------------
    # IBAC manifest
    # -----------------------------------------------------------------------

    def _build_manifest(
        self,
        *,
        evaluation_point: IBACEvaluationPoint,
        envelope: AgBusEnvelope | None = None,
        peer: Peer | None = None,
        session: Any | None = None,
        declared: dict[str, Any] | None = None,
    ) -> IntentManifest:
        """Assemble an intent manifest, keeping claims and facts apart.

        Everything the message body carries is *declared*. Everything resolved
        from the authenticated connection or from the coordinator's own state
        is *derived*. The distinction decides which rules can carry a
        guarantee, so it is made here rather than trusted to each call site.
        """
        identity = getattr(peer, "identity", None) if peer is not None else None

        # Resolved from the connection the message arrived on — not from the
        # envelope's sender field, which the sender writes.
        authenticated_agent_id = ""
        if peer is not None:
            for agent_id, peer_id in self._agent_peers.items():
                if peer_id == peer.peer_id:
                    authenticated_agent_id = agent_id
                    break

        return IntentManifest(
            declared=DeclaredIntent(
                claimed_agent_id=envelope.sender.id if envelope is not None else "",
                **(declared or {}),
            ),
            derived=DerivedFacts(
                evaluation_point=evaluation_point.value,
                session_id=getattr(session, "session_id", "") if session else "",
                authenticated_subject=identity.subject if identity else "",
                authenticated_agent_id=authenticated_agent_id,
                identity_verified=identity is not None,
            ),
        )

    # -----------------------------------------------------------------------
    # Progress events
    # -----------------------------------------------------------------------

    async def _emit_event(
        self,
        session_id: str,
        category: str,
        summary: str,
        *,
        phase: str = "",
        detail: dict[str, Any] | None = None,
        agent_id: str = "",
        step_index: int | None = None,
        progress: float | None = None,
    ) -> None:
        """Send a progress / status event to the requester over WebSocket.

        Events are informational – they do not change session state.  They
        provide real-time visibility into every coordinator decision.
        """
        requester_peer_id = self._session_requester_peers.get(session_id)
        if not requester_peer_id:
            return
        peer = self._server.get_peer(requester_peer_id)
        if not peer:
            return

        event_env = build_envelope(
            MessageType.EVENT,
            COORDINATOR_SENDER,
            session_id,
            EventPayload(
                category=category,
                phase=phase,
                summary=summary,
                detail=detail or {},
                agent_id=agent_id,
                step_index=step_index,
                progress=progress,
            ),
            inject_trace_context(),
        )
        try:
            await peer.send_envelope(event_env)
        except Exception:
            logger.debug("Failed to send event to requester for session %s", session_id)

    async def _handle_agent_event(self, envelope: AgBusEnvelope, peer: Peer) -> None:
        """Forward an event from an agent to the session's requester.

        Agents emit ``EVENT`` messages during execution to report progress,
        intermediate results, log messages, etc.  The coordinator relays
        them to the requester so the UI can display live updates.
        """
        session = self.sessions.get(envelope.session_id)
        if session is None:
            logger.debug("Event for unknown session %s", envelope.session_id)
            return

        # Forward to the requester as-is (the sender info already identifies the agent)
        requester_peer_id = self._session_requester_peers.get(envelope.session_id)
        if requester_peer_id:
            requester_peer = self._server.get_peer(requester_peer_id)
            if requester_peer:
                await requester_peer.send_envelope(envelope)

    # -----------------------------------------------------------------------
    # Intent handling
    # -----------------------------------------------------------------------

    async def _handle_intent(self, envelope: AgBusEnvelope, peer: Peer) -> None:
        """Handle an incoming intent – the start of a Agentic Bus lifecycle."""
        with agbus_span("agbus.intent.admission"):
            intent = IntentPayload.model_validate(envelope.payload)

            # 1. Create session
            identity = getattr(peer, "identity", None)
            session = self.sessions.create(
                requester_id=envelope.sender.id,
                oidc_subject=identity.subject if identity else "",
            )
            session.intent = intent
            session.audit_log.append(envelope)
            self._session_requester_peers[session.session_id] = peer.peer_id

            # Capture assigned validator agent (if specified)
            if intent.assigned_agent_id:
                session.assigned_agent_id = intent.assigned_agent_id
                logger.info(
                    "Agent '%s' assigned as validator for session %s",
                    intent.assigned_agent_id,
                    session.session_id,
                )

            self.audit_log.log(
                action="session.created",
                actor=envelope.sender.id,
                target=session.session_id,
                target_type="session",
                details=f'Intent: "{intent.intent_text[:120]}"',
                severity="info",
            )

            await self._emit_event(
                session.session_id,
                "phase",
                "Session created — evaluating intent admission",
                phase="created",
                progress=0.05,
            )

            # 2. IBAC – intent admission
            await self._emit_event(
                session.session_id,
                "ibac",
                "Running IBAC intent admission check…",
                phase="intent_admission",
                progress=0.10,
            )

            ibac_req = IBACRequest(
                evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
                requester_id=session.requester_id,
                requester_oidc_subject=session.requester_oidc_subject,
                intent_text=intent.intent_text,
                intent_context=intent.context,
                requested_scopes=intent.ibac_claims_requested,
                manifest=self._build_manifest(
                    evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
                    envelope=envelope,
                    peer=peer,
                    session=session,
                    declared={
                        "intent_text": intent.intent_text,
                        "context": intent.context,
                        "purpose": str(intent.context.get("purpose", "")),
                        "requested_scopes": intent.ibac_claims_requested,
                    },
                ),
            )
            ibac_result = await self.ibac.evaluate_with_llm(ibac_req)
            session.ibac_decisions.append(ibac_result.model_dump())

            await self._emit_event(
                session.session_id,
                "ibac",
                f"IBAC intent admission: {ibac_result.decision.upper()} — {ibac_result.reason}",
                phase="intent_admission",
                detail=ibac_result.model_dump(),
                progress=0.15,
            )

            if not ibac_result.is_allowed:
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

            await self._emit_event(
                session.session_id,
                "phase",
                "Intent admitted — decomposing into sub-intents…",
                phase="intent_received",
                progress=0.20,
            )

            # 3. Decompose intent
            decomposition = await self.intent_processor.decompose(intent)
            session.composition_plan["decomposition"] = decomposition

            sub_count = len(decomposition.get("sub_intents", []))
            await self._emit_event(
                session.session_id,
                "phase",
                f"Intent decomposed into {sub_count} sub-intent(s): {decomposition.get('rationale', '')}",
                phase="decomposition",
                detail=decomposition,
                progress=0.30,
            )

            # 4. Discovery – semantic adjudication
            self.sessions.transition(session.session_id, SessionPhase.DISCOVERY)
            await self._emit_event(
                session.session_id,
                "discovery",
                "Discovering eligible agents via semantic adjudication…",
                phase="discovery",
                progress=0.35,
            )

            candidates = await self.adjudicator.discover(intent)
            session.discovered_agents = [c.agent_id for c in candidates]

            if not candidates:
                await self._emit_event(
                    session.session_id,
                    "discovery",
                    "No eligible agents found — session will be terminated",
                    phase="discovery",
                    progress=1.0,
                )
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

            await self._emit_event(
                session.session_id,
                "discovery",
                f"Discovered {len(candidates)} eligible agent(s): {', '.join(c.agent_id for c in candidates)}",
                phase="discovery",
                detail={"agents": [c.agent_id for c in candidates]},
                progress=0.40,
            )

            # 5. Request offers from discovered agents
            self.sessions.transition(session.session_id, SessionPhase.NEGOTIATION)
            await self._emit_event(
                session.session_id,
                "negotiation",
                "Soliciting offers from discovered agents…",
                phase="negotiation",
                progress=0.45,
            )
            await self._request_offers(session, candidates)

    # -----------------------------------------------------------------------
    # Offer handling
    # -----------------------------------------------------------------------

    async def _request_offers(self, session: SessionState, candidates: list) -> None:
        """Send intent to discovered agents to solicit offers.

        All agents (ephemeral, persistent, and managed) are contacted over
        WebSocket.  Managed agents run as independent server processes and
        connect to the coordinator just like any other agent.
        """
        for candidate in candidates:
            agent_peer_id = self._agent_peers.get(candidate.agent_id)
            if agent_peer_id is None:
                logger.warning("Agent %s has no active connection", candidate.agent_id)
                continue

            peer = self._server.get_peer(agent_peer_id)
            if peer is None:
                continue

            session.solicited_agents.append(candidate.agent_id)
            intent_env = build_envelope(
                MessageType.INTENT,
                COORDINATOR_SENDER,
                session.session_id,
                session.intent or {},
                inject_trace_context(),
            )
            await peer.send_envelope(intent_env)

    async def _handle_offer(self, envelope: AgBusEnvelope, peer: Peer) -> None:
        """Handle an offer from a provider agent."""
        session = self.sessions.get(envelope.session_id)
        if session is None:
            logger.warning("Offer for unknown session %s", envelope.session_id)
            return

        offer = OfferPayload.model_validate(envelope.payload)
        session.audit_log.append(envelope)

        await self._emit_event(
            session.session_id,
            "negotiation",
            f"Received offer from agent '{envelope.sender.id}' for capability '{offer.capability_id}'",
            phase="negotiation",
            agent_id=envelope.sender.id,
            detail={
                "capability_id": offer.capability_id,
                "estimated_cost": offer.estimated_cost,
                "estimated_latency": offer.estimated_latency,
            },
        )

        # IBAC – offer eligibility
        await self._emit_event(
            session.session_id,
            "ibac",
            f"Evaluating IBAC offer eligibility for agent '{envelope.sender.id}'…",
            phase="negotiation",
            agent_id=envelope.sender.id,
        )

        ibac_req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY,
            requester_id=session.requester_id,
            agent_id=envelope.sender.id,
            intent_text=session.intent.intent_text if session.intent else "",
            proposed_capabilities=[offer.capability_id],
            requested_scopes=offer.required_scopes,
            manifest=self._build_manifest(
                evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY,
                envelope=envelope,
                peer=peer,
                session=session,
                declared={
                    "intent_text": session.intent.intent_text if session.intent else "",
                    "proposed_capabilities": [offer.capability_id],
                    "requested_scopes": offer.required_scopes,
                },
            ),
        )
        ibac_result = await self.ibac.evaluate_with_llm(ibac_req)
        session.ibac_decisions.append(ibac_result.model_dump())

        record = NegotiationRecord(
            agent_id=envelope.sender.id,
            offer=offer,
            status="pending" if ibac_result.is_allowed else "rejected",
            rejection_reason="" if ibac_result.is_allowed else ibac_result.reason,
        )
        session.offers.append(record)

        eligibility_status = "eligible" if ibac_result.is_allowed else "rejected"
        await self._emit_event(
            session.session_id,
            "ibac",
            f"IBAC offer eligibility for '{envelope.sender.id}': {eligibility_status}"
            + (f" — {ibac_result.reason}" if ibac_result.reason else ""),
            phase="negotiation",
            agent_id=envelope.sender.id,
            detail=ibac_result.model_dump(),
        )

        # Check if we have enough offers to attempt negotiation convergence
        await self._try_converge(session)

    async def _try_converge(self, session: SessionState) -> None:
        """Attempt to converge negotiation after receiving offers.

        After convergence the coordinator composes the full execution plan
        and sends it to the requester as an ``offer`` for explicit approval.
        Execution does NOT begin until the requester sends ``accept``.
        """
        # Guard: don't re-propose if already awaiting approval or dissolved
        if session.phase in (SessionPhase.AWAITING_APPROVAL, SessionPhase.DISSOLVED):
            logger.debug(
                "Session %s in phase %s – ignoring late offer",
                session.session_id, session.phase,
            )
            return

        # Wait until all solicited agents have responded
        expected = set(session.solicited_agents) or set(session.discovered_agents)
        responded = {o.agent_id for o in session.offers}
        if not expected.issubset(responded):
            pending = expected - responded
            await self._emit_event(
                session.session_id,
                "negotiation",
                f"Waiting for offers: {len(responded)}/{len(expected)} agents responded (pending: {', '.join(pending)})",
                phase="negotiation",
                progress=0.50,
            )
            return

        await self._emit_event(
            session.session_id,
            "negotiation",
            f"All {len(expected)} solicited agents have responded — evaluating offers…",
            phase="negotiation",
            progress=0.55,
        )

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
                await self._emit_event(
                    session.session_id,
                    "ibac",
                    f"Running IBAC negotiation acceptance for agent '{record.agent_id}'…",
                    phase="negotiation",
                    agent_id=record.agent_id,
                )

                ibac_req = IBACRequest(
                    evaluation_point=IBACEvaluationPoint.NEGOTIATION_ACCEPTANCE,
                    requester_id=session.requester_id,
                    agent_id=record.agent_id,
                    intent_text=session.intent.intent_text if session.intent else "",
                    proposed_capabilities=[record.offer.capability_id],
                    requested_scopes=record.offer.required_scopes,
                )
                ibac_result = await self.ibac.evaluate_with_llm(ibac_req)
                session.ibac_decisions.append(ibac_result.model_dump())

                if ibac_result.is_allowed:
                    record.status = "accepted"
                    session.accepted_offers.append(record.agent_id)
                    await self._emit_event(
                        session.session_id,
                        "negotiation",
                        f"Offer from '{record.agent_id}' accepted (IBAC approved)",
                        phase="negotiation",
                        agent_id=record.agent_id,
                    )
                else:
                    record.status = "rejected"
                    record.rejection_reason = ibac_result.reason
                    await self._emit_event(
                        session.session_id,
                        "negotiation",
                        f"Offer from '{record.agent_id}' rejected by IBAC: {ibac_result.reason}",
                        phase="negotiation",
                        agent_id=record.agent_id,
                    )

        # Check convergence
        if self.negotiation.check_convergence(session.offers, initial_entropy):
            await self._emit_event(
                session.session_id,
                "negotiation",
                "Negotiation converged — composing execution plan…",
                phase="negotiation",
                progress=0.65,
            )
            await self._propose_plan_to_requester(session)
            return

        # Check if fallback is needed
        round_num = session.composition_plan.get("round", 0) + 1
        session.composition_plan["round"] = round_num
        fallback = self.negotiation.needs_fallback(round_num, session.offers, initial_entropy)

        if fallback == "solidification":
            await self._emit_event(
                session.session_id,
                "warning",
                "Negotiation failed to converge — solidifying session",
                phase="negotiation",
            )
            logger.warning("Negotiation failed for session %s – solidifying", session.session_id)
            await self._dissolve_session(session.session_id)
        elif fallback == "recursive_simplification":
            await self._emit_event(
                session.session_id,
                "negotiation",
                f"Attempting recursive simplification (round {round_num})",
                phase="negotiation",
            )
            logger.info("Attempting recursive simplification for session %s", session.session_id)
            await self._try_propose_from_accepted(session)
        else:
            # All agents have responded but entropy hasn't converged and
            # we haven't reached the fallback threshold yet.  Rather than
            # silently stalling, proceed with accepted offers if any.
            accepted = [o for o in session.offers if o.status == "accepted"]
            if accepted:
                logger.info(
                    "Entropy not converged (round %d) but all agents responded; "
                    "proceeding with %d accepted offer(s) for session %s",
                    round_num, len(accepted), session.session_id,
                )
                await self._emit_event(
                    session.session_id,
                    "negotiation",
                    f"Proceeding with {len(accepted)} accepted agent(s) "
                    f"({', '.join(o.agent_id for o in accepted)}) — "
                    f"some offers were rejected by IBAC",
                    phase="negotiation",
                    progress=0.65,
                )
                await self._propose_plan_to_requester(session)
            else:
                logger.warning(
                    "No accepted offers for session %s (round %d) — dissolving",
                    session.session_id, round_num,
                )
                await self._emit_event(
                    session.session_id,
                    "warning",
                    "No agents could be accepted — dissolving session",
                    phase="negotiation",
                )
                await self._dissolve_session(session.session_id)

    async def _try_propose_from_accepted(self, session: SessionState) -> None:
        """Propose a plan from accepted offers, or dissolve if none remain."""
        accepted = [o for o in session.offers if o.status == "accepted"]
        if accepted:
            logger.info(
                "Simplifying to %d accepted agent(s) for session %s",
                len(accepted), session.session_id,
            )
            await self._emit_event(
                session.session_id,
                "negotiation",
                f"Simplified plan: proceeding with {len(accepted)} accepted agent(s) "
                f"({', '.join(o.agent_id for o in accepted)})",
                phase="negotiation",
                progress=0.65,
            )
            await self._propose_plan_to_requester(session)
        else:
            logger.warning(
                "No accepted offers after simplification for session %s — dissolving",
                session.session_id,
            )
            await self._emit_event(
                session.session_id,
                "warning",
                "No agents could be accepted after recursive simplification — dissolving session",
                phase="negotiation",
            )
            await self._dissolve_session(session.session_id)

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
            await self._emit_event(
                session.session_id,
                "warning",
                "No viable execution plan could be composed from the received offers",
                phase="negotiation",
            )
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

        await self._emit_event(
            session.session_id,
            "phase",
            f"Execution plan composed: {flow_description}",
            phase="plan_proposed",
            detail={"steps": plan.get("steps", []), "agents": participating_agents},
            progress=0.70,
        )

        # Explain the role of each step in the execution plan
        await self._explain_execution_plan(session, plan)

        # Send the full plan to the requester as an OFFER for approval
        from agentic_bus.core.protocol.envelope import OfferPayload
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

    # -----------------------------------------------------------------------
    # Execution plan explanation
    # -----------------------------------------------------------------------

    _PLAN_EXPLANATION_SYSTEM = """\
You are the coordinator of the Agentic Bus Protocol.
Given a user intent and an execution plan (a sequence of agent steps), explain
WHY each step is necessary and what role it plays in fulfilling the intent.

For each step, provide:
- A short role description (what this step accomplishes toward the intent).
- Why this specific agent/capability was chosen.
- If an agent appears multiple times, explain clearly why each invocation
  is distinct and what different aspect of the intent it addresses.

Return ONLY a JSON object (no markdown fences, no commentary):
{{
  "plan_rationale": "<one-paragraph summary of the overall strategy>",
  "steps": [
    {{
      "step_number": 1,
      "agent_id": "<agent>",
      "capability_id": "<capability>",
      "role": "<what this step does and why it is needed>"
    }}
  ]
}}
"""

    _PLAN_EXPLANATION_HUMAN = """\
Intent: {intent_text}
Context: {context}

Execution plan steps:
{steps_description}
"""

    async def _explain_execution_plan(
        self,
        session: SessionState,
        plan: dict[str, Any],
    ) -> None:
        """Use the coordinator LLM to explain each step's role in the plan.

        Emits a ``plan_explanation`` event so the UI can display the
        rationale for why each agent is called and, in particular, why an
        agent may appear multiple times with different responsibilities.
        """
        steps = plan.get("steps", [])
        if not steps:
            return

        steps_text = "\n".join(
            f"  Step {i+1}: agent={s['agent_id']}, "
            f"capability={s['capability_id']}, "
            f"description={s.get('description', 'N/A')}"
            for i, s in enumerate(steps)
        )

        try:
            from agentic_bus.core.llm import get_llm
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser

            llm = get_llm()
            prompt = ChatPromptTemplate.from_messages([
                ("system", self._PLAN_EXPLANATION_SYSTEM),
                ("human", self._PLAN_EXPLANATION_HUMAN),
            ])
            chain = prompt | llm | JsonOutputParser()

            result = await chain.ainvoke({
                "intent_text": session.intent.intent_text if session.intent else "",
                "context": str(session.intent.context if session.intent else {}),
                "steps_description": steps_text,
            })

            rationale = result.get("plan_rationale", "")
            step_roles = result.get("steps", [])

            # Emit overall rationale
            await self._emit_event(
                session.session_id,
                "plan_explanation",
                f"Plan rationale: {rationale}",
                phase="plan_proposed",
                detail={"plan_rationale": rationale, "step_roles": step_roles},
            )

            # Emit per-step role explanations
            for sr in step_roles:
                step_num = sr.get("step_number", "?")
                agent_id = sr.get("agent_id", "")
                capability_id = sr.get("capability_id", "")
                role = sr.get("role", "")
                await self._emit_event(
                    session.session_id,
                    "plan_explanation",
                    f"Step {step_num} — {agent_id}:{capability_id}: {role}",
                    phase="plan_proposed",
                    agent_id=agent_id,
                    detail=sr,
                )

        except Exception:
            logger.warning(
                "Failed to generate plan explanation for session %s",
                session.session_id,
                exc_info=True,
            )

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
        await self._emit_event(
            session.session_id,
            "execution",
            "Building dynamic execution graph (LangGraph)…",
            phase="execution",
            progress=0.75,
        )

        with agbus_span("agbus.graph.build", attributes={"session_id": session.session_id}):
            plan = session.composition_plan

            # --- Initialise session memory with inferred policies ---
            memory_policies = self.negotiation.infer_memory_policies(plan)
            for mp in memory_policies:
                session.memory.set_policy(MemoryAccessPolicy(**mp))

            # Seed the memory with intent context so agents can read it
            session.memory.coordinator_write(
                "shared.intent_text",
                session.intent.intent_text if session.intent else "",
            )
            session.memory.coordinator_write(
                "shared.intent_context",
                session.intent.context if session.intent else {},
            )

            await self._emit_event(
                session.session_id,
                "memory",
                f"Session memory initialised with {len(memory_policies)} agent policy/ies",
                phase="execution",
                detail={"policies": memory_policies},
                progress=0.76,
            )

            graph = self.graph_builder.build(plan)
            compiled = graph.compile()

        steps = plan.get("steps", [])
        node_desc = " → ".join(s.get("agent_id", "?") for s in steps)
        await self._emit_event(
            session.session_id,
            "execution",
            f"Execution graph built with {len(steps)} node(s): {node_desc}",
            phase="execution",
            detail={"node_count": len(steps), "flow": node_desc},
            progress=0.80,
        )

        await self._emit_event(
            session.session_id,
            "execution",
            "Starting supervised execution with per-step IBAC validation…",
            phase="execution",
            progress=0.82,
        )

        with agbus_span("agbus.execution.run", attributes={"session_id": session.session_id}):
            complete_env = await self.supervisor.execute(session, compiled)

        complete_payload = complete_env.payload
        exec_status = complete_payload.get("status", "unknown")
        exec_metadata = complete_payload.get("metadata", {})

        # Surface agent metrics & output in events
        agent_metrics = exec_metadata.get("agent_metrics", [])
        output_text = exec_metadata.get("output", "")
        output_summary = exec_metadata.get("output_summary", "")

        if agent_metrics:
            await self._emit_event(
                session.session_id,
                "execution",
                "Agent quality scores: "
                + ", ".join(
                    f"{m['agent_id']}={m.get('quality_score', '?')}/10 ({m.get('latency_ms', 0):.0f}ms, {m.get('retries', 0)} retries)"
                    for m in agent_metrics
                ),
                phase="scoring",
                detail={"agent_metrics": agent_metrics},
                progress=0.92,
            )

        if output_text:
            await self._emit_event(
                session.session_id,
                "execution",
                f"Synthesised output: {output_summary or output_text[:200]}",
                phase="synthesis",
                detail={"output": output_text, "output_summary": output_summary},
                progress=0.95,
            )

        await self._emit_event(
            session.session_id,
            "execution",
            f"Execution finished with status: {exec_status}",
            phase="execution",
            detail=complete_payload,
            progress=0.97,
        )

        # Store results
        session.execution_results.append(complete_payload)
        session.audit_log.append(complete_env)

        # Update per-agent performance stats (score, latency, execution count)
        if agent_metrics:
            await self._update_agent_stats(agent_metrics)

        # ── Agent-based answer validation ──────────────────────────────
        # If an agent was assigned as validator, the output must be validated
        # before the session completes.  If validation fails, a renegotiation
        # loop is triggered with the rejection reason fed back as context.
        if session.assigned_agent_id and exec_status in ("success", "partial_failure"):
            validation_outcome = await self._run_validation_loop(session, complete_env)
            if validation_outcome is not None:
                # Validation triggered renegotiation or final rejection –
                # the session lifecycle is now managed by the validation
                # handler, so we return here.
                return

        # Send completion to requester
        requester_peer_id = self._session_requester_peers.get(session.session_id)
        if requester_peer_id:
            peer = self._server.get_peer(requester_peer_id)
            if peer:
                await peer.send_envelope(complete_env)

        # Mandatory dissolution (§16)
        await self._dissolve_session(session.session_id)

    # -----------------------------------------------------------------------
    # Agent-based answer validation
    # -----------------------------------------------------------------------

    async def _run_validation_loop(
        self,
        session: SessionState,
        complete_env: AgBusEnvelope,
    ) -> str | None:
        """Validate execution output using the assigned agent.

        Returns:
        - ``None`` if validation passed (caller should proceed normally).
        - ``"renegotiated"`` if a renegotiation cycle was triggered.
        - ``"rejected"`` if max validation rounds were exhausted.
        """
        assigned_id = session.assigned_agent_id
        if not assigned_id:
            return None

        # Extract the answer to validate
        metadata = complete_env.payload.get("metadata", {})
        output_text = metadata.get("output", "")
        step_results = complete_env.payload.get("artifacts", [{}])

        # Build the answer dict the validator will review
        answer_for_validation = {
            "output": output_text,
            "output_summary": metadata.get("output_summary", ""),
            "step_results": step_results[0] if step_results else {},
        }

        # Resolve the validator's validate_answer callable
        validate_fn = await self._resolve_validator(assigned_id)
        if validate_fn is None:
            logger.warning(
                "Assigned validator '%s' not available — skipping validation for session %s",
                assigned_id,
                session.session_id,
            )
            return None

        await self._emit_event(
            session.session_id,
            "validation",
            f"Validating execution output with assigned agent '{assigned_id}' "
            f"(round {session.validation_rounds + 1}/{session.max_validation_rounds})…",
            phase="validation",
            agent_id=assigned_id,
        )

        vr = await self.validation_engine.validate(
            session=session,
            answer=answer_for_validation,
            agent_validate_fn=validate_fn,
        )

        await self._emit_event(
            session.session_id,
            "validation",
            f"Validation {'APPROVED' if vr.approved else 'REJECTED'} by '{assigned_id}' "
            f"(round {vr.round_num}): {vr.reason}",
            phase="validation",
            agent_id=assigned_id,
            detail=vr.to_dict(),
        )

        if vr.approved:
            # Validation passed — let the normal completion flow proceed
            return None

        # Validation failed — check if we can renegotiate
        if session.validation_rounds >= session.max_validation_rounds:
            logger.warning(
                "Max validation rounds (%d) exhausted for session %s — rejecting",
                session.max_validation_rounds,
                session.session_id,
            )
            await self._emit_event(
                session.session_id,
                "validation",
                f"Max validation rounds ({session.max_validation_rounds}) exhausted — "
                f"rejecting session. Last rejection: {vr.reason}",
                phase="validation",
                agent_id=assigned_id,
            )

            # Send final rejection to requester
            reject_env = build_envelope(
                MessageType.REJECT,
                COORDINATOR_SENDER,
                session.session_id,
                RejectPayload(
                    reason=(
                        f"Answer rejected by validator '{assigned_id}' after "
                        f"{session.max_validation_rounds} rounds: {vr.reason}"
                    ),
                ),
                inject_trace_context(),
            )
            requester_peer_id = self._session_requester_peers.get(session.session_id)
            if requester_peer_id:
                peer = self._server.get_peer(requester_peer_id)
                if peer:
                    await peer.send_envelope(reject_env)
            await self._dissolve_session(session.session_id)
            return "rejected"

        # Trigger renegotiation with validation feedback
        await self._emit_event(
            session.session_id,
            "validation",
            f"Triggering renegotiation due to validation rejection (round {vr.round_num}): "
            f"{vr.reason} — suggestions: {vr.suggestions}",
            phase="validation",
            agent_id=assigned_id,
        )

        await self._validation_renegotiate(session, vr)
        return "renegotiated"

    async def _resolve_validator(self, agent_id: str) -> Any | None:
        """Resolve the ``validate_answer`` callable for the assigned agent.

        Checks:
        1. In-process validator registry (for managed agents running as tasks).
        2. ManagedAgent from DB (build a temporary validation instance).
        3. Falls back to ``None`` if the agent can't be found.

        For external agents connected via WebSocket, the validation is
        delegated over the wire (future extension).  Currently external
        agents use the default ``BaseAgent.validate_answer`` which approves
        everything — they should override it.
        """
        # 1. Check the validator registry (populated when managed agents start)
        if agent_id in self._validator_agents:
            agent_instance = self._validator_agents[agent_id]
            return agent_instance.validate_answer

        # 2. Try to build a validator from the managed agent DB record
        try:
            import asyncio
            ma = await asyncio.to_thread(self.managed_repo.get, agent_id)
            if ma is not None:
                server = ManagedAgentServer(ma)
                # Cache for future rounds
                self._validator_agents[agent_id] = server
                return server.validate_answer
        except Exception:
            logger.debug("Could not load managed agent %s for validation", agent_id)

        # 3. For connected external agents, check if they have a WS peer
        #    and use a WS-based validation call (simplified: call validate
        #    via a temporary BaseAgent wrapper)
        peer_id = self._agent_peers.get(agent_id)
        if peer_id:
            # External agents connected via WS — for now, use default
            # validation (approve).  External agents should implement
            # validate_answer in their own process.
            from agentic_bus.agents.base.agent import BaseAgent

            class _ExternalValidator(BaseAgent):
                def capabilities(self):
                    return []
                async def execute_task(self, p, c):
                    return {}

            validator = _ExternalValidator(agent_id=agent_id)
            return validator.validate_answer

        return None

    async def _validation_renegotiate(
        self,
        session: SessionState,
        vr: 'ValidationResult',
    ) -> None:
        """Reset session for a validation-triggered renegotiation cycle.

        Injects the validation rejection reason and suggestions into the
        intent context so agents can produce a better answer.
        """
        # Reset negotiation state
        session.offers.clear()
        session.accepted_offers.clear()
        session.solicited_agents.clear()
        session.execution_results.clear()

        # Preserve validation context and inject feedback
        if session.intent:
            session.intent.context["_validation_feedback"] = session.validation_history
            session.intent.context["_validation_rejection_reason"] = vr.reason
            session.intent.context["_validation_suggestions"] = vr.suggestions

        session.composition_plan = {
            "validation_renegotiation_round": session.validation_rounds,
            "validation_rejection_reason": vr.reason,
            "validation_suggestions": vr.suggestions,
        }

        self.sessions.transition(session.session_id, SessionPhase.DISCOVERY)
        logger.info(
            "Validation renegotiation (round %d) for session %s — re-running discovery",
            session.validation_rounds,
            session.session_id,
        )

        # Re-run discovery with enriched context
        candidates = await self.adjudicator.discover(session.intent)
        session.discovered_agents = [c.agent_id for c in candidates]

        if not candidates:
            logger.warning(
                "No agents found during validation renegotiation for session %s",
                session.session_id,
            )
            reject_env = build_envelope(
                MessageType.REJECT,
                COORDINATOR_SENDER,
                session.session_id,
                RejectPayload(
                    reason="No eligible agents found during validation renegotiation",
                ),
                inject_trace_context(),
            )
            requester_peer_id = self._session_requester_peers.get(session.session_id)
            if requester_peer_id:
                peer = self._server.get_peer(requester_peer_id)
                if peer:
                    await peer.send_envelope(reject_env)
            await self._dissolve_session(session.session_id)
            return

        self.sessions.transition(session.session_id, SessionPhase.NEGOTIATION)
        await self._request_offers(session, candidates)

    # -----------------------------------------------------------------------
    # Managed agent validation registration
    # -----------------------------------------------------------------------

    def register_validator(self, agent_id: str, agent_instance: Any) -> None:
        """Register a managed agent instance for in-process validation.

        Called when a managed agent server is started, so the coordinator
        can invoke ``validate_answer`` directly without WS round-trips.
        """
        self._validator_agents[agent_id] = agent_instance

    async def _update_agent_stats(self, agent_metrics: list[dict]) -> None:
        """Persist per-agent execution stats (score, latency, count).

        Tries the managed agent repo first, then the persistent agent repo.
        Runs in a thread to avoid blocking the event loop.
        """
        import asyncio

        for m in agent_metrics:
            agent_id = m.get("agent_id", "")
            score = m.get("quality_score", -1)
            latency = m.get("latency_ms", 0.0)
            if not agent_id or score < 0:
                continue

            try:
                # Try managed first (most common), then persistent
                managed = await asyncio.to_thread(self.managed_repo.get, agent_id)
                if managed is not None:
                    await asyncio.to_thread(
                        self.managed_repo.record_execution,
                        agent_id,
                        float(score),
                        float(latency),
                    )
                else:
                    await asyncio.to_thread(
                        self.agent_repo.record_execution,
                        agent_id,
                        float(score),
                        float(latency),
                    )
            except Exception:
                logger.debug(
                    "Failed to update stats for agent %s — non-critical",
                    agent_id,
                    exc_info=True,
                )

    # -----------------------------------------------------------------------
    # Completion & dissolution
    # -----------------------------------------------------------------------

    async def _handle_register(self, envelope: AgBusEnvelope, peer: Peer) -> None:
        """Handle the ``register`` performative (LIP 0.2.0)."""
        await self._handle_agent_registration(envelope, peer)

    async def _handle_complete(self, envelope: AgBusEnvelope, peer: Peer) -> None:
        """Handle a complete message from an agent.

        Deprecated special case: before LIP 0.2.0 agents registered by
        sending ``complete`` with ``session_id="__registration__"``. Still
        accepted so that agents built against 0.1.0 keep working, but the
        ``register`` performative is the specified way.
        """
        if envelope.session_id == "__registration__":
            logger.warning(
                "Agent %s registered using the pre-0.2.0 'complete' form. "
                "This still works but is deprecated — upgrade the agent to "
                "send the 'register' performative.",
                envelope.sender.id,
            )
            await self._handle_agent_registration(envelope, peer)
            return
        
        # Handle normal task completion
        session = self.sessions.get(envelope.session_id)
        if session:
            session.audit_log.append(envelope)
            session.execution_results.append(envelope.payload)

        # Resolve any pending execution future for this agent+session
        key = (envelope.session_id, envelope.sender.id)
        fut = self._pending_completions.pop(key, None)
        if fut and not fut.done():
            fut.set_result(envelope)

    def _resolve_scopes(self, registration: AgentRegistration) -> dict[str, list[str]]:
        """Decide what this agent actually holds, and record what it asked for.

        RFC 0003. The agent's declared ``required_scopes`` is a **request**;
        the grant comes from a binding an administrator authored. So this
        never returns a scope because an agent named it — the two lists are
        computed independently and only reported together.

        Three outcomes per declared name:

        *recognised* — the catalogue has it. Says nothing about whether this
        agent may hold it.

        *unrecognised* — recorded as a request, so an operator can see what
        agents are asking for. Previously this information was discarded.

        *catalogued* — development only: added on first sight, because a local
        bus should not need a catalogue authored before anything runs.
        """
        declared = list(registration.required_scopes or [])
        for capability in registration.capabilities:
            declared.extend(capability.required_scopes or [])

        try:
            catalogue = self.scope_repo.catalogue()
        except Exception:
            # A catalogue that cannot be read must not become an open door,
            # but it also must not break registration: report nothing granted.
            logger.exception("Could not read the scope catalogue")
            return {"granted": [], "unrecognised": [], "catalogue": []}

        decision = self._scopes.resolve(declared, catalogue)

        for scope in decision.catalogued:
            try:
                self.scope_repo.add_scope(
                    scope,
                    description=f"Added on first sight from {registration.agent_id!r}",
                    created_by="auto",
                )
                logger.warning(
                    "Scope %r was not catalogued and has been added automatically. "
                    "Set AGBUS_SCOPE_CATALOGUE_ENFORCED=true to refuse instead.",
                    scope,
                )
            except ValueError:
                pass

        for scope in decision.unrecognised:
            try:
                self.scope_repo.record_request(registration.agent_id, scope)
            except Exception:
                logger.exception("Could not record the scope request for %r", scope)

        # The grant. Note what is *not* consulted here: anything the agent
        # declared. An unbound capability holds nothing.
        granted: set[str] = set()
        for capability in registration.capabilities:
            try:
                granted.update(
                    self.scope_repo.granted(
                        registration.agent_id, capability.capability_id
                    )
                )
            except Exception:
                logger.exception(
                    "Could not read bindings for %s:%s",
                    registration.agent_id,
                    capability.capability_id,
                )

        if decision.unrecognised:
            logger.info(
                "Agent %s asked for uncatalogued scopes: %s",
                registration.agent_id,
                ", ".join(decision.unrecognised),
            )

        return {
            "granted": sorted(granted),
            "unrecognised": decision.unrecognised,
            # Only worth returning when the agent named something outside it;
            # otherwise it is noise on every successful registration.
            "catalogue": (
                self.scope_repo.catalogue() if decision.unrecognised else []
            ),
        }

    def _admit(
        self, registration: AgentRegistration, peer: Peer
    ) -> tuple[bool, str]:
        """Decide whether this agent may join the bus, and say why not.

        Three questions, in order of how cheaply they can be answered:

        1. Is the connection authenticated, when this deployment requires it?
        2. Has this ``agent_id`` been rejected or revoked by an administrator?
        3. Is the authenticated subject entitled to *this* ``agent_id``?

        Revocation is checked for ephemeral agents too, even though they keep
        no state of their own. An agent that an administrator revoked could
        otherwise return by reconnecting as ephemeral, which would make
        revocation a suggestion.
        """
        identity = getattr(peer, "identity", None)
        agent_id = registration.agent_id

        record = None
        try:
            record = self.agent_repo.get(agent_id)
        except Exception:
            # A registry lookup failure must not become an open door.
            logger.exception("Could not load the agent record for %s", agent_id)
            return False, "agent record could not be read"

        if record is not None and record.status in (
            AgentStatus.REJECTED,
            AgentStatus.REVOKED,
        ):
            return False, f"agent {agent_id!r} is {record.status.value}"

        if record is not None and registration.mode == "persistent":
            if record.status != AgentStatus.APPROVED:
                return False, (
                    f"agent {agent_id!r} is awaiting approval; "
                    "an administrator must approve the enrolment"
                )

        allowed, reason = self._auth.entitled_to_register(
            identity,
            agent_id,
            bound_subject=getattr(record, "oidc_subject", "") or "",
        )
        if not allowed:
            return False, reason

        # First authenticated registration binds the id to the subject, so a
        # second credential cannot later claim it. Only ever recorded, never
        # overwritten — rebinding is an administrative act, not something a
        # connection can do to itself.
        if record is not None and identity is not None and not record.oidc_subject:
            try:
                self.agent_repo.bind_subject(agent_id, identity.subject)
                logger.info(
                    "Agent %s is now bound to subject %s", agent_id, identity.subject
                )
            except Exception:
                logger.exception("Could not bind %s to a subject", agent_id)

        return True, ""

    async def _handle_agent_registration(self, envelope: AgBusEnvelope, peer: Peer) -> None:
        """Handle agent capability registration (§7 AGENTS.md).
        
        Agents register by sending a COMPLETE message with session_id="__registration__"
        and payload containing their AgentRegistration.
        """
        try:
            payload = envelope.payload
            # ``register`` carries the fields directly; the deprecated
            # ``complete`` form nested them under "registration".
            reg_data = payload.get("registration", payload)
            if not reg_data.get("agent_id"):
                logger.warning(
                    "Registration from %s carried no agent_id", envelope.sender.id
                )
                await self._send_registered(
                    peer, "", accepted=False, reason="registration payload has no agent_id"
                )
                return

            registration = AgentRegistration.model_validate(reg_data)

            # Admission control, before the registry hears about it. An agent
            # admitted first and vetted afterwards is discoverable in the
            # window between, which is the whole window that matters.
            admitted, reason = self._admit(registration, peer)
            if not admitted:
                logger.warning(
                    "Refused registration of %s: %s", registration.agent_id, reason
                )
                await self._send_registered(
                    peer, registration.agent_id, accepted=False, reason=reason
                )
                return

            self.register_agent(registration, peer.peer_id)

            logger.info(
                "✅ Agent registered: %s (version %s, mode=%s) with %d capabilities",
                registration.agent_id,
                registration.version,
                registration.mode,
                len(registration.capabilities),
            )

            scopes = self._resolve_scopes(registration)

            await self._send_registered(
                peer,
                registration.agent_id,
                accepted=True,
                capabilities=[c.capability_id for c in registration.capabilities],
                granted_scopes=scopes["granted"],
                unrecognised_scopes=scopes["unrecognised"],
                catalogue=scopes["catalogue"],
            )

        except Exception as e:
            logger.exception("Failed to register agent from %s: %s", envelope.sender.id, e)
            # The agent is waiting on an answer. Without one it would sit
            # connected and idle, believing it had registered.
            await self._send_registered(
                peer,
                envelope.sender.id,
                accepted=False,
                reason=f"registration failed: {e}",
            )

    async def _send_registered(
        self,
        peer: Peer,
        agent_id: str,
        *,
        accepted: bool,
        reason: str = "",
        capabilities: list[str] | None = None,
        granted_scopes: list[str] | None = None,
        unrecognised_scopes: list[str] | None = None,
        catalogue: list[str] | None = None,
    ) -> None:
        """Answer a registration attempt.

        Best-effort: if the socket has already gone, the agent will register
        again on its next connection anyway, so a failure here must not
        propagate into the registration path.
        """
        ack = build_envelope(
            MessageType.REGISTERED,
            COORDINATOR_SENDER,
            "",
            RegisteredPayload(
                accepted=accepted,
                agent_id=agent_id,
                reason=reason,
                registered_capabilities=capabilities or [],
                granted_scopes=granted_scopes or [],
                unrecognised_scopes=unrecognised_scopes or [],
                catalogue=catalogue or [],
                coordinator_protocol_version=LIP_PROTOCOL_VERSION,
            ),
            inject_trace_context(),
        )
        try:
            await peer.send_envelope(ack)
        except Exception:
            logger.warning(
                "Could not send 'registered' answer to %s", agent_id or "<unknown>"
            )

    async def _handle_accept(self, envelope: AgBusEnvelope, peer: Peer) -> None:
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

        # Validate the requester's payload before acting on it — a malformed
        # accept must not be treated as approval.  Nothing else is needed
        # from it, so the parsed value is deliberately discarded.
        AcceptPayload.model_validate(envelope.payload)

        # Acknowledge approval back to the requester
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

        await self._emit_event(
            session.session_id,
            "phase",
            "Requester approved the execution plan — preparing execution…",
            phase="approved",
            progress=0.72,
        )

        # Now proceed to execution
        await self._finalize_negotiation(session)

    async def _handle_reject(self, envelope: AgBusEnvelope, peer: Peer) -> None:
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
        peer: Peer,
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
        session.solicited_agents.clear()
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

            # --- Archive memory summary before destruction ---
            memory_summary = session.memory.audit_summary()

            if memory_summary["total_operations"] > 0:
                await self._emit_event(
                    session_id,
                    "memory",
                    f"Session memory dissolution: {memory_summary['writes']} write(s), "
                    f"{memory_summary['reads']} read(s), {memory_summary['denied']} denied "
                    f"across {len(memory_summary['keys_at_dissolution'])} key(s)",
                    phase="dissolution",
                    detail={"memory_summary": memory_summary},
                )

            # Destroy session memory (Invariant II: R_c(A,B) = 0)
            session.memory.clear()

            await self._emit_event(
                session_id,
                "phase",
                "Dissolving session — cleaning up all ephemeral state (Invariant II)",
                phase="dissolution",
                progress=1.0,
            )

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
                # Archive the session before it is garbage-collected
                await self._archive_session(final_snapshot)

                self.audit_log.log(
                    action="session.dissolved",
                    actor="coordinator",
                    target=session_id,
                    target_type="session",
                    details="Session completed and dissolved per Invariant II",
                    severity="info",
                )
                logger.info(
                    "Session %s dissolved. Audit trail: %d messages",
                    session_id,
                    len(final_snapshot.audit_log),
                )

    async def _archive_session(self, snapshot: SessionState) -> None:
        """Persist a read-only archive of a dissolved session.

        This runs in a thread to avoid blocking the event loop with DB I/O.
        Failures are logged but do not prevent dissolution.
        """
        import asyncio

        try:
            # Derive outcome from execution results
            outcome = "success"
            outcome_summary = ""
            if snapshot.execution_results:
                last = snapshot.execution_results[-1]
                outcome = last.get("status", "success")
                # Build a short summary from artifacts
                artifacts = last.get("artifacts", [])
                if artifacts:
                    outcome_summary = f"{len(artifacts)} artifact(s) produced"
            elif snapshot.phase == SessionPhase.DISSOLVED and not snapshot.accepted_offers:
                outcome = "cancelled"
                outcome_summary = "Session dissolved without execution"

            # Compute duration
            from datetime import datetime, timezone

            duration = 0.0
            try:
                t0 = datetime.fromisoformat(snapshot.created_at)
                t1 = datetime.fromisoformat(snapshot.dissolved_at) if snapshot.dissolved_at else datetime.now(timezone.utc)
                duration = (t1 - t0).total_seconds()
            except (ValueError, TypeError):
                pass

            # Extract intent text
            intent_text = ""
            intent_domain = ""
            decomposition: dict = {}
            if snapshot.intent:
                # IntentPayload carries the text as `intent_text`. Falling back
                # to str() puts the model's repr in the archive — which then
                # reaches the dashboard and the history API as the intent.
                intent_text = getattr(snapshot.intent, "intent_text", "") or getattr(
                    snapshot.intent, "text", ""
                )
                intent_domain = snapshot.intent.domain if hasattr(snapshot.intent, "domain") else ""
                if hasattr(snapshot.intent, "decomposition") and snapshot.intent.decomposition:
                    decomposition = snapshot.intent.decomposition if isinstance(snapshot.intent.decomposition, dict) else {}

            # Serialize the audit trail (list of AgBusEnvelope -> list of dicts)
            audit_trail = []
            for env in snapshot.audit_log:
                try:
                    audit_trail.append(env.model_dump(mode="json") if hasattr(env, "model_dump") else env)
                except Exception:
                    audit_trail.append(str(env))

            # Build timeline events from the audit trail envelopes
            # (The UI builds its own timeline from websocket events, but we
            # reconstruct a simplified version from the envelope stream.)
            timeline_events = []
            for env_data in audit_trail:
                if isinstance(env_data, dict):
                    payload = env_data.get("payload", {})
                    msg_type = env_data.get("message_type", "")
                    sender = env_data.get("sender", {})
                    timeline_events.append({
                        "id": env_data.get("message_id", ""),
                        "timestamp": env_data.get("timestamp", ""),
                        "category": payload.get("category", msg_type),
                        "phase": payload.get("phase", ""),
                        "summary": payload.get("summary", f"{msg_type} from {sender.get('id', '?')}"),
                        "detail": payload.get("detail"),
                        "agentId": payload.get("agent_id", sender.get("id", "")),
                        "progress": payload.get("progress"),
                    })

            # Build agents detail map from negotiation offers
            agents_map: dict = {}
            for offer_rec in snapshot.offers:
                try:
                    offer_data = (
                        offer_rec.offer.model_dump(mode="json")
                        if hasattr(offer_rec.offer, "model_dump")
                        else {}
                    )
                    agents_map[offer_rec.agent_id] = {
                        "status": offer_rec.status,
                        "capability_id": offer_data.get("capability_id", ""),
                        "capability_description": offer_data.get("capability_description", ""),
                        "estimated_cost": offer_data.get("estimated_cost"),
                        "estimated_latency": offer_data.get("estimated_latency"),
                    }
                except Exception:
                    agents_map[offer_rec.agent_id] = {"status": offer_rec.status}

            # Extract agent metrics and synthesised output from execution results
            agent_metrics: list[dict] = []
            output_text = ""
            output_summary_text = ""
            if snapshot.execution_results:
                last = snapshot.execution_results[-1]
                metadata = last.get("metadata", {})
                agent_metrics = metadata.get("agent_metrics", [])
                output_text = metadata.get("output", "")
                output_summary_text = metadata.get("output_summary", "")

            await asyncio.to_thread(
                self.archive_repo.archive_session,
                session_id=snapshot.session_id,
                requester_id=snapshot.requester_id,
                requester_oidc_subject=snapshot.requester_oidc_subject,
                intent_text=intent_text,
                intent_domain=intent_domain,
                decomposition=decomposition,
                outcome=outcome,
                outcome_summary=outcome_summary,
                discovered_agents=snapshot.discovered_agents,
                accepted_agents=snapshot.accepted_offers,
                agents=agents_map,
                composition_plan=snapshot.composition_plan,
                execution_results=snapshot.execution_results,
                timeline_events=timeline_events,
                audit_trail=audit_trail,
                ibac_decisions=snapshot.ibac_decisions,
                agent_metrics=agent_metrics,
                output=output_text,
                output_summary=output_summary_text,
                created_at=snapshot.created_at,
                dissolved_at=snapshot.dissolved_at,
                duration_seconds=duration,
            )
            logger.info("Session %s archived to database", snapshot.session_id)
        except Exception:
            logger.exception("Failed to archive session %s — dissolution proceeds", snapshot.session_id)

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

    async def _start_managed_agents(self) -> None:
        """Spawn all active managed agents as independent server tasks.

        Each managed agent runs a ``ManagedAgentServer`` in an asyncio task.
        The server connects back to the coordinator via WebSocket and
        registers its capabilities like any external agent.
        """
        active_agents = self.managed_repo.list_all(status=ManagedAgentStatus.ACTIVE)
        for ma in active_agents:
            await self.start_managed_agent(ma.agent_id)
        logger.info(
            "Spawned %d managed (active) agent server(s)",
            len(active_agents),
        )

    async def start_managed_agent(self, agent_id: str) -> bool:
        """Start a single managed agent as an independent server task.

        Returns ``True`` if the agent was started, ``False`` if it was
        already running or couldn't be found.
        """
        if agent_id in self._managed_tasks and not self._managed_tasks[agent_id].done():
            logger.info("Managed agent %s is already running", agent_id)
            return False

        ma = self.managed_repo.get(agent_id)
        if ma is None:
            logger.error("Managed agent %r not found in database", agent_id)
            return False

        uri = self._server.agent_endpoint
        if uri is None:
            # An in-process transport has no address to hand out, so a managed
            # agent has nowhere to dial. The host application attaches its own
            # agents instead; spawning one here would start a process that can
            # never connect.
            logger.warning(
                "Cannot start managed agent %r: the %s transport has no endpoint "
                "for an agent to dial. Attach agents in-process instead.",
                agent_id,
                self._server.description,
            )
            return False

        server = ManagedAgentServer(ma, coordinator_uri=uri)

        # Register as a validator so the coordinator can call validate_answer
        # in-process without a WS round-trip.
        self.register_validator(agent_id, server)

        async def _run_agent() -> None:
            max_retries = 5
            for attempt in range(1, max_retries + 1):
                try:
                    await server.run_forever()
                    return  # clean exit
                except asyncio.CancelledError:
                    logger.info("Managed agent %s task cancelled", agent_id)
                    return
                except ConnectionRefusedError:
                    if attempt < max_retries:
                        wait = attempt * 0.5
                        logger.warning(
                            "Managed agent %s connection refused (attempt %d/%d), "
                            "retrying in %.1fs…",
                            agent_id, attempt, max_retries, wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.exception(
                            "Managed agent %s failed after %d attempts",
                            agent_id, max_retries,
                        )
                except Exception:
                    logger.exception("Managed agent %s crashed", agent_id)
                    return

        task = asyncio.create_task(_run_agent(), name=f"managed-agent-{agent_id}")
        self._managed_tasks[agent_id] = task
        logger.info("Started managed agent %s as independent server task", agent_id)
        return True

    async def stop_managed_agent(self, agent_id: str) -> bool:
        """Stop a running managed agent task.

        Returns ``True`` if the agent was stopped.
        """
        task = self._managed_tasks.pop(agent_id, None)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Stopped managed agent %s", agent_id)
        return True

    async def _stop_all_managed_agents(self) -> None:
        """Stop all running managed agent tasks (called during shutdown)."""
        agent_ids = list(self._managed_tasks.keys())
        for agent_id in agent_ids:
            await self.stop_managed_agent(agent_id)

    # -----------------------------------------------------------------------
    # MCP bridge agent lifecycle
    # -----------------------------------------------------------------------

    async def _start_mcp_bridges(self) -> None:
        """Spawn bridge agents for all active MCP servers.

        Each MCP bridge connects to its external MCP server, discovers
        tools, then connects back to the coordinator via WebSocket and
        registers its capabilities like any other agent.
        """
        from agentic_bus.core.persistence.models import MCPServerStatus

        active = self.mcp_repo.list_all(status=MCPServerStatus.ACTIVE)
        for mcp in active:
            await self.start_mcp_bridge(mcp.server_id)
        logger.info(
            "Spawned %d MCP bridge agent(s)",
            len(active),
        )

    async def start_mcp_bridge(self, server_id: str) -> bool:
        """Start a single MCP bridge agent.

        Returns ``True`` if the bridge was started, ``False`` if it was
        already running or couldn't be found.
        """
        if server_id in self._mcp_bridge_tasks and not self._mcp_bridge_tasks[server_id].done():
            logger.info("MCP bridge %s is already running", server_id)
            return False

        mcp = self.mcp_repo.get(server_id)
        if mcp is None:
            logger.error("MCP server %r not found in database", server_id)
            return False

        from agentic_bus.agents.mcp_bridge import MCPBridgeAgent

        uri = self._server.agent_endpoint
        if uri is None:
            logger.warning(
                "Cannot start MCP bridge %r: the %s transport has no endpoint "
                "for an agent to dial.",
                server_id,
                self._server.description,
            )
            return False

        bridge = MCPBridgeAgent(mcp, coordinator_uri=uri)
        self._mcp_bridge_agents[server_id] = bridge

        async def _run_bridge() -> None:
            max_retries = 5
            for attempt in range(1, max_retries + 1):
                try:
                    await bridge.run_forever()
                    return
                except asyncio.CancelledError:
                    logger.info("MCP bridge %s task cancelled", server_id)
                    return
                except ConnectionRefusedError:
                    if attempt < max_retries:
                        wait = attempt * 0.5
                        logger.warning(
                            "MCP bridge %s connection refused (attempt %d/%d), "
                            "retrying in %.1fs…",
                            server_id, attempt, max_retries, wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.exception(
                            "MCP bridge %s failed after %d attempts",
                            server_id, max_retries,
                        )
                except Exception:
                    logger.exception("MCP bridge %s crashed", server_id)
                    return

        task = asyncio.create_task(_run_bridge(), name=f"mcp-bridge-{server_id}")
        self._mcp_bridge_tasks[server_id] = task
        logger.info("Started MCP bridge %s → agent %s", server_id, mcp.agent_id)
        return True

    async def stop_mcp_bridge(self, server_id: str) -> bool:
        """Stop a running MCP bridge agent.

        Returns ``True`` if the bridge was stopped.
        """
        self._mcp_bridge_agents.pop(server_id, None)
        task = self._mcp_bridge_tasks.pop(server_id, None)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Stopped MCP bridge %s", server_id)
        return True

    async def _stop_all_mcp_bridges(self) -> None:
        """Stop all running MCP bridge tasks (called during shutdown)."""
        server_ids = list(self._mcp_bridge_tasks.keys())
        for server_id in server_ids:
            await self.stop_mcp_bridge(server_id)

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

        self.audit_log.log(
            action="agent.disconnected",
            actor=agent_id,
            target=agent_id,
            target_type="agent",
            details="WebSocket disconnect",
            severity="info",
        )

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

        self.audit_log.log(
            action="agent.connected",
            actor=registration.agent_id,
            target=registration.agent_id,
            target_type="agent",
            details=f"Agent registered (mode={registration.mode}, v{registration.version})",
            severity="info",
        )

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
        runtime = self  # capture reference for event emission

        async def _executor(state: AgBusGraphState) -> AgBusGraphState:
            session_id = state.get("session_id", "")
            step_index = state.get("_current_step_index")

            await runtime._emit_event(
                session_id,
                "execution",
                f"Dispatching task to agent '{agent_id}'…",
                phase="execution",
                agent_id=agent_id,
                step_index=step_index,
            )

            # --- Execution guard -------------------------------------
            # The capability issued when execution was authorised is checked
            # before *every* dispatch, not once at the start. A multi-step
            # flow can outlive the approval that started it, and a plan can
            # name an agent the approval never covered.
            session_for_guard = runtime.sessions.get(session_id)
            capability = getattr(session_for_guard, "capability", None)
            if capability is not None:
                violation = capability.check(principal=agent_id)
                if violation is not None:
                    await runtime._emit_event(
                        session_id,
                        "ibac",
                        f"Execution refused for '{agent_id}': {violation.reason}",
                        phase="execution",
                        agent_id=agent_id,
                        step_index=step_index,
                        detail={"capability_id": violation.capability_id},
                    )
                    raise PermissionError(
                        f"capability check failed for {agent_id}: {violation.reason}"
                    )

            peer_id = runtime._agent_peers.get(agent_id)
            if not peer_id:
                raise RuntimeError(f"Agent {agent_id} not connected")

            peer = runtime._server.get_peer(peer_id)
            if not peer:
                raise RuntimeError(f"Peer {peer_id} not found for agent {agent_id}")

            # --- Build filtered memory snapshot for this agent ---
            memory_snapshot: dict[str, Any] = {}
            session = runtime.sessions.get(session_id)
            if session:
                memory_snapshot = session.memory.snapshot_for_agent(agent_id)

            # Send execute message to agent
            execute_env = build_envelope(
                MessageType.EXECUTE,
                COORDINATOR_SENDER,
                session_id,
                {
                    "execution_plan": {
                        "intent_text": state.get("intent_text", ""),
                        "context": state.get("context", {}),
                        "prior_results": state.get("step_results", {}),
                    },
                    # Carried from the capability rather than left empty, so
                    # the agent is told what it was actually authorised for.
                    "authorized_scopes": (
                        capability.scopes if capability is not None else []
                    ),
                    "capability_id": (
                        capability.capability_id if capability is not None else ""
                    ),
                    "memory_snapshot": memory_snapshot,
                },
                inject_trace_context(),
            )
            # Register a Future that _handle_complete will resolve
            key = (session_id, agent_id)
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[AgBusEnvelope] = loop.create_future()
            runtime._pending_completions[key] = fut

            await peer.send_envelope(execute_env)

            if memory_snapshot:
                await runtime._emit_event(
                    session_id,
                    "memory",
                    f"Injected {len(memory_snapshot)} memory key(s) into '{agent_id}' execution payload",
                    phase="execution",
                    agent_id=agent_id,
                    step_index=step_index,
                    detail={"keys": list(memory_snapshot.keys())},
                )

            await runtime._emit_event(
                session_id,
                "execution",
                f"Waiting for agent '{agent_id}' to complete…",
                phase="execution",
                agent_id=agent_id,
                step_index=step_index,
            )

            # Wait for the agent's COMPLETE routed through the main message loop
            try:
                response = await asyncio.wait_for(fut, timeout=120.0)

                response_status = response.payload.get("status", "unknown")

                # --- Apply memory writes from the agent's response ---
                raw_writes = response.payload.get("memory_writes", {})
                if raw_writes and session:
                    write_requests = [
                        MemoryWriteRequest(key=k, value=v)
                        for k, v in raw_writes.items()
                    ]
                    write_results = session.memory.write_batch(write_requests, agent_id)
                    accepted = sum(write_results)
                    denied = len(write_results) - accepted

                    await runtime._emit_event(
                        session_id,
                        "memory",
                        f"Agent '{agent_id}' memory writes: {accepted} accepted, {denied} denied",
                        phase="execution",
                        agent_id=agent_id,
                        step_index=step_index,
                        detail={
                            "accepted_keys": [
                                w.key
                                for w, ok in zip(write_requests, write_results)
                                if ok
                            ],
                            "denied_keys": [
                                w.key
                                for w, ok in zip(write_requests, write_results)
                                if not ok
                            ],
                        },
                    )

                await runtime._emit_event(
                    session_id,
                    "execution",
                    f"Agent '{agent_id}' completed with status: {response_status}",
                    phase="execution",
                    agent_id=agent_id,
                    step_index=step_index,
                    detail={"status": response_status},
                )

                results = dict(state.get("step_results", {}))
                results[agent_id] = response.payload
                return {**state, "step_results": results}
            except asyncio.TimeoutError as exc:
                runtime._pending_completions.pop(key, None)
                await runtime._emit_event(
                    session_id,
                    "error",
                    f"Agent '{agent_id}' timed out during execution (120s)",
                    phase="execution",
                    agent_id=agent_id,
                    step_index=step_index,
                )
                raise RuntimeError(f"Agent {agent_id} timed out during execution") from exc

        return _executor


