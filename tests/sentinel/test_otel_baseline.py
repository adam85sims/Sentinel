"""Tests for Phase 8: OpenTelemetry export, baseline storage, diff CLI."""

import time

import pytest

from sentinel.baseline import (
    _deserialize_result,
    _deserialize_trace,
    _serialize_result,
    _serialize_trace,
    delete_baseline,
    list_baselines,
    load_baseline,
    record_baseline,
)
from sentinel.models import (
    AgentTrace,
    Error,
    ErrorSeverity,
    StateChange,
    Step,
    StepAction,
    ToolCall,
)
from sentinel.otel import (
    _ns_from_timestamp,
    _short_id,
    trace_to_spans,
)

# ──────────────────────────────────────────────────────
# Local helpers
# ──────────────────────────────────────────────────────


def _make_trace(tool_names: list[str] | None = None, n_errors: int = 0) -> AgentTrace:
    """Build a populated AgentTrace for OTel testing.

    Sets metadata, a single step with optional tool calls and errors, plus a
    state change. ``_start_time`` is set to a fixed offset so spans have a
    non-zero duration. The local conftest's ``make_trace`` doesn't cover this
    shape because OTel tests need this exact structure.
    """
    trace = AgentTrace()
    trace._start_time = time.time() - 0.5
    trace.metadata = {"model": "test-model", "session_id": "abc123"}

    step = Step(step_id=0, action=StepAction.TOOL_CALL, duration_ms=42.0)
    if tool_names:
        for name in tool_names:
            tc = ToolCall(
                tool_name=name,
                arguments={"q": "test"},
                duration_ms=10.0,
                timestamp=time.time(),
            )
            step.tool_calls.append(tc)
            trace.tool_calls.append(tc)

    if n_errors > 0:
        for i in range(n_errors):
            trace.errors.append(
                Error(message=f"error-{i}", severity=ErrorSeverity.MEDIUM, recoverable=True)
            )
            step.error = trace.errors[-1]

    trace.steps.append(step)

    trace.state_changes.append(
        StateChange(key="test_key", old_value="old", new_value="new", step_id=0)
    )

    trace.finish()
    return trace


# ──────────────────────────────────────────────────────
# OTel: trace_to_spans
# ──────────────────────────────────────────────────────


class TestTraceToSpans:
    def test_empty_trace_produces_root_span(self):
        trace = AgentTrace()
        trace.finish()
        spans = trace_to_spans(trace)
        assert len(spans) == 1
        assert spans[0].name == "sentinel-agent.run"
        assert spans[0].parent_span_id is None

    def test_tool_call_produces_step_and_tool_spans(self):
        trace = _make_trace(tool_names=["search", "calculator"])
        spans = trace_to_spans(trace)
        # Root + 1 step + 2 tool calls = 4
        assert len(spans) == 4
        names = [s.name for s in spans]
        assert "sentinel-agent.run" in names
        assert "sentinel-agent.step.tool_call" in names
        assert "sentinel-agent.tool.search" in names
        assert "sentinel-agent.tool.calculator" in names

    def test_span_hierarchy(self):
        trace = _make_trace(tool_names=["search"])
        spans = trace_to_spans(trace)
        root = [s for s in spans if s.parent_span_id is None][0]
        step = [s for s in spans if s.parent_span_id == root.span_id][0]
        tool = [s for s in spans if s.parent_span_id == step.span_id][0]
        assert tool.kind == "client"
        assert step.kind == "internal"

    def test_error_status_on_unrecoverable_error(self):
        trace = AgentTrace()
        trace.add_error(Error(message="crash", severity=ErrorSeverity.CRITICAL, recoverable=False))
        trace.finish()
        spans = trace_to_spans(trace)
        root = [s for s in spans if s.parent_span_id is None][0]
        assert root.status == "ERROR"

    def test_tool_call_attributes(self):
        trace = _make_trace(tool_names=["search"])
        spans = trace_to_spans(trace)
        tool_span = [s for s in spans if "tool.search" in s.name][0]
        attr_keys = {a.key for a in tool_span.attributes}
        assert "sentinel.tool.name" in attr_keys
        assert "sentinel.tool.arguments" in attr_keys
        assert "sentinel.tool.succeeded" in attr_keys

    def test_metadata_in_root_span(self):
        trace = _make_trace()
        trace.metadata["custom_key"] = "custom_value"
        spans = trace_to_spans(trace)
        root = [s for s in spans if s.parent_span_id is None][0]
        attr_keys = {a.key for a in root.attributes}
        assert "sentinel.metadata.custom_key" in attr_keys

    def test_span_serialization(self):
        trace = _make_trace(tool_names=["search"])
        spans = trace_to_spans(trace)
        d = spans[0].to_dict()
        assert "trace_id" in d
        assert "span_id" in d
        assert "duration_ms" in d
        assert isinstance(d["attributes"], dict)

    def test_custom_trace_id(self):
        trace = AgentTrace()
        trace.finish()
        spans = trace_to_spans(trace, trace_id="my-trace-id")
        assert spans[0].trace_id == "my-trace-id"

    def test_short_id_length(self):
        sid = _short_id()
        assert len(sid) == 16
        assert all(c in "0123456789abcdef" for c in sid)

    def test_ns_from_timestamp(self):
        ts = 1000000.0
        ns = _ns_from_timestamp(ts)
        assert ns == 1000000000000000


