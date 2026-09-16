"""Typed access to what an execution was told.

A capability publishes ``input_model``; the coordinator composes a step's
parameters against it and validates them before dispatch (RFC 0005). Then the
agent received a plain ``dict`` and read it with ``context.get("x") or ""`` —
the type it declared, used on one side of the wire and thrown away on the
other.

Two reasons that is worse than untidy. The agent reimplements every default
and every access by string, so the declared shape stops being the source of
truth. And when composition *fails* validation, the coordinator drops the
composed parameters and the step falls back to the requester's raw context —
which nobody validated. On that path the agent is the only check there is,
and a dict read with ``.get`` performs none.

So ``BaseAgent`` validates the context against the executing capability's
``input_model`` before calling ``execute_task``, whether or not the author
asks it to, and a mismatch is reported as ``invalid_input`` — distinct from an
error, because the agent did not break: it was handed a shape it never agreed
to receive. :func:`inputs` then hands the author the validated instance::

    from agentic_bus import inputs

    async def execute_task(self, payload, context):
        req = inputs(EnvioModelo)
        for d in req.destinatarios:
            await mailer.send(to=d.email, subject=req.assunto, ...)

Extra fields are ignored, as Pydantic does by default. That is the right
default here: the context the coordinator sends still carries whatever the
requester put in it, and the model picks its own fields out of it.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)


class InvalidInput(ValueError):
    """The context does not match the shape the capability published.

    A ``ValueError`` so a caller catching broad input errors behaves sensibly;
    ``BaseAgent`` reports it as a refusal with status ``invalid_input``.
    """

    def __init__(self, model: type[BaseModel], error: ValidationError) -> None:
        self.model = model.__name__
        self.errors = [
            {"field": ".".join(str(p) for p in e.get("loc", ())), "reason": e.get("msg", "")}
            for e in error.errors()
        ]
        detail = "; ".join(f"{e['field'] or '<root>'}: {e['reason']}" for e in self.errors)
        super().__init__(f"context does not match {self.model}: {detail}")


#: The context of the execution running on this task, as the coordinator sent
#: it. A context variable for the same reason the scope grant is one: an
#: author should be able to call :func:`inputs` from inside a tool without the
#: context having been threaded down to it.
_current: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "agentic_bus_execution_context", default=None
)


def inputs(model: type[M], context: dict[str, Any] | None = None) -> M:
    """The execution's context as an instance of *model*.

    Reads the running execution's context unless *context* is given — pass it
    explicitly in a test that calls ``execute_task`` directly. Raises
    :class:`InvalidInput` when the shape does not match.

    Outside an execution, with nothing passed, this validates an empty object:
    a model whose fields all have defaults builds; one with a required field
    raises, which is the truthful answer when there is no input at all.
    """
    data = context if context is not None else (_current.get() or {})
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise InvalidInput(model, exc) from exc


def set_context(context: dict[str, Any] | None) -> contextvars.Token:
    """Install the execution's context. Close with :func:`reset_context`.

    Called by ``BaseAgent`` around ``execute_task``; agents do not call it.
    """
    return _current.set(dict(context or {}))


def reset_context(token: contextvars.Token) -> None:
    _current.reset(token)
