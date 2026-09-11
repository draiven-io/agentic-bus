"""Enforcing a grant where the work actually happens.

A coordinator cannot police what runs inside an agent's process. That is not a
gap in this implementation — it is where the trust boundary is. So this module
is deliberate about which attacker it stops.

**It does not stop a malicious agent binary.** Someone who controls the agent's
code can call whatever it likes and report whatever it likes. Nothing running
inside that process could prevent it.

**It does stop a compromised agent brain**, which is the realistic threat for
an agent driven by a language model. A prompt injected through a document can
persuade the model to call ``send_email``; it cannot persuade the tool
invocation path to skip the guard, because the guard is not in the model's
control. The model chooses *what to call*; it does not choose *whether the call
is checked*.

That distinction is what makes the usage report worth reading. Uses are
recorded by the invocation path rather than volunteered by the model, so the
report reflects what happened rather than what the agent would like to say
happened — and a coordinator reconciling it against the grant catches an agent
that was talked into exceeding its authority.
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass, field

from agentic_bus.core.scopes import covered_by_any, normalise

logger = logging.getLogger(__name__)


class ScopeDenied(PermissionError):
    """Raised when work requires a scope this execution was not granted.

    A subclass of :class:`PermissionError` so an agent that catches broad
    permission failures behaves sensibly without knowing about this type.
    """

    def __init__(self, scope: str, granted: list[str]) -> None:
        self.scope = scope
        self.granted = list(granted)
        super().__init__(
            f"{scope!r} was not granted for this execution "
            f"(granted: {', '.join(granted) or 'nothing'})"
        )


@dataclass
class ScopeGrant:
    """What one execution was authorised to do, and what it actually did.

    Created from the ``authorized_scopes`` the coordinator sends with
    ``execute``. The agent does not choose its contents.
    """

    session_id: str = ""
    capability_id: str = ""
    granted: list[str] = field(default_factory=list)
    #: Every scope the invocation path checked, in order of first use. Recorded
    #: whether the check passed or failed, because a refused attempt is the
    #: more interesting half.
    used: list[str] = field(default_factory=list)
    #: Scopes required and not held. Populated even though the call raised, so
    #: the completion can report the attempt.
    denied: list[str] = field(default_factory=list)

    def permits(self, scope: str) -> bool:
        return covered_by_any(self.granted, scope)

    def require(self, scope: str) -> None:
        """Record the use and raise if it was not authorised."""
        scope = normalise(scope)
        if scope and scope not in self.used:
            self.used.append(scope)

        if self.permits(scope):
            return

        if scope not in self.denied:
            self.denied.append(scope)
        logger.warning(
            "Agent work required %r, which this execution does not hold", scope
        )
        raise ScopeDenied(scope, self.granted)


#: The grant in force for the current task.
#:
#: A context variable rather than an argument threaded through every call: an
#: agent author should be able to write ``require_scope("payments:write")``
#: inside a tool without the session having been plumbed to it, and asyncio
#: gives each task its own value, so concurrent sessions cannot read each
#: other's grant.
_current: contextvars.ContextVar[ScopeGrant | None] = contextvars.ContextVar(
    "agentic_bus_scope_grant", default=None
)


def current_grant() -> ScopeGrant | None:
    """The grant for the execution running on this task, if any."""
    return _current.get()


def set_grant(grant: ScopeGrant | None) -> contextvars.Token:
    """Install a grant for this task. Reset with :func:`reset_grant`."""
    return _current.set(grant)


def reset_grant(token: contextvars.Token) -> None:
    _current.reset(token)


def require_scope(scope: str) -> None:
    """Assert that the running execution holds *scope*.

    Call it from a tool, or anywhere work happens that a scope is meant to
    govern::

        from agentic_bus.agents.scope_guard import require_scope

        @tool
        def issue_refund(order_id: str) -> str:
            require_scope("payments:refund")
            ...

    Outside an execution — a test, a script, an agent that never registered —
    there is no grant, and this does nothing. Refusing there would break every
    caller that is not running under a coordinator, to protect nothing: a
    process with no grant is not one an attacker reached through the bus.
    """
    grant = _current.get()
    if grant is None:
        logger.debug("require_scope(%r) outside an execution — nothing to check", scope)
        return
    grant.require(scope)


def scope_is_held(scope: str) -> bool:
    """Whether the running execution holds *scope*, without raising.

    For deciding between two paths rather than refusing one — offering a
    narrower answer when the broader one is not authorised, say. The use is
    still recorded.
    """
    grant = _current.get()
    if grant is None:
        return True
    if scope and normalise(scope) not in grant.used:
        grant.used.append(normalise(scope))
    return grant.permits(scope)
