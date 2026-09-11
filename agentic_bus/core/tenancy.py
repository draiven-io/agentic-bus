"""Which agents a requester is allowed to see at all.

The data model has had tenants since the beginning and the coordination path
has never consulted them: the capability registry is global, and discovery
hands *every* registered agent's description to a language model, which then
picks. In a deployment serving more than one customer that is two problems,
and only one of them is the obvious one.

The obvious one is that the model can pick another tenant's agent. The other
is that it *saw* them — capability descriptions are not innocuous
(``"Query ACME Corp's payroll database"``), and by the time a result is
filtered the description has already been written into a prompt. So filtering
happens before the summaries are assembled, not after the candidates come
back.

Tenant is a **derived** fact throughout. It is resolved from the authenticated
subject on the connection, never read from the envelope — a tenant a caller
can write is a tenant a caller can choose.

The default is deliberate and preserves single-tenant deployments: an agent
assigned to no tenant is **global**, visible to everyone. Tenancy switches on
by assigning agents to tenants, not by setting a flag, so a bus that never
heard of tenants keeps working and one that uses them is isolated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantScope:
    """What one requester may see.

    ``tenant_ids`` empty means the requester resolved to no tenant — an
    unidentified caller, or one whose subject is not enrolled. They see global
    agents only, which in a deployment that assigns every agent is nothing.
    That is the intended answer rather than an edge case: an unidentified
    caller in a tenanted bus has no business reaching a tenanted agent.
    """

    tenant_ids: list[int] = field(default_factory=list)
    subject: str = ""

    @property
    def is_resolved(self) -> bool:
        return bool(self.tenant_ids)

    @property
    def single_tenant_id(self) -> str:
        """The tenant, when there is exactly one.

        Empty when the requester belongs to several: the manifest's
        ``tenant_id`` is a single value, and picking one arbitrarily would
        make a boundary rule fire against a tenant nobody chose. An intent
        that needs to name one among several should say so, and be checked
        against this — which is not built yet, and is noted rather than
        guessed at.
        """
        if len(self.tenant_ids) == 1:
            return str(self.tenant_ids[0])
        return ""


class TenantResolver:
    """Resolves the tenant scope of a connection, and filters visibility."""

    def __init__(self, user_repo=None, tenant_repo=None) -> None:
        self._user_repo = user_repo
        self._tenant_repo = tenant_repo

    def scope_for(self, subject: str) -> TenantScope:
        """The tenants an authenticated subject belongs to.

        Resolved from the subject on the verified connection. A subject that
        matches no enrolled user resolves to no tenant rather than to all of
        them.
        """
        if not subject or self._user_repo is None:
            return TenantScope(subject=subject)

        try:
            user = self._user_repo.get_by_subject(subject)
            if user is None:
                logger.debug("Subject %r is not an enrolled user", subject)
                return TenantScope(subject=subject)
            tenant_ids = self._user_repo.get_user_tenant_ids(user.id)
        except Exception:
            # A membership lookup that fails must not widen visibility.
            logger.exception("Could not resolve tenants for subject %r", subject)
            return TenantScope(subject=subject)

        return TenantScope(tenant_ids=sorted(tenant_ids), subject=subject)

    def agent_tenants(self, agent_id: str) -> list[int]:
        """Tenants this agent is assigned to. Empty means global."""
        if self._tenant_repo is None:
            return []
        try:
            return list(self._tenant_repo.get_agent_tenant_ids(agent_id))
        except Exception:
            # Cannot establish an assignment. Treated as *assigned to nothing
            # reachable* rather than global, because failing open here would
            # expose exactly what this module exists to contain.
            logger.exception("Could not resolve tenants for agent %r", agent_id)
            return [-1]

    def visible_agents(self, scope: TenantScope, agent_ids: list[str]) -> list[str]:
        """Of *agent_ids*, those this scope may see.

        An agent assigned to no tenant is global. One assigned to tenants is
        visible only to a requester sharing at least one.
        """
        visible: list[str] = []
        for agent_id in agent_ids:
            assigned = self.agent_tenants(agent_id)
            if not assigned:
                visible.append(agent_id)  # global
                continue
            if any(t in scope.tenant_ids for t in assigned):
                visible.append(agent_id)
        return visible

    def any_agent_is_assigned(self, agent_ids: list[str]) -> bool:
        """Whether tenancy is in use at all on this bus.

        Used only to decide whether to say anything in the logs. Filtering
        itself needs no such switch — with nothing assigned, everything is
        global and the filter is the identity function.
        """
        return any(self.agent_tenants(a) for a in agent_ids)
