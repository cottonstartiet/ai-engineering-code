import pytest
from opentelemetry import propagate
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from support_demo import telemetry


def test_safe_error_spans_and_queue_trace_propagation(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    monkeypatch.setattr(telemetry, "tracer", tracer)
    with telemetry.span("api"):
        carrier = {}
        propagate.inject(carrier)
        with tracer.start_as_current_span("worker", context=propagate.extract(carrier)):
            with pytest.raises(ValueError):
                with telemetry.span("tool"):
                    raise ValueError("private customer text must never appear in telemetry")
    spans = exporter.get_finished_spans()
    assert len({s.context.trace_id for s in spans}) == 1
    tool = next(s for s in spans if s.name == "tool")
    assert tool.status.status_code == StatusCode.ERROR
    assert tool.attributes["error.type"] == "ValueError"
    assert not tool.events and tool.status.description is None
    assert "private customer" not in repr(spans)
    provider.shutdown()