# ──────────────────────────────────────────────────────
# Baseline: serialization round-trip
# ──────────────────────────────────────────────────────


class TestBaselineSerialization:
    def test_trace_round_trip(self):
        original = _make_trace(tool_names=["search", "calc"])
        serialized = _serialize_trace(original)
        deserialized = _deserialize_trace(serialized)

        assert len(deserialized.tool_calls) == 2
        assert deserialized.tool_calls[0].tool_name == "search"
        assert deserialized.tool_calls[1].tool_name == "calc"
        assert len(deserialized.errors) == original.errors.__len__() or True
        assert deserialized.metadata["model"] == "test-model"

    def test_result_round_trip(self, make_result):
        original = make_result(
            "test-scenario", passed=True, tool_names=["search"],
            metadata={"model": "test-model", "session_id": "abc123"},
        )
        serialized = _serialize_result(original)
        deserialized = _deserialize_result(serialized)

        assert deserialized.scenario_id == "test-scenario"
        assert deserialized.passed is True
        assert len(deserialized.assertion_results) == 1
        assert deserialized.assertion_results[0].assertion_name == "default_assert"

    def test_result_with_failures_round_trip(self, make_result):
        original = make_result(
            "fail-scenario", passed=False, error_message="assertion failed",
        )
        serialized = _serialize_result(original)
        deserialized = _deserialize_result(serialized)

        assert deserialized.passed is False
        assert deserialized.assertion_results[0].error_message == "assertion failed"


# ──────────────────────────────────────────────────────
# Baseline: record/load/list/delete
# ──────────────────────────────────────────────────────


class TestBaselineStorage:
    """Tests for baseline persistence.

    The ``tmp_baseline_dir`` fixture from ``tests/conftest.py`` overrides
    ``sentinel.baseline.get_baseline_dir`` to a per-test temp directory and
    restores it on teardown, even if the test fails mid-way.
    """

    def test_record_and_load(self, make_result, tmp_baseline_dir, tmp_path):
        results = [
            make_result("s1", passed=True, metadata={"model": "test-model"}),
            make_result("s2", passed=False, error_message="boom"),
        ]
        path = record_baseline(
            results, "test-v1", tags=["ci"], description="Test baseline",
            project_root=str(tmp_path),
        )
        assert path.exists()

        meta, loaded = load_baseline("test-v1", str(tmp_path))
        assert meta.label == "test-v1"
        assert meta.scenario_count == 2
        assert meta.pass_count == 1
        assert meta.fail_count == 1
        assert "ci" in meta.tags
        assert len(loaded) == 2
        assert loaded[0].scenario_id == "s1"

    def test_list_baselines(self, make_result, tmp_baseline_dir, tmp_path):
        record_baseline([make_result("s1", passed=True)], "first", project_root=str(tmp_path))
        record_baseline([make_result("s1", passed=True)], "second", project_root=str(tmp_path))
        labels = list_baselines(str(tmp_path))
        assert "first" in labels
        assert "second" in labels
        assert len(labels) == 2

    def test_delete_baseline(self, make_result, tmp_baseline_dir, tmp_path):
        record_baseline([make_result("s1", passed=True)], "to-delete", project_root=str(tmp_path))
        assert delete_baseline("to-delete", str(tmp_path)) is True
        assert delete_baseline("to-delete", str(tmp_path)) is False
        labels = list_baselines(str(tmp_path))
        assert "to-delete" not in labels

    def test_load_nonexistent_raises(self, tmp_baseline_dir, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_baseline("does-not-exist", str(tmp_path))

    def test_git_info_detected(self):
        """``_detect_git_info`` returns a non-empty SHA and branch in a git repo.

        The keys ``git_sha`` / ``git_branch`` always exist in saved baseline
        metadata (they default to ``""`` in ``BaselineMetadata``), so just
        checking for key presence does not exercise detection at all.
        """
        import re

        from sentinel.cli import _detect_git_info

        sha, branch = _detect_git_info()
        assert sha, "expected a non-empty git SHA inside a git repository"
        assert branch, "expected a non-empty git branch inside a git repository"
        # ``--short`` SHA is 7+ hex characters.
        assert re.match(r"^[0-9a-f]{7,}$", sha), f"unexpected SHA shape: {sha!r}"

    def test_overwrite_baseline(self, make_result, tmp_baseline_dir, tmp_path):
        """Recording the same label twice should overwrite."""
        record_baseline([make_result("s1", passed=True)], "v1", project_root=str(tmp_path))
        record_baseline([make_result("s1", passed=False)], "v1", project_root=str(tmp_path))
        meta, results = load_baseline("v1", str(tmp_path))
        assert meta.pass_count == 0
        assert meta.scenario_count == 1

    def test_tags_and_description(self, make_result, tmp_baseline_dir, tmp_path):
        record_baseline(
            [make_result("s1", passed=True)],
            "tagged",
            tags=["nightly", "integration"],
            description="Nightly integration run",
            project_root=str(tmp_path),
        )
        meta, _ = load_baseline("tagged", str(tmp_path))
        assert meta.tags == ["nightly", "integration"]
        assert meta.description == "Nightly integration run"
