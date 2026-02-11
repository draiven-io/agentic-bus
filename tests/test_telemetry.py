"""Tests for OpenTelemetry instrumentation."""

from app.core.telemetry.tracing import (
    init_telemetry,
    agbus_span,
    inject_trace_context,
)


class TestTelemetry:
    def test_init_telemetry(self):
        provider = init_telemetry("test-service")
        assert provider is not None

    def test_agbus_span_context(self):
        init_telemetry("test-service")
        with agbus_span("test.operation", attributes={"key": "value"}) as span:
            assert span is not None
            ctx = inject_trace_context()
            assert ctx.trace_id  # should have a valid trace_id inside a span

    def test_inject_outside_span(self):
        """Outside a span, trace context should be empty or zero."""
        ctx = inject_trace_context()
        # May be empty or zero-padded depending on provider state
        assert isinstance(ctx.trace_id, str)
