"""Admin REST API – FastAPI application for the Agentic Bus dashboard.

All mutating endpoints require admin privileges.  When OIDC is enabled
(``AGBUS_OIDC_ISSUER`` is set), a valid Bearer token with an admin role
is required.  In dev mode the ``DevVerifier`` is used and a default admin
identity is synthesised when no token is provided.

Read-only endpoints still extract the identity (so we know *who* is
reading) but do not require admin privileges.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from app.coordinator.admin.audit import AuditLog
from app.coordinator.admin.schemas import (
    AuditLogEntryDTO,
    CoordinatorSettingsDTO,
    CurrentUserDTO,
    DashboardStatsDTO,
    EphemeralAgentDTO,
    IBACRuleCreateRequest,
    IBACRuleDTO,
    IBACRuleUpdateRequest,
    LLMConfigCreateRequest,
    LLMConfigDTO,
    LLMConfigUpdateRequest,
    MCPServerCreateRequest,
    MCPServerDTO,
    MCPServerUpdateRequest,
    ManagedAgentCreateRequest,
    ManagedAgentDTO,
    PersistentAgentDTO,
    SessionArchiveDetailDTO,
    SessionArchiveListDTO,
    SessionDTO,
    TenantCreateRequest,
    TenantDTO,
    TenantUpdateRequest,
    UserCreateRequest,
    UserDTO,
    UserUpdateRequest,
)
from app.coordinator.admin.serializers import (
    ibac_rule_to_dto,
    llm_config_to_dto,
    managed_agent_to_dto,
    mcp_server_to_dto,
    persistent_agent_to_dto,
    registration_to_ephemeral_dto,
    session_archive_to_detail_dto,
    session_archive_to_list_dto,
    session_to_dto,
    tenant_to_dto,
    user_to_dto,
)
from app.core.auth.admin import AdminPolicy
from app.core.auth.oidc import DevVerifier, OIDCIdentity, OIDCVerifier
from app.core.persistence.models import MCPServerStatus, ManagedAgentStatus, UserRole
from app.core.protocol.envelope import LIP_PROTOCOL_VERSION

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

_oidc_verifier: OIDCVerifier | None = None
_dev_verifier = DevVerifier()


def _get_verifier() -> OIDCVerifier | DevVerifier:
    global _oidc_verifier
    issuer = os.getenv("AGBUS_OIDC_ISSUER", "")
    if issuer:
        if _oidc_verifier is None:
            _oidc_verifier = OIDCVerifier()
        return _oidc_verifier
    return _dev_verifier


async def _get_identity(authorization: str | None = Header(None)) -> OIDCIdentity:
    """Extract and verify identity from the Authorization header."""
    issuer = os.getenv("AGBUS_OIDC_ISSUER", "")

    if issuer:
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization header required")
        token = authorization.removeprefix("Bearer ").strip()
        verifier = _get_verifier()
        try:
            return await verifier.verify(token)
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Token verification failed: {exc}")

    # Dev mode – accept any token or synthesise a default admin identity
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        return await _dev_verifier.verify(token)
    return OIDCIdentity(
        subject="dev-admin",
        issuer="dev",
        audience="agbus",
        scopes=[],
        custom_claims={"roles": ["agbus:admin"]},
    )


async def _require_admin(
    identity: OIDCIdentity = Depends(_get_identity),
) -> OIDCIdentity:
    """Ensure the caller has admin privileges."""
    policy = AdminPolicy.from_env()
    if not policy.is_admin(identity):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return identity


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_admin_api(runtime: Any) -> FastAPI:
    """Build and return the FastAPI application wired to *runtime*.

    Parameters
    ----------
    runtime : CoordinatorRuntime
        The live coordinator runtime instance.  Stored in ``app.state``
        so route handlers can access all subsystems.
    """
    app = FastAPI(
        title="Agentic Bus Admin API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.runtime = runtime

    # Ensure an audit log exists on the runtime
    if not hasattr(runtime, "audit_log"):
        runtime.audit_log = AuditLog()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Helper to run synchronous repository calls off the event loop
    # ------------------------------------------------------------------

    async def _run_sync(fn, *args, **kwargs):
        """Run a synchronous function in a thread to avoid blocking."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _rt(request: Request):
        return request.app.state.runtime

    # ------------------------------------------------------------------
    # Liveness
    # ------------------------------------------------------------------

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Unauthenticated liveness probe.

        Deliberately outside ``/api/admin`` and free of auth so container
        orchestrators can call it without credentials, and deliberately
        cheap — it reports that the API is serving, not that every
        subsystem is healthy. It touches no database and no LLM, because a
        probe that depends on those turns a slow dependency into a restart
        loop.
        """
        return {
            "status": "ok",
            "protocol_version": LIP_PROTOCOL_VERSION,
        }

    # ------------------------------------------------------------------
    # Tenant-scoping helpers
    # ------------------------------------------------------------------

    async def _resolve_user(
        identity: OIDCIdentity,
        request: Request,
    ) -> tuple[bool, list[int]]:
        """Return ``(is_admin, tenant_ids)`` for the authenticated caller.

        Admins (as determined by ``AdminPolicy``) see everything.
        Regular users see only the agents belonging to their tenants.
        If the user doesn't exist in the DB yet (e.g. dev mode) we treat
        them as admin when the policy says so, otherwise empty tenants.
        """
        policy = AdminPolicy.from_env()
        is_admin = policy.is_admin(identity)
        if is_admin:
            return True, []

        rt = _rt(request)
        user = await _run_sync(rt.user_repo.get_by_subject, identity.subject)
        if user is None:
            return False, []
        tenant_ids = await _run_sync(rt.user_repo.get_user_tenant_ids, user.id)
        return False, tenant_ids

    async def _visible_agent_ids(
        is_admin: bool,
        tenant_ids: list[int],
        request: Request,
    ) -> set[str] | None:
        """Return the set of agent IDs visible to the caller.

        Returns ``None`` if the caller is admin (no filtering needed).
        """
        if is_admin:
            return None
        rt = _rt(request)
        ids: set[str] = set()
        for tid in tenant_ids:
            agent_ids = await _run_sync(rt.tenant_repo.get_tenant_agent_ids, tid)
            ids.update(agent_ids)
        return ids

    # ==================================================================
    # Dashboard
    # ==================================================================

    @app.get("/api/admin/stats", response_model=DashboardStatsDTO)
    async def get_dashboard_stats(
        request: Request,
        identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        is_admin, tenant_ids = await _resolve_user(identity, request)
        visible = await _visible_agent_ids(is_admin, tenant_ids, request)

        persistent = await _run_sync(rt.admin.list_agents)
        managed = await _run_sync(rt.managed_repo.list_all)
        mcp_servers = await _run_sync(rt.mcp_repo.list_all)
        ephemeral = [
            r for r in rt.registry.all_agents() if r.mode == "ephemeral"
        ]

        if visible is not None:
            persistent = [a for a in persistent if a.agent_id in visible]
            managed = [a for a in managed if a.agent_id in visible]
            mcp_servers = [m for m in mcp_servers if m.agent_id in visible]
            ephemeral = [e for e in ephemeral if e.agent_id in visible]

        approved = [a for a in persistent if a.status.value == "approved"]
        pending = [a for a in persistent if a.status.value == "pending"]

        sessions = rt.sessions.active_sessions()

        # Current LLM
        current_llm = await _run_sync(rt.admin.get_current_llm_config)
        llm_provider = current_llm.provider if current_llm else "—"
        llm_model = current_llm.model if current_llm else "—"

        # Count today's sessions from audit log
        today = datetime.now(timezone.utc).date()
        today_sessions = 0
        for entry in rt.audit_log.list_all():
            if entry.action == "session.created":
                try:
                    ts = datetime.fromisoformat(entry.timestamp)
                    if ts.date() == today:
                        today_sessions += 1
                except ValueError:
                    pass

        return DashboardStatsDTO(
            total_agents=len(persistent) + len(managed) + len(ephemeral) + len(mcp_servers),
            approved_agents=len(approved),
            pending_agents=len(pending),
            managed_agents=len(managed),
            ephemeral_agents=len(ephemeral),
            mcp_servers=len(mcp_servers),
            active_sessions=len(sessions),
            total_sessions_today=today_sessions,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )

    # ==================================================================
    # Persistent Agents
    # ==================================================================

    @app.get("/api/admin/agents/persistent", response_model=list[PersistentAgentDTO])
    async def list_persistent_agents(
        request: Request,
        status: str | None = Query(None),
        identity: OIDCIdentity = Depends(_get_identity),
    ):
        from app.core.persistence.models import AgentStatus

        rt = _rt(request)
        is_admin, tenant_ids = await _resolve_user(identity, request)
        visible = await _visible_agent_ids(is_admin, tenant_ids, request)

        status_enum = None
        if status:
            try:
                status_enum = AgentStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        agents = await _run_sync(rt.admin.list_agents, status_enum)
        if visible is not None:
            agents = [a for a in agents if a.agent_id in visible]
        return [persistent_agent_to_dto(a) for a in agents]

    @app.get("/api/admin/agents/persistent/{agent_id}", response_model=PersistentAgentDTO)
    async def get_persistent_agent(
        request: Request,
        agent_id: str,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        agent = await _run_sync(rt.admin.get_agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id!r} not found")
        return persistent_agent_to_dto(agent)

    @app.post("/api/admin/agents/persistent/{agent_id}/approve", response_model=PersistentAgentDTO)
    async def approve_agent(
        request: Request,
        agent_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            agent = await _run_sync(rt.admin.approve_agent, agent_id, identity)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        rt.audit_log.log(
            action="agent.approved",
            actor=identity.subject,
            target=agent_id,
            target_type="agent",
            details="Agent approved after admin review",
            severity="info",
        )
        return persistent_agent_to_dto(agent)

    @app.post("/api/admin/agents/persistent/{agent_id}/reject", response_model=PersistentAgentDTO)
    async def reject_agent(
        request: Request,
        agent_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            agent = await _run_sync(rt.admin.reject_agent, agent_id, identity)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        rt.audit_log.log(
            action="agent.rejected",
            actor=identity.subject,
            target=agent_id,
            target_type="agent",
            details="Agent enrolment rejected by admin",
            severity="warning",
        )
        return persistent_agent_to_dto(agent)

    @app.post("/api/admin/agents/persistent/{agent_id}/revoke", response_model=PersistentAgentDTO)
    async def revoke_agent(
        request: Request,
        agent_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            agent = await _run_sync(rt.admin.revoke_agent, agent_id, identity)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        rt.audit_log.log(
            action="agent.revoked",
            actor=identity.subject,
            target=agent_id,
            target_type="agent",
            details="Agent revoked by admin",
            severity="warning",
        )
        return persistent_agent_to_dto(agent)

    @app.delete("/api/admin/agents/persistent/{agent_id}")
    async def delete_persistent_agent(
        request: Request,
        agent_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            deleted = await _run_sync(rt.admin.delete_agent, agent_id, identity)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id!r} not found")
        rt.audit_log.log(
            action="agent.deleted",
            actor=identity.subject,
            target=agent_id,
            target_type="agent",
            details="Agent permanently deleted",
            severity="warning",
        )
        return {"ok": True}

    # ==================================================================
    # Managed Agents
    # ==================================================================

    @app.get("/api/admin/agents/managed", response_model=list[ManagedAgentDTO])
    async def list_managed_agents(
        request: Request,
        status: str | None = Query(None),
        identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        is_admin, tenant_ids = await _resolve_user(identity, request)
        visible = await _visible_agent_ids(is_admin, tenant_ids, request)

        status_enum = None
        if status:
            try:
                status_enum = ManagedAgentStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        agents = await _run_sync(rt.managed_repo.list_all, status_enum)
        if visible is not None:
            agents = [a for a in agents if a.agent_id in visible]
        return [managed_agent_to_dto(a) for a in agents]

    @app.get("/api/admin/agents/managed/{agent_id}", response_model=ManagedAgentDTO)
    async def get_managed_agent(
        request: Request,
        agent_id: str,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        agent = await _run_sync(rt.managed_repo.get, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Managed agent {agent_id!r} not found")
        return managed_agent_to_dto(agent)

    @app.post("/api/admin/agents/managed/{agent_id}/activate", response_model=ManagedAgentDTO)
    async def activate_managed_agent(
        request: Request,
        agent_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            agent = await _run_sync(
                rt.managed_repo.set_status, agent_id, ManagedAgentStatus.ACTIVE
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # Start the managed agent as an independent server task
        await rt.start_managed_agent(agent_id)
        rt.audit_log.log(
            action="agent.activated",
            actor=identity.subject,
            target=agent_id,
            target_type="agent",
            details="Managed agent activated and server started",
            severity="info",
        )
        return managed_agent_to_dto(agent)

    @app.post("/api/admin/agents/managed/{agent_id}/disable", response_model=ManagedAgentDTO)
    async def disable_managed_agent(
        request: Request,
        agent_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        # Stop the managed agent server task before disabling
        await rt.stop_managed_agent(agent_id)
        try:
            agent = await _run_sync(
                rt.managed_repo.set_status, agent_id, ManagedAgentStatus.DISABLED
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        rt.audit_log.log(
            action="agent.disabled",
            actor=identity.subject,
            target=agent_id,
            target_type="agent",
            details="Managed agent disabled and server stopped",
            severity="warning",
        )
        return managed_agent_to_dto(agent)

    @app.post("/api/admin/agents/managed", response_model=ManagedAgentDTO, status_code=201)
    async def create_managed_agent(
        request: Request,
        body: ManagedAgentCreateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        status = (
            ManagedAgentStatus.ACTIVE if body.activate
            else ManagedAgentStatus.DRAFT
        )
        capabilities = [
            {
                "capability_id": c.capability_id,
                "description": c.description,
                "expected_output": c.expected_output,
                "supported_data_domains": c.supported_data_domains,
                "estimated_cost": c.estimated_cost,
                "estimated_latency": c.estimated_latency,
                "output_fields": [f.model_dump() for f in c.output_fields],
            }
            for c in body.capabilities
        ]
        try:
            agent = await _run_sync(
                rt.managed_repo.create,
                agent_id=body.agent_id,
                name=body.name,
                role=body.role,
                goal=body.goal,
                backstory=body.backstory,
                llm_config_name=body.llm_config_name,
                verbose=body.verbose,
                max_iter=body.max_iter,
                max_rpm=body.max_rpm,
                memory=body.memory,
                tools=body.tools,
                tool_config=body.tool_config or {},
                capabilities=capabilities,
                status=status,
                created_by=identity.subject,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        # If created as active, start the managed agent server task immediately
        if status == ManagedAgentStatus.ACTIVE:
            await rt.start_managed_agent(body.agent_id)
        rt.audit_log.log(
            action="agent.created",
            actor=identity.subject,
            target=body.agent_id,
            target_type="agent",
            details=f"Managed agent created (status={status.value})",
            severity="info",
        )
        return managed_agent_to_dto(agent)

    @app.delete("/api/admin/agents/managed/{agent_id}")
    async def delete_managed_agent(
        request: Request,
        agent_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        # Stop the agent server task if it is running
        await rt.stop_managed_agent(agent_id)
        deleted = await _run_sync(rt.managed_repo.delete, agent_id)
        if not deleted:
            raise HTTPException(
                status_code=404, detail=f"Managed agent {agent_id!r} not found"
            )
        rt.audit_log.log(
            action="agent.deleted",
            actor=identity.subject,
            target=agent_id,
            target_type="agent",
            details="Managed agent permanently deleted",
            severity="warning",
        )
        return {"ok": True}

    @app.get("/api/admin/agents/tools")
    async def list_available_tools(
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        from app.agents.factory import list_available_tools as _list_tools
        from app.agents.factory import CREWAI_TOOL_DESCRIPTIONS, CREWAI_TOOL_REQUIREMENTS

        tools = _list_tools()
        return [
            {
                "name": t,
                "description": CREWAI_TOOL_DESCRIPTIONS.get(t, ""),
                "requirements": CREWAI_TOOL_REQUIREMENTS.get(t, []),
            }
            for t in tools
        ]

    # ==================================================================
    # Ephemeral Agents
    # ==================================================================

    @app.get("/api/admin/agents/ephemeral", response_model=list[EphemeralAgentDTO])
    async def list_ephemeral_agents(
        request: Request,
        identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        is_admin, tenant_ids = await _resolve_user(identity, request)
        visible = await _visible_agent_ids(is_admin, tenant_ids, request)

        ephemerals = [
            r for r in rt.registry.all_agents() if r.mode == "ephemeral"
        ]
        if visible is not None:
            ephemerals = [e for e in ephemerals if e.agent_id in visible]
        return [registration_to_ephemeral_dto(r) for r in ephemerals]

    # ==================================================================
    # MCP Server Bridges
    # ==================================================================

    def _enrich_mcp_dto(rt, mcp) -> MCPServerDTO:
        """Build an MCPServerDTO with live runtime info."""
        agent_id = mcp.agent_id
        is_connected = agent_id in rt._agent_peers
        discovered: list[str] = []
        task = rt._mcp_bridge_tasks.get(mcp.server_id)
        if task and not task.done():
            # Try to get discovered tools from the bridge agent
            bridge = rt._mcp_bridge_agents.get(mcp.server_id)
            if bridge is not None:
                discovered = list(bridge._tool_names)
        return mcp_server_to_dto(
            mcp,
            is_connected=is_connected,
            discovered_tools=discovered,
        )

    @app.get("/api/admin/agents/mcp", response_model=list[MCPServerDTO])
    async def list_mcp_servers(
        request: Request,
        identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        is_admin, tenant_ids = await _resolve_user(identity, request)
        visible = await _visible_agent_ids(is_admin, tenant_ids, request)

        servers = await _run_sync(rt.mcp_repo.list_all)
        if visible is not None:
            servers = [s for s in servers if s.agent_id in visible]
        return [_enrich_mcp_dto(rt, s) for s in servers]

    @app.get("/api/admin/agents/mcp/{server_id}", response_model=MCPServerDTO)
    async def get_mcp_server(
        request: Request,
        server_id: str,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        mcp = await _run_sync(rt.mcp_repo.get, server_id)
        if mcp is None:
            raise HTTPException(status_code=404, detail=f"MCP server {server_id!r} not found")
        return _enrich_mcp_dto(rt, mcp)

    @app.post("/api/admin/agents/mcp", response_model=MCPServerDTO, status_code=201)
    async def create_mcp_server(
        request: Request,
        body: MCPServerCreateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        status = (
            MCPServerStatus.ACTIVE if body.activate
            else MCPServerStatus.DISABLED
        )
        tool_overrides_raw = {
            name: ovr.model_dump() for name, ovr in body.tool_overrides.items()
        }
        try:
            mcp = await _run_sync(
                rt.mcp_repo.create,
                server_id=body.server_id,
                server_url=body.server_url,
                agent_id=body.agent_id,
                transport=body.transport,
                auth_headers=body.auth_headers,
                command=body.command,
                args=body.args,
                env=body.env,
                semantic_description=body.semantic_description,
                mode=body.mode,
                tool_overrides=tool_overrides_raw,
                status=status,
                created_by=identity.subject,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

        # If created as active, start the bridge immediately
        if status == MCPServerStatus.ACTIVE:
            await rt.start_mcp_bridge(body.server_id)

        rt.audit_log.log(
            action="mcp.server_created",
            actor=identity.subject,
            target=body.server_id,
            target_type="mcp_server",
            details=f"MCP server bridge created → agent {body.agent_id} (status={status.value})",
            severity="info",
        )
        return _enrich_mcp_dto(rt, mcp)

    @app.patch("/api/admin/agents/mcp/{server_id}", response_model=MCPServerDTO)
    async def update_mcp_server(
        request: Request,
        server_id: str,
        body: MCPServerUpdateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        updates: dict = {}
        for field in (
            "server_url", "transport", "auth_headers", "command",
            "args", "env", "semantic_description", "mode",
        ):
            val = getattr(body, field, None)
            if val is not None:
                updates[field] = val
        if body.tool_overrides is not None:
            updates["tool_overrides"] = {
                name: ovr.model_dump() for name, ovr in body.tool_overrides.items()
            }
        try:
            mcp = await _run_sync(rt.mcp_repo.update, server_id, **updates)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        rt.audit_log.log(
            action="mcp.server_updated",
            actor=identity.subject,
            target=server_id,
            target_type="mcp_server",
            details=f"MCP server bridge updated (fields: {list(updates.keys())})",
            severity="info",
        )
        return _enrich_mcp_dto(rt, mcp)

    @app.post("/api/admin/agents/mcp/{server_id}/activate", response_model=MCPServerDTO)
    async def activate_mcp_server(
        request: Request,
        server_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            mcp = await _run_sync(
                rt.mcp_repo.set_status, server_id, MCPServerStatus.ACTIVE
            )
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        await rt.start_mcp_bridge(server_id)
        rt.audit_log.log(
            action="mcp.server_activated",
            actor=identity.subject,
            target=server_id,
            target_type="mcp_server",
            details="MCP server bridge activated and started",
            severity="info",
        )
        return _enrich_mcp_dto(rt, mcp)

    @app.post("/api/admin/agents/mcp/{server_id}/disable", response_model=MCPServerDTO)
    async def disable_mcp_server(
        request: Request,
        server_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        await rt.stop_mcp_bridge(server_id)
        try:
            mcp = await _run_sync(
                rt.mcp_repo.set_status, server_id, MCPServerStatus.DISABLED
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        rt.audit_log.log(
            action="mcp.server_disabled",
            actor=identity.subject,
            target=server_id,
            target_type="mcp_server",
            details="MCP server bridge disabled and stopped",
            severity="warning",
        )
        return _enrich_mcp_dto(rt, mcp)

    @app.post("/api/admin/agents/mcp/{server_id}/rediscover")
    async def rediscover_mcp_tools(
        request: Request,
        server_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        bridge = rt._mcp_bridge_agents.get(server_id)
        if bridge is None:
            raise HTTPException(
                status_code=400,
                detail=f"MCP bridge {server_id!r} is not running",
            )
        try:
            new_tools = await bridge.rediscover_tools()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        rt.audit_log.log(
            action="mcp.tools_rediscovered",
            actor=identity.subject,
            target=server_id,
            target_type="mcp_server",
            details=f"Rediscovered {len(new_tools)} tool(s)",
            severity="info",
        )
        return {"server_id": server_id, "tools": new_tools}

    @app.delete("/api/admin/agents/mcp/{server_id}")
    async def delete_mcp_server(
        request: Request,
        server_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        await rt.stop_mcp_bridge(server_id)
        deleted = await _run_sync(rt.mcp_repo.delete, server_id)
        if not deleted:
            raise HTTPException(
                status_code=404, detail=f"MCP server {server_id!r} not found"
            )
        rt.audit_log.log(
            action="mcp.server_deleted",
            actor=identity.subject,
            target=server_id,
            target_type="mcp_server",
            details="MCP server bridge permanently deleted",
            severity="warning",
        )
        return {"ok": True}

    # ==================================================================
    # Sessions
    # ==================================================================

    @app.get("/api/admin/sessions", response_model=list[SessionDTO])
    async def list_sessions(
        request: Request,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        sessions = rt.sessions.active_sessions()
        return [session_to_dto(s) for s in sessions]

    # ==================================================================
    # Audit Log
    # ==================================================================

    @app.get("/api/admin/audit", response_model=list[AuditLogEntryDTO])
    async def list_audit_log(
        request: Request,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        entries = rt.audit_log.list_all()
        return [
            AuditLogEntryDTO(
                id=e.id,
                timestamp=e.timestamp,
                action=e.action,
                actor=e.actor,
                target=e.target,
                target_type=e.target_type,
                details=e.details,
                severity=e.severity,
            )
            for e in entries
        ]

    # ==================================================================
    # LLM Configurations
    # ==================================================================

    @app.get("/api/admin/llm/configs", response_model=list[LLMConfigDTO])
    async def list_llm_configs(
        request: Request,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        configs = await _run_sync(rt.admin.list_llm_configs)
        return [llm_config_to_dto(c) for c in configs]

    @app.post("/api/admin/llm/configs", response_model=LLMConfigDTO)
    async def add_llm_config(
        request: Request,
        body: LLMConfigCreateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            config = await _run_sync(
                rt.admin.add_llm_config,
                body.name,
                body.provider,
                body.model,
                identity,
                temperature=body.temperature,
                api_key=body.api_key,
                extra_config=body.extra_config,
                is_current=body.is_current,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        rt.audit_log.log(
            action="llm.config_added",
            actor=identity.subject,
            target=body.name,
            target_type="llm_config",
            details=f"LLM config added: {body.provider}/{body.model}",
            severity="info",
        )
        return llm_config_to_dto(config)

    @app.post("/api/admin/llm/configs/{name}/activate", response_model=LLMConfigDTO)
    async def activate_llm_config(
        request: Request,
        name: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            config = await _run_sync(rt.admin.activate_llm_config, name, identity)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        rt.audit_log.log(
            action="llm.config_activated",
            actor=identity.subject,
            target=name,
            target_type="llm_config",
            details=f"Switched active LLM to {name} ({config.provider}/{config.model})",
            severity="info",
        )
        return llm_config_to_dto(config)

    @app.put("/api/admin/llm/configs/{name}", response_model=LLMConfigDTO)
    async def update_llm_config(
        request: Request,
        name: str,
        body: LLMConfigUpdateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            config = await _run_sync(
                rt.admin.update_llm_config,
                name,
                identity,
                provider=body.provider,
                model=body.model,
                temperature=body.temperature,
                api_key=body.api_key,
                extra_config=body.extra_config,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        rt.audit_log.log(
            action="llm.config_updated",
            actor=identity.subject,
            target=name,
            target_type="llm_config",
            details=f"LLM config {name!r} updated",
            severity="info",
        )
        return llm_config_to_dto(config)

    @app.delete("/api/admin/llm/configs/{name}")
    async def delete_llm_config(
        request: Request,
        name: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            deleted = await _run_sync(rt.admin.delete_llm_config, name, identity)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        if not deleted:
            raise HTTPException(
                status_code=404, detail=f"LLM config {name!r} not found"
            )
        rt.audit_log.log(
            action="llm.config_deleted",
            actor=identity.subject,
            target=name,
            target_type="llm_config",
            details=f"LLM config {name!r} deleted",
            severity="warning",
        )
        return {"ok": True}

    # ==================================================================
    # Coordinator Settings
    # ==================================================================

    @app.get("/api/admin/settings", response_model=CoordinatorSettingsDTO)
    async def get_settings(
        request: Request,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        oidc_issuer = os.getenv("AGBUS_OIDC_ISSUER", "")
        return CoordinatorSettingsDTO(
            host=os.getenv("AGBUS_HOST", "0.0.0.0"),
            port=int(os.getenv("AGBUS_PORT", "8765")),
            oidc_enabled=bool(oidc_issuer),
            oidc_issuer=oidc_issuer,
            oidc_audience=os.getenv("AGBUS_OIDC_AUDIENCE", ""),
            auto_approve=os.getenv("AGBUS_AGENT_AUTO_APPROVE", "false").lower()
            in ("true", "1", "yes"),
            database_url=os.getenv("AGBUS_DATABASE_URL", "sqlite:///agbus_agents.db"),
        )

    # ==================================================================
    # Current User ("who am I")
    # ==================================================================

    @app.get("/api/admin/me", response_model=CurrentUserDTO)
    async def get_current_user(
        request: Request,
        identity: OIDCIdentity = Depends(_get_identity),
    ):
        policy = AdminPolicy.from_env()
        is_admin = policy.is_admin(identity)
        rt = _rt(request)
        user = await _run_sync(rt.user_repo.get_by_subject, identity.subject)

        tenant_ids: list[int] = []
        tenant_slugs: list[str] = []
        email = ""
        display_name = identity.subject
        role = "admin" if is_admin else "user"

        if user:
            email = user.email or ""
            display_name = user.display_name or identity.subject
            role = user.role.value if hasattr(user.role, "value") else str(user.role)
            if is_admin:
                role = "admin"
            tids = await _run_sync(rt.user_repo.get_user_tenant_ids, user.id)
            for tid in tids:
                t = await _run_sync(rt.tenant_repo.get, tid)
                if t:
                    tenant_ids.append(t.id)
                    tenant_slugs.append(t.slug)

        return CurrentUserDTO(
            subject=identity.subject,
            email=email,
            display_name=display_name,
            role=role,
            is_admin=is_admin,
            tenant_ids=tenant_ids,
            tenant_slugs=tenant_slugs,
        )

    # ==================================================================
    # Tenants
    # ==================================================================

    @app.get("/api/admin/tenants", response_model=list[TenantDTO])
    async def list_tenants(
        request: Request,
        identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        is_admin, user_tenant_ids = await _resolve_user(identity, request)
        tenants = await _run_sync(rt.tenant_repo.list_all)
        if not is_admin:
            tenants = [t for t in tenants if t.id in user_tenant_ids]
        return [tenant_to_dto(t) for t in tenants]

    @app.get("/api/admin/tenants/{tenant_id}", response_model=TenantDTO)
    async def get_tenant(
        request: Request,
        tenant_id: int,
        identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        is_admin, user_tenant_ids = await _resolve_user(identity, request)
        if not is_admin and tenant_id not in user_tenant_ids:
            raise HTTPException(status_code=403, detail="Access denied")
        tenant = await _run_sync(rt.tenant_repo.get, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")
        return tenant_to_dto(tenant)

    @app.post("/api/admin/tenants", response_model=TenantDTO)
    async def create_tenant(
        request: Request,
        body: TenantCreateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            tenant = await _run_sync(
                rt.tenant_repo.create, body.slug, body.name, enabled=body.enabled
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        rt.audit_log.log(
            action="tenant.created",
            actor=identity.subject,
            target=body.slug,
            target_type="tenant",
            details=f"Tenant {body.name!r} created",
            severity="info",
        )
        return tenant_to_dto(tenant)

    @app.put("/api/admin/tenants/{tenant_id}", response_model=TenantDTO)
    async def update_tenant(
        request: Request,
        tenant_id: int,
        body: TenantUpdateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            tenant = await _run_sync(
                rt.tenant_repo.update, tenant_id, name=body.name, enabled=body.enabled
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        rt.audit_log.log(
            action="tenant.updated",
            actor=identity.subject,
            target=str(tenant_id),
            target_type="tenant",
            details=f"Tenant {tenant_id} updated",
            severity="info",
        )
        return tenant_to_dto(tenant)

    @app.delete("/api/admin/tenants/{tenant_id}")
    async def delete_tenant(
        request: Request,
        tenant_id: int,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        deleted = await _run_sync(rt.tenant_repo.delete, tenant_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")
        rt.audit_log.log(
            action="tenant.deleted",
            actor=identity.subject,
            target=str(tenant_id),
            target_type="tenant",
            details="Tenant deleted",
            severity="warning",
        )
        return {"ok": True}

    # -- Tenant ↔ Agent assignments

    @app.post("/api/admin/tenants/{tenant_id}/agents/{agent_id}")
    async def assign_agent_to_tenant(
        request: Request,
        tenant_id: int,
        agent_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        tenant = await _run_sync(rt.tenant_repo.get, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        await _run_sync(rt.tenant_repo.assign_agent, agent_id, tenant_id)
        rt.audit_log.log(
            action="tenant.agent_assigned",
            actor=identity.subject,
            target=agent_id,
            target_type="agent",
            details=f"Agent assigned to tenant {tenant.slug}",
            severity="info",
        )
        return {"ok": True}

    @app.delete("/api/admin/tenants/{tenant_id}/agents/{agent_id}")
    async def unassign_agent_from_tenant(
        request: Request,
        tenant_id: int,
        agent_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        removed = await _run_sync(rt.tenant_repo.unassign_agent, agent_id, tenant_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Assignment not found")
        rt.audit_log.log(
            action="tenant.agent_unassigned",
            actor=identity.subject,
            target=agent_id,
            target_type="agent",
            details=f"Agent removed from tenant {tenant_id}",
            severity="info",
        )
        return {"ok": True}

    # ==================================================================
    # Users
    # ==================================================================

    @app.get("/api/admin/users", response_model=list[UserDTO])
    async def list_users(
        request: Request,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        users = await _run_sync(rt.user_repo.list_all)
        return [user_to_dto(u) for u in users]

    @app.get("/api/admin/users/{user_id}", response_model=UserDTO)
    async def get_user(
        request: Request,
        user_id: int,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        user = await _run_sync(rt.user_repo.get, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        return user_to_dto(user)

    @app.post("/api/admin/users", response_model=UserDTO)
    async def create_user(
        request: Request,
        body: UserCreateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            role_enum = UserRole(body.role)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role: {body.role!r}. Must be 'admin' or 'user'.",
            )
        try:
            user = await _run_sync(
                rt.user_repo.create,
                body.subject,
                email=body.email,
                display_name=body.display_name,
                role=role_enum,
                enabled=body.enabled,
                created_by=identity.subject,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Assign to tenants
        for tid in body.tenant_ids:
            await _run_sync(rt.user_repo.assign_tenant, user.id, tid)

        rt.audit_log.log(
            action="user.created",
            actor=identity.subject,
            target=body.subject,
            target_type="user",
            details=f"User {body.display_name or body.subject!r} created with role {body.role}",
            severity="info",
        )
        # Re-fetch to include tenant associations
        user = await _run_sync(rt.user_repo.get, user.id)
        return user_to_dto(user)

    @app.put("/api/admin/users/{user_id}", response_model=UserDTO)
    async def update_user(
        request: Request,
        user_id: int,
        body: UserUpdateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        kwargs: dict[str, Any] = {}
        if body.email is not None:
            kwargs["email"] = body.email
        if body.display_name is not None:
            kwargs["display_name"] = body.display_name
        if body.role is not None:
            try:
                kwargs["role"] = UserRole(body.role)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid role: {body.role!r}")
        if body.enabled is not None:
            kwargs["enabled"] = body.enabled

        try:
            user = await _run_sync(rt.user_repo.update, user_id, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        # Update tenant assignments if provided
        if body.tenant_ids is not None:
            current = set(await _run_sync(rt.user_repo.get_user_tenant_ids, user_id))
            desired = set(body.tenant_ids)
            for tid in desired - current:
                await _run_sync(rt.user_repo.assign_tenant, user_id, tid)
            for tid in current - desired:
                await _run_sync(rt.user_repo.unassign_tenant, user_id, tid)

        rt.audit_log.log(
            action="user.updated",
            actor=identity.subject,
            target=str(user_id),
            target_type="user",
            details=f"User {user_id} updated",
            severity="info",
        )
        user = await _run_sync(rt.user_repo.get, user_id)
        return user_to_dto(user)

    @app.delete("/api/admin/users/{user_id}")
    async def delete_user(
        request: Request,
        user_id: int,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        deleted = await _run_sync(rt.user_repo.delete, user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        rt.audit_log.log(
            action="user.deleted",
            actor=identity.subject,
            target=str(user_id),
            target_type="user",
            details="User deleted",
            severity="warning",
        )
        return {"ok": True}

    # ------------------------------------------------------------------
    # IBAC Rule endpoints
    # ------------------------------------------------------------------

    @app.get("/api/admin/ibac/rules", response_model=list[IBACRuleDTO])
    async def list_ibac_rules(
        request: Request,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        rules = await _run_sync(rt.admin.list_ibac_rules)
        return [ibac_rule_to_dto(r) for r in rules]

    @app.get("/api/admin/ibac/rules/{rule_id}", response_model=IBACRuleDTO)
    async def get_ibac_rule(
        request: Request,
        rule_id: str,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        rule = await _run_sync(rt.admin.get_ibac_rule, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail=f"IBAC rule '{rule_id}' not found")
        return ibac_rule_to_dto(rule)

    @app.post("/api/admin/ibac/rules", response_model=IBACRuleDTO, status_code=201)
    async def create_ibac_rule(
        request: Request,
        body: IBACRuleCreateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            rule = await _run_sync(
                rt.admin.add_ibac_rule,
                body.rule_id,
                body.name,
                identity,
                description=body.description,
                enabled=body.enabled,
                priority=body.priority,
                action=body.action,
                evaluation_points=body.evaluation_points,
                conditions=body.conditions,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        rt.audit_log.log(
            action="ibac.rule_created",
            actor=identity.subject,
            target=body.rule_id,
            target_type="ibac_rule",
            details=f"IBAC rule '{body.name}' created (action={body.action}, priority={body.priority})",
            severity="info",
        )
        return ibac_rule_to_dto(rule)

    @app.put("/api/admin/ibac/rules/{rule_id}", response_model=IBACRuleDTO)
    async def update_ibac_rule(
        request: Request,
        rule_id: str,
        body: IBACRuleUpdateRequest,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        try:
            rule = await _run_sync(
                rt.admin.update_ibac_rule,
                rule_id,
                identity,
                name=body.name,
                description=body.description,
                enabled=body.enabled,
                priority=body.priority,
                action=body.action,
                evaluation_points=body.evaluation_points,
                conditions=body.conditions,
            )
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        rt.audit_log.log(
            action="ibac.rule_updated",
            actor=identity.subject,
            target=rule_id,
            target_type="ibac_rule",
            details=f"IBAC rule '{rule_id}' updated",
            severity="info",
        )
        return ibac_rule_to_dto(rule)

    @app.delete("/api/admin/ibac/rules/{rule_id}")
    async def delete_ibac_rule(
        request: Request,
        rule_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        deleted = await _run_sync(rt.admin.delete_ibac_rule, rule_id, identity)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"IBAC rule '{rule_id}' not found")
        rt.audit_log.log(
            action="ibac.rule_deleted",
            actor=identity.subject,
            target=rule_id,
            target_type="ibac_rule",
            details=f"IBAC rule '{rule_id}' deleted",
            severity="warning",
        )
        return {"ok": True}

    # ==================================================================
    # Session Archives (History)
    # ==================================================================

    @app.get("/api/admin/history", response_model=list[SessionArchiveListDTO])
    async def list_session_archives(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        outcome: str | None = Query(default=None),
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        archives = await _run_sync(
            rt.archive_repo.list_all,
            limit=limit,
            offset=offset,
            outcome=outcome,
        )
        return [session_archive_to_list_dto(a) for a in archives]

    @app.get("/api/admin/history/count")
    async def count_session_archives(
        request: Request,
        outcome: str | None = Query(default=None),
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        total = await _run_sync(rt.archive_repo.count, outcome=outcome)
        return {"count": total}

    @app.get("/api/admin/history/{session_id}", response_model=SessionArchiveDetailDTO)
    async def get_session_archive(
        request: Request,
        session_id: str,
        _identity: OIDCIdentity = Depends(_get_identity),
    ):
        rt = _rt(request)
        archive = await _run_sync(rt.archive_repo.get, session_id)
        if archive is None:
            raise HTTPException(status_code=404, detail=f"Archive '{session_id}' not found")
        return session_archive_to_detail_dto(archive)

    @app.delete("/api/admin/history/{session_id}")
    async def delete_session_archive(
        request: Request,
        session_id: str,
        identity: OIDCIdentity = Depends(_require_admin),
    ):
        rt = _rt(request)
        deleted = await _run_sync(rt.archive_repo.delete, session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Archive '{session_id}' not found")
        rt.audit_log.log(
            action="history.archive_deleted",
            actor=identity.subject,
            target=session_id,
            target_type="session",
            details=f"Session archive '{session_id}' deleted",
            severity="warning",
        )
        return {"ok": True}

    return app
