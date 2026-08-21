"""OpenTelemetry instrumentation for Agentic Bus (§5 of AGENTS.md).

Every Agentic Bus message propagates ``trace_id`` and ``span_id``.
Coordinator spans form the root of each intent-execution trace.

Instrumented layers:
- WebSocket message handling
- Intent lifecycle
- Negotiation
- Graph execution
- Agent calls
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span, StatusCode

from agentic_bus.core.protocol.envelope import TraceContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider bootstrap
# ---------------------------------------------------------------------------

_provider: TracerProvider | None = None


def init_telemetry(service_name: str = "agentic-bus") -> TracerProvider:
    """Initialise a global TracerProvider with a console exporter.

    In production, replace the exporter with an OTLP exporter pointing at a
    Jaeger / Tempo / etc. backend.
    """
    global _provider
    _provider = TracerProvider()
    exporter = ConsoleSpanExporter()
    _provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(_provider)
    logger.info("OpenTelemetry initialised for service=%s", service_name)
    return _provider


def get_tracer(name: str = "agbus") -> trace.Tracer:
    return trace.get_tracer(name)


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------

@contextmanager
def agbus_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Generator[Span, None, None]:
    """Create a traced span for an Agentic Bus operation."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


def inject_trace_context() -> TraceContext:
    """Build a ``TraceContext`` from the current active span."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id:
        return TraceContext(
            trace_id=format(ctx.trace_id, "032x"),
            span_id=format(ctx.span_id, "016x"),
        )
    return TraceContext()
