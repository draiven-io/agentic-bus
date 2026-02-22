"""Serialisation helpers – convert ORM / registry objects to API DTOs."""

from __future__ import annotations

from app.coordinator.admin.schemas import (
    AgentCapabilityDTO,
    EphemeralAgentDTO,
    IBACRuleDTO,
    LLMConfigDTO,
    ManagedAgentCapabilityDTO,
    ManagedAgentDTO,
    PersistentAgentDTO,
    SessionDTO,
    TenantDTO,
    UserDTO,
)
from app.core.persistence.models import (
    IBACRule,
    LLMConfig,
    ManagedAgent,
    ManagedAgentCapability,
    PersistentAgent,
    Tenant,
    User,
)
from app.core.registry.capability_registry import AgentRegistration
from app.core.session.manager import SessionState


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
    from app.agents.factory import CREWAI_TOOL_REQUIREMENTS

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
