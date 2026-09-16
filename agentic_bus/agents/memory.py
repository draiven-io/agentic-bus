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
            rows = await self.crm.get().buscar(...)
            remember(f"{self.agent_id}.clientes", {"rows": len(rows)})
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
