"""Serialisation helpers – convert ORM / registry objects to API DTOs."""

from __future__ import annotations

from agentic_bus.coordinator.admin.schemas import (
    AgentCapabilityDTO,
    EphemeralAgentDTO,
    IBACRuleDTO,
    LLMConfigDTO,
    MCPServerDTO,
    MCPToolOverrideDTO,
    ManagedAgentCapabilityDTO,
    ManagedAgentDTO,
    PersistentAgentDTO,
    SessionArchiveDetailDTO,
    SessionArchiveListDTO,
    SessionDTO,
    TenantDTO,
    UserDTO,
)
from agentic_bus.core.persistence.models import (
    IBACRule,
    LLMConfig,
    MCPServer,
    ManagedAgent,
    ManagedAgentCapability,
    PersistentAgent,
    SessionArchive,
    Tenant,
    User,
)
from agentic_bus.core.registry.capability_registry import AgentRegistration
from agentic_bus.core.session.manager import SessionState


def persistent_agent_to_dto(agent: PersistentAgent) -> PersistentAgentDTO:
    caps = agent.capabilities_json if agent.capabilities_json else []
    return PersistentAgentDTO(
        agent_id=agent.agent_id,
        public_key_pem=agent.public_key_pem,
        status=agent.status.value if hasattr(agent.status, "value") else str(agent.status),
        semantic_description=agent.semantic_description or "",
        version=agent.version or "",
        capabilities=[
            AgentCapabilityDTO(
                capability_id=c.get("capability_id", ""),
                description=c.get("description", ""),
                estimated_cost=c.get("estimated_cost"),
                estimated_latency=c.get("estimated_latency"),
            )
            for c in caps
        ],
        required_scopes=agent.required_scopes_json or [],
        supported_domains=agent.supported_domains_json or [],
        enrolled_at=agent.enrolled_at.isoformat() if agent.enrolled_at else "",
        approved_at=agent.approved_at.isoformat() if agent.approved_at else None,
        approved_by=agent.approved_by,
        last_connected_at=(
            agent.last_connected_at.isoformat() if agent.last_connected_at else None
        ),
        total_executions=agent.total_executions or 0,
        current_score=agent.current_score or 0.0,
        mean_latency_ms=agent.mean_latency_ms or 0.0,
        last_execution_at=(
            agent.last_execution_at.isoformat() if agent.last_execution_at else None
        ),
    )


def managed_capability_to_dto(cap: ManagedAgentCapability) -> ManagedAgentCapabilityDTO:
    return ManagedAgentCapabilityDTO(
        id=cap.id,
        capability_id=cap.capability_id,
        description=cap.description or "",
        expected_output=cap.expected_output or "",
        required_scopes=cap.required_scopes_json or [],
        supported_data_domains=cap.supported_data_domains_json or [],
        estimated_cost=cap.estimated_cost or 0.0,
        estimated_latency=cap.estimated_latency or 0.0,
        output_fields=cap.output_fields_json or [],
        output_schema=cap.output_schema_json or {},
    )


def managed_agent_to_dto(agent: ManagedAgent) -> ManagedAgentDTO:
    return ManagedAgentDTO(
        id=agent.id,
        agent_id=agent.agent_id,
        name=agent.name,
        role=agent.role,
        goal=agent.goal,
        backstory=agent.backstory,
        llm_config_name=agent.llm_config_name,
        verbose=agent.verbose,
        max_iter=agent.max_iter,
        max_rpm=agent.max_rpm,
        memory=agent.memory,
        tools=agent.tools_json or [],
        tool_config=_mask_tool_secrets(agent.tools_json or [], agent.tool_config_json or {}),
        status=agent.status.value if hasattr(agent.status, "value") else str(agent.status),
        capabilities=[managed_capability_to_dto(c) for c in (agent.capabilities or [])],
        created_at=agent.created_at.isoformat() if agent.created_at else "",
        updated_at=agent.updated_at.isoformat() if agent.updated_at else "",
        created_by=agent.created_by or "",
        total_executions=agent.total_executions or 0,
        current_score=agent.current_score or 0.0,
        mean_latency_ms=agent.mean_latency_ms or 0.0,
        last_execution_at=(
            agent.last_execution_at.isoformat() if agent.last_execution_at else None
        ),
    )


