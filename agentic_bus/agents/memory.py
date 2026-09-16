"""Staging an execution's writes to the session's shared memory.

:class:`~agentic_bus.core.session.memory.SessionMemory` lives on the
coordinator, is namespaced, carries a per-agent access policy derived from the
composition plan, audits every operation, and is destroyed at dissolution. The
coordinator already reads ``memory_writes`` off a ``complete`` and applies them
through that policy, counting what it refused.

Nothing on the agent side ever put anything there. This is that half.

Writes are *staged* during execution and travel on the ``complete``, rather
than being sent as they happen, for two reasons. An execution that fails
part-way should not leave half its writes behind; and the policy check belongs
to the coordinator, which owns the memory — an agent that could write directly
would be an agent deciding what it may write.

Namespaces, from ``SessionMemory``:

``shared.*``
    Readable and writable by any agent the plan authorised.

``<agent_id>.*``
    That agent's own, plus the coordinator. The plan grants the *next* step
    read access to the previous step's namespace, which is how a result
    reaches the agent that consumes it.

A key outside the agent's write patterns is refused by the coordinator and
recorded as a denial — it is not dropped silently. Choosing the namespace is
therefore the author's decision and it is checkable, which is why nothing here
prefixes a key on the author's behalf.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any

logger = logging.getLogger(__name__)


#: Writes staged by the execution running on this task.
#:
#: A context variable for the same reason the scope grant is one: an author
#: should be able to call :func:`remember` from inside a tool without the
#: session having been threaded down to it, and asyncio gives each task its
#: own value, so concurrent executions cannot write into each other's batch.
_staged: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "agentic_bus_memory_writes", default=None
)


def remember(key: str, value: Any) -> None:
    """Stage *value* under *key* for the session's shared memory.

    The write is applied by the coordinator when the execution completes, and
    only if the agent's write policy admits the key::

        from agentic_bus import remember

        async def execute_task(self, payload, context):
            rows = await self.crm.get().find(...)
            remember(f"{self.agent_id}.customers", {"rows": len(rows)})
            return {"count": len(rows)}

    Outside an execution there is nothing to stage and this does nothing,
    matching :func:`~agentic_bus.agents.scope_guard.require_scope` — a script
    or a test that never registered has no session to write into.

    Staging the same key twice keeps the last value: the batch is what the
    execution ended up meaning to write, not a log of how it got there.
    """
    staged = _staged.get()
    if staged is None:
        logger.debug("remember(%r) outside an execution — nothing to stage", key)
        return
    staged[key] = value


def staged_writes() -> dict[str, Any]:
    """A copy of what this execution has staged so far.

    Returned as a copy so a caller reading the batch cannot edit it in place;
    :func:`remember` stays the only way in.
    """
    return dict(_staged.get() or {})


def open_staging() -> contextvars.Token:
    """Start a batch for this task. Close it with :func:`reset_staging`.

    Called by ``BaseAgent`` around ``execute_task``; agents do not call it.
    """
    return _staged.set({})


def reset_staging(token: contextvars.Token) -> None:
    _staged.reset(token)


#: What this execution may read, as the coordinator filtered it.
#:
#: Separate from the staging buffer on purpose: what an execution wrote is not
#: what it can read. The coordinator applies staged writes through the agent's
#: write policy when the execution completes, and a key the policy refuses is
#: never in anyone's snapshot. Folding the two together here would let an
#: agent read back a write that was about to be denied.
_snapshot: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "agentic_bus_memory_snapshot", default=None
)


def recall(key: str, default: Any = None) -> Any:
    """Read *key* from the session's shared memory.

    The counterpart of :func:`remember`, and the half that was missing: the
    coordinator has always built a per-agent snapshot and put it on the
    ``execute``, and ``BaseAgent`` never handed it to ``execute_task``, so a
    step could write to the shared store and no step could read it::

        from agentic_bus import recall

        async def execute_task(self, payload, context):
            customers = recall("crm-reader.customers", default=[])
            return {"sent": len(customers)}

    What arrives is already filtered. The plan grants each step read access to
    the namespaces of the steps before it, so this returns what *this* agent
    was authorised to see and nothing else — asking for a key outside that is
    a miss, not a refusal, because the key was never delivered.

    It is a snapshot taken when the execution was dispatched, not a live view.
    Writes staged during this execution are not in it: they are applied by the
    coordinator afterwards, through a policy that may refuse them, and reading
    back an unapplied write would report as stored something that is not.

    Outside an execution there is nothing to read and *default* comes back,
    matching :func:`remember` and
    :func:`~agentic_bus.agents.scope_guard.require_scope`.
    """
    snapshot = _snapshot.get()
    if snapshot is None:
        logger.debug("recall(%r) outside an execution — nothing to read", key)
        return default
    return snapshot.get(key, default)


def recalled() -> dict[str, Any]:
    """Everything this execution may read, as a copy.

    For an agent that wants to see what it was given rather than ask for one
    key — a consumer that does not know which step produced what, say.
    """
    return dict(_snapshot.get() or {})


def set_snapshot(snapshot: dict[str, Any] | None) -> contextvars.Token:
    """Install what this task may read. Close with :func:`reset_snapshot`.

    Called by ``BaseAgent`` around ``execute_task``; agents do not call it.
    """
    return _snapshot.set(dict(snapshot or {}))


def reset_snapshot(token: contextvars.Token) -> None:
    _snapshot.reset(token)
