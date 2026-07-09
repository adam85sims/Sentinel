"""OpenTelemetry trace export for Sentinel.

Converts AgentTrace structures into OTel-compatible span data that
can be exported to any OTLP collector (Jaeger, Grafana Tempo, Honeycomb, etc.).

Designed to work WITHOUT requiring the opentelemetry-sdk package at import
time — the heavy dependency is only needed when actually exporting. This
module defines the span data structures and conversion logic; the actual
OTLP export uses the standard OTel SDK only when available.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sentinel.models import AgentTrace

# ──────────────────────────────────────────────────────
# Span data model (lightweight, no OTel SDK dependency)
# ──────────────────────────────────────────────────────


@dataclass
class SpanAttribute:
    """A key-value attribute on a span."""

    key: str
    value: Any


@dataclass
class SpanEvent:
    """An event within a span (timestamped annotation)."""

    name: str
    timestamp_ns: int  # nanoseconds since epoch
    attributes: list[SpanAttribute] = field(default_factory=list)


@dataclass
class OTelSpan:
    """OTel-compatible span representation.

    This is our lightweight representation that doesn't require the
    opentelemetry-sdk. Can be serialized to JSON for inspection or
    converted to real OTel spans when the SDK is available.
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str  # "internal", "client", "server", "producer", "consumer"
    start_time_ns: int
    end_time_ns: int
    status: str  # "OK", "ERROR", "UNSET"
    attributes: list[SpanAttribute] = field(default_factory=list)
    events: list[SpanEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON export."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "kind": self.kind,
            "start_time_ns": self.start_time_ns,
            "end_time_ns": self.end_time_ns,
            "duration_ms": (self.end_time_ns - self.start_time_ns) / 1e6,
            "status": self.status,
            "attributes": {a.key: a.value for a in self.attributes},
            "events": [
                {
                    "name": e.name,
                    "timestamp_ns": e.timestamp_ns,
                    "attributes": {a.key: a.value for a in e.attributes},
                }
                for e in self.events
            ],
        }


# ──────────────────────────────────────────────────────
# Conversion: AgentTrace → OTelSpans
# ──────────────────────────────────────────────────────


def _ns_from_timestamp(ts: float) -> int:
    """Convert seconds-since-epoch float to nanoseconds."""
    return int(ts * 1e9)


def _short_id() -> str:
    """Generate a 16-char hex ID (64-bit) for span/trace IDs."""
    return uuid4().hex[:16]


def trace_to_spans(
    trace: AgentTrace,
    trace_id: str | None = None,
    service_name: str = "sentinel-agent",
) -> list[OTelSpan]:
    """Convert an AgentTrace into a list of OTel-compatible spans.

    The resulting span hierarchy:
        Root span (agent run)
          ├── Step spans (one per step)
          │     └── Tool call spans (nested under steps)
          └── Error event spans

    Args:
        trace: The AgentTrace to convert.
        trace_id: Optional trace ID (generated if not provided).
        service_name: The service name for the root span.

    Returns:
        List of OTelSpan objects ready for export.
    """
    trace_id = trace_id or _short_id()
    spans: list[OTelSpan] = []

    # Root span: the entire agent run
    root_span_id = _short_id()
    root_start = _ns_from_timestamp(trace._start_time)
    root_end = _ns_from_timestamp(trace._end_time or time.time())

    root_status = "OK"
    if trace.errors:
        unrecoverable = [e for e in trace.errors if not e.recoverable]
        if unrecoverable:
            root_status = "ERROR"

    root_attrs = [
        SpanAttribute("service.name", service_name),
        SpanAttribute("sentinel.total_steps", trace.total_steps),
        SpanAttribute("sentinel.total_tool_calls", trace.total_tool_calls),
        SpanAttribute("sentinel.tool_names", trace.tool_names_called),
        SpanAttribute("sentinel.state_changes", len(trace.state_changes)),
        SpanAttribute("sentinel.errors", len(trace.errors)),
    ]
    if trace.metadata:
        for k, v in trace.metadata.items():
            root_attrs.append(SpanAttribute(f"sentinel.metadata.{k}", v))

    spans.append(
        OTelSpan(
            trace_id=trace_id,
            span_id=root_span_id,
            parent_span_id=None,
            name=f"{service_name}.run",
            kind="internal",
            start_time_ns=root_start,
            end_time_ns=root_end,
            status=root_status,
            attributes=root_attrs,
        )
    )

    # Step spans
    for step in trace.steps:
        step_span_id = _short_id()
        step_start = _ns_from_timestamp(
            step.tool_calls[0].timestamp if step.tool_calls else trace._start_time
        )
        # Approximate step end: start + duration or next step start
        step_end = step_start + int(step.duration_ms * 1e6) if step.duration_ms else step_start + 1

        step_status = "ERROR" if step.error else "OK"

        step_attrs = [
            SpanAttribute("sentinel.step.id", step.step_id),
            SpanAttribute("sentinel.step.action", step.action.value),
        ]
        if step.duration_ms:
            step_attrs.append(SpanAttribute("sentinel.step.duration_ms", step.duration_ms))

        step_events: list[SpanEvent] = []
        if step.error:
            step_events.append(
                SpanEvent(
                    name="error",
                    timestamp_ns=step_start,
                    attributes=[
                        SpanAttribute("error.message", step.error.message),
                        SpanAttribute("error.severity", step.error.severity.value),
                        SpanAttribute("error.recoverable", step.error.recoverable),
                    ],
                )
            )

        spans.append(
            OTelSpan(
                trace_id=trace_id,
                span_id=step_span_id,
                parent_span_id=root_span_id,
                name=f"{service_name}.step.{step.action.value}",
                kind="internal",
                start_time_ns=step_start,
                end_time_ns=step_end,
                status=step_status,
                attributes=step_attrs,
                events=step_events,
            )
        )

        # Tool call spans (nested under step)
        for tc in step.tool_calls:
            tc_span_id = _short_id()
            tc_start = _ns_from_timestamp(tc.timestamp)
            tc_end = tc_start + int(tc.duration_ms * 1e6) if tc.duration_ms else tc_start + 1

            tc_attrs = [
                SpanAttribute("sentinel.tool.name", tc.tool_name),
                SpanAttribute("sentinel.tool.arguments", tc.arguments),
                SpanAttribute("sentinel.tool.succeeded", tc.succeeded),
            ]
            if tc.duration_ms:
                tc_attrs.append(SpanAttribute("sentinel.tool.duration_ms", tc.duration_ms))

            tc_status = "ERROR" if not tc.succeeded else "OK"

            tc_events: list[SpanEvent] = []
            if tc.error:
                tc_events.append(
                    SpanEvent(
                        name="error",
                        timestamp_ns=tc_start,
                        attributes=[
                            SpanAttribute("error.message", tc.error),
                        ],
                    )
                )
            if tc.result is not None:
                # Record result as event (don't put large payloads in attributes)
                tc_events.append(
                    SpanEvent(
                        name="tool_result",
                        timestamp_ns=tc_end,
                        attributes=[
                            SpanAttribute("result.type", type(tc.result).__name__),
                        ],
                    )
                )

            spans.append(
                OTelSpan(
                    trace_id=trace_id,
                    span_id=tc_span_id,
                    parent_span_id=step_span_id,
                    name=f"{service_name}.tool.{tc.tool_name}",
                    kind="client",
                    start_time_ns=tc_start,
                    end_time_ns=tc_end,
                    status=tc_status,
                    attributes=tc_attrs,
                    events=tc_events,
                )
            )

    return spans