def _mask_tool_secrets(
    tools: list[str],
    config: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Mask secret values in tool config for API responses.

    Values whose requirement has ``secret: True`` are replaced with a
    masked placeholder so API consumers know a value is set without
    exposing the raw secret.
    """
    from agentic_bus.agents.factory import CREWAI_TOOL_REQUIREMENTS

    masked: dict[str, dict[str, object]] = {}
    for tool_name in tools:
        tool_cfg = config.get(tool_name)
        if not tool_cfg:
            masked[tool_name] = {}
            continue
        reqs = CREWAI_TOOL_REQUIREMENTS.get(tool_name, [])
        secret_keys = {r["key"] for r in reqs if r.get("secret")}
        entry: dict[str, object] = {}
        for k, v in tool_cfg.items():
            if k in secret_keys and v:
                s = str(v)
                entry[k] = s[:3] + "…" + s[-3:] if len(s) > 8 else "***"
            else:
                entry[k] = v
        masked[tool_name] = entry
    return masked


def registration_to_ephemeral_dto(reg: AgentRegistration) -> EphemeralAgentDTO:
    return EphemeralAgentDTO(
        agent_id=reg.agent_id,
        version=reg.version,
        status="online",
        semantic_description=reg.semantic_description,
        capabilities=[
            AgentCapabilityDTO(
                capability_id=c.capability_id,
                description=c.description,
                estimated_cost=c.estimated_cost,
                estimated_latency=c.estimated_latency,
            )
            for c in reg.capabilities
        ],
        required_scopes=reg.required_scopes,
        supported_domains=reg.supported_data_domains,
        operational_constraints=reg.operational_constraints,
        registered_at=reg.registered_at,
    )


def llm_config_to_dto(config: LLMConfig) -> LLMConfigDTO:
    return LLMConfigDTO(
        id=config.id,
        name=config.name,
        provider=config.provider,
        model=config.model,
        temperature=config.temperature,
        is_current=config.is_current,
        extra_config=config.extra_config if config.extra_config else None,
        created_at=config.created_at.isoformat() if config.created_at else "",
        updated_at=config.updated_at.isoformat() if config.updated_at else "",
        created_by=config.created_by or "",
    )


def session_to_dto(session: SessionState) -> SessionDTO:
    return SessionDTO(
        session_id=session.session_id,
        phase=session.phase.value if hasattr(session.phase, "value") else str(session.phase),
        requester_id=session.requester_id,
        discovered_agents=session.discovered_agents,
        accepted_offers=session.accepted_offers,
        created_at=session.created_at,
        dissolved_at=session.dissolved_at,
    )


def ibac_rule_to_dto(rule: IBACRule) -> IBACRuleDTO:
    return IBACRuleDTO(
        id=rule.id,
        rule_id=rule.rule_id,
        name=rule.name,
        description=rule.description or "",
        enabled=rule.enabled,
        priority=rule.priority,
        action=rule.action.value if hasattr(rule.action, "value") else str(rule.action),
        evaluation_points=rule.evaluation_points_json or [],
        conditions=rule.conditions_json or {},
        created_at=rule.created_at.isoformat() if rule.created_at else "",
        updated_at=rule.updated_at.isoformat() if rule.updated_at else "",
        created_by=rule.created_by or "",
    )


def tenant_to_dto(tenant: Tenant) -> TenantDTO:
    return TenantDTO(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        enabled=tenant.enabled,
        created_at=tenant.created_at.isoformat() if tenant.created_at else "",
        updated_at=tenant.updated_at.isoformat() if tenant.updated_at else "",
        user_count=len(tenant.user_associations) if tenant.user_associations else 0,
        agent_count=len(tenant.agent_associations) if tenant.agent_associations else 0,
    )


def user_to_dto(user: User) -> UserDTO:
    tenant_ids: list[int] = []
    tenant_slugs: list[str] = []
    if user.tenant_associations:
        for assoc in user.tenant_associations:
            tenant_ids.append(assoc.tenant_id)
            if assoc.tenant:
                tenant_slugs.append(assoc.tenant.slug)
    return UserDTO(
        id=user.id,
        subject=user.subject,
        email=user.email or "",
        display_name=user.display_name or "",
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        enabled=user.enabled,
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else "",
        created_by=user.created_by or "",
        tenant_ids=tenant_ids,
        tenant_slugs=tenant_slugs,
    )


# ---------------------------------------------------------------------------
# Session Archive serializers
# ---------------------------------------------------------------------------


def session_archive_to_list_dto(archive: SessionArchive) -> SessionArchiveListDTO:
    """Convert a SessionArchive ORM object to a lightweight list DTO."""
    plan = archive.composition_plan_json or {}
    steps = plan.get("steps", [])
    agents = archive.agents_json or {}
    discovered = archive.discovered_agents_json or []
    # agents_json has detail per agent; fall back to unique discovered agents
    agent_count = len(agents) if agents else len(set(discovered))
    return SessionArchiveListDTO(
        id=archive.id,
        session_id=archive.session_id,
        requester_id=archive.requester_id,
        intent_text=archive.intent_text or "",
        intent_domain=archive.intent_domain or "",
        outcome=(
            archive.outcome.value
            if hasattr(archive.outcome, "value")
            else str(archive.outcome)
        ),
        outcome_summary=archive.outcome_summary or "",
        agent_count=agent_count,
        step_count=len(steps),
        created_at=archive.created_at.isoformat() if archive.created_at else "",
        dissolved_at=archive.dissolved_at.isoformat() if archive.dissolved_at else "",
        duration_seconds=archive.duration_seconds or 0.0,
    )


def session_archive_to_detail_dto(archive: SessionArchive) -> SessionArchiveDetailDTO:
    """Convert a SessionArchive ORM object to a full detail DTO."""
    return SessionArchiveDetailDTO(
        id=archive.id,
        session_id=archive.session_id,
        requester_id=archive.requester_id,
        requester_oidc_subject=archive.requester_oidc_subject or "",
        intent_text=archive.intent_text or "",
        intent_domain=archive.intent_domain or "",
        decomposition=archive.decomposition_json or {},
        outcome=(
            archive.outcome.value
            if hasattr(archive.outcome, "value")
            else str(archive.outcome)
        ),
        outcome_summary=archive.outcome_summary or "",
        discovered_agents=archive.discovered_agents_json or [],
        accepted_agents=archive.accepted_agents_json or [],
        agents=archive.agents_json or {},
        composition_plan=archive.composition_plan_json or {},
        execution_results=archive.execution_results_json or [],
        timeline_events=archive.timeline_events_json or [],
        audit_trail=archive.audit_trail_json or [],
        ibac_decisions=archive.ibac_decisions_json or [],
        output=getattr(archive, "output", None) or None,
        output_summary=getattr(archive, "output_summary", None) or None,
        agent_metrics=getattr(archive, "agent_metrics_json", None) or [],
        created_at=archive.created_at.isoformat() if archive.created_at else "",
        dissolved_at=archive.dissolved_at.isoformat() if archive.dissolved_at else "",
        duration_seconds=archive.duration_seconds or 0.0,
    )


# ---------------------------------------------------------------------------
# MCP Server serializers
# ---------------------------------------------------------------------------


def mcp_server_to_dto(
    mcp: MCPServer,
    *,
    is_connected: bool = False,
    discovered_tools: list[str] | None = None,
) -> MCPServerDTO:
    """Convert an ``MCPServer`` ORM record to an API DTO.

    Parameters
    ----------
    mcp:
        The database record.
    is_connected:
        Whether the bridge agent is currently online (populated by the API
        handler from runtime state).
    discovered_tools:
        Tool names currently known to the bridge (populated at runtime).
    """
    overrides: dict[str, MCPToolOverrideDTO] = {}
    raw_overrides = mcp.tool_overrides_json or {}
    for tool_name, ovr in raw_overrides.items():
        if isinstance(ovr, dict):
            overrides[tool_name] = MCPToolOverrideDTO(**ovr)
        else:
            overrides[tool_name] = ovr

    return MCPServerDTO(
        id=mcp.id,
        server_id=mcp.server_id,
        server_url=mcp.server_url,
        transport=mcp.transport,
        agent_id=mcp.agent_id,
        semantic_description=mcp.semantic_description or "",
        mode=mcp.mode or "persistent",
        tool_overrides=overrides,
        status=mcp.status.value if hasattr(mcp.status, "value") else str(mcp.status),
        total_executions=mcp.total_executions or 0,
        current_score=mcp.current_score or 0.0,
        mean_latency_ms=mcp.mean_latency_ms or 0.0,
        last_execution_at=(
            mcp.last_execution_at.isoformat() if mcp.last_execution_at else None
        ),
        created_at=mcp.created_at.isoformat() if mcp.created_at else "",
        updated_at=mcp.updated_at.isoformat() if mcp.updated_at else "",
        created_by=mcp.created_by or "",
        is_connected=is_connected,
        discovered_tools=discovered_tools or [],
    )