# ──────────────────────────────────────────────────────
# Export to real OTel SDK (when available)
# ──────────────────────────────────────────────────────


def export_to_otel(
    trace: AgentTrace,
    service_name: str = "sentinel-agent",
    endpoint: str | None = None,
) -> bool:
    """Export an AgentTrace to an OTLP collector using the real OTel SDK.

    Requires: opentelemetry-sdk, opentelemetry-exporter-otlp

    Args:
        trace: The AgentTrace to export.
        service_name: Service name for the OTel resource.
        endpoint: OTLP collector endpoint (e.g., "http://localhost:4317").
                  If None, uses OTLP_EXPORTER_ENDPOINT env var or default.

    Returns:
        True if export succeeded, False if SDK not available or export failed.
    """
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return False

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
        except ImportError:
            return False

    import os

    endpoint = endpoint or os.environ.get("OTLP_EXPORTER_ENDPOINT", "http://localhost:4317")

    # Build resource and provider
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)

    tracer = otel_trace.get_tracer(service_name)

    # Convert and emit spans
    otel_spans = trace_to_spans(trace, service_name=service_name)

    for span_data in otel_spans:
        with tracer.start_as_current_span(
            span_data.name,
            kind=_otel_kind(span_data.kind),
            start_time=span_data.start_time_ns,
        ) as span:
            # Set attributes
            for attr in span_data.attributes:
                span.set_attribute(attr.key, attr.value)

            # Set events
            for event in span_data.events:
                attrs = {}
                for a in event.attributes:
                    attrs[a.key] = a.value
                span.add_event(event.name, timestamp=event.timestamp_ns // 1000000, attributes=attrs)

            # Set status
            if span_data.status == "ERROR":
                span.set_status(otel_trace.StatusCode.ERROR)
            elif span_data.status == "OK":
                span.set_status(otel_trace.StatusCode.OK)

    # Force flush
    provider.shutdown()
    return True


def _otel_kind(kind_str: str) -> Any:
    """Convert our kind string to OTel SpanKind enum."""
    try:
        from opentelemetry import trace as otel_trace
        kind_map = {
            "internal": otel_trace.SpanKind.INTERNAL,
            "client": otel_trace.SpanKind.CLIENT,
            "server": otel_trace.SpanKind.SERVER,
            "producer": otel_trace.SpanKind.PRODUCER,
            "consumer": otel_trace.SpanKind.CONSUMER,
        }
        return kind_map.get(kind_str, otel_trace.SpanKind.INTERNAL)
    except ImportError:
        return None
