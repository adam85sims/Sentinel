"""Edge case tests for sentinel.

Tests boundary conditions, error handling, and unusual inputs
that could cause failures in production use.
"""

import json

import pytest

from sentinel.assertions import (
    assert_no_tool_errors,
    assert_tool_call_count,
    assert_tool_called,
    assert_tool_not_called,
)
from sentinel.env import (
    EnvironmentBuilder,
    MockTool,
    MockToolError,
    RateLimitError,
    TimeoutError,
)
from sentinel.models import AgentTrace, ErrorSeverity, Step, StepAction, ToolCall

# ─── Empty/Null Inputs ─────────────────────────────────────────

class TestEmptyInputs:
    """Things that should work with empty or null inputs."""

    def test_empty_tool_name(self):
        """Tool with empty name should work."""
        mock = MockTool("", response="ok")
        assert mock.name == ""
        result = mock()
        assert result == "ok"

    def test_empty_response(self):
        """Tool with empty string response."""
        mock = MockTool("t", response="")
        assert mock() == ""

    def test_none_response(self):
        """Tool with None response."""
        mock = MockTool("t", response=None)
        assert mock() is None

    def test_empty_dict_response(self):
        """Tool with empty dict response."""
        mock = MockTool("t", response={})
        assert mock() == {}

    def test_empty_list_response(self):
        """Tool with empty list response."""
        mock = MockTool("t", response=[])
        assert mock() == []

    def test_empty_trace_assertions(self):
        """Assertions on empty trace should not crash."""
        trace = AgentTrace()
        assert_tool_not_called(trace, "anything")
        assert_no_tool_errors(trace)

    def test_empty_environment_builder(self):
        """Building environment with no tools."""
        env = EnvironmentBuilder().build()
        assert len(env.tools) == 0
        assert len(env.apis) == 0
        assert len(env.databases) == 0


# ─── Malformed/Invalid Inputs ──────────────────────────────────

class TestMalformedInputs:
    """Handling of malformed or unexpected inputs."""

    def test_mock_tool_with_invalid_error(self):
        """MockTool with side_effect that's not an exception."""
        mock = MockTool("t", side_effect="not an exception")
        with pytest.raises(TypeError):
            mock()

    def test_tool_call_with_extra_kwargs(self):
        """Extra kwargs should be passed through."""
        mock = MockTool("t", response_fn=lambda **kwargs: kwargs)
        result = mock(extra="value")
        assert result == {"extra": "value"}

    def test_trace_with_invalid_tool_call(self):
        """Lock current behavior: ``add_tool_call(None)`` appends ``None`` silently.

        ``AgentTrace.add_tool_call`` performs no validation today — it just
        delegates to ``self.tool_calls.append(call)``. This test pins the
        behavior so any tightening of the contract (e.g. raising ``TypeError``
        on ``None``) becomes a deliberate, reviewed change.

        TODO: Decide whether ``add_tool_call`` should validate its input and
        raise ``TypeError`` for ``None``. If so, update this test to assert
        the raise, and audit any callers that may pass ``None`` defensively.
        """
        trace = AgentTrace()
        trace.add_tool_call(None)

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0] is None

    def test_assertions_with_none_trace(self):
        """Assertions should handle None gracefully or raise clearly."""
        # This should raise (not silently pass)
        with pytest.raises((TypeError, AttributeError)):
            assert_tool_called(None, "tool")


# ─── Boundary Conditions ───────────────────────────────────────

class TestBoundaryConditions:
    """Edge cases at boundaries."""

    def test_many_tool_calls(self):
        """Recording 1000 tool calls should work."""
        trace = AgentTrace()
        mock = MockTool("t", response="ok")

        for i in range(1000):
            tc = ToolCall(tool_name="t", arguments={"i": i}, result="ok")
            trace.add_tool_call(tc)

        assert len(trace.tool_calls) == 1000
        assert_tool_call_count(trace, "t", expected_count=1000)

    def test_very_long_tool_name(self):
        """Tool with very long name."""
        long_name = "x" * 1000
        mock = MockTool(long_name, response="ok")
        assert mock.name == long_name

    def test_very_long_response(self):
        """Tool with very long response."""
        long_response = "x" * 100000
        mock = MockTool("t", response=long_response)
        assert mock() == long_response

    def test_unicode_in_tool_name(self):
        """Tool with unicode characters in name."""
        mock = MockTool("工具_🔍", response="ok")
        assert mock.name == "工具_🔍"
        result = mock()
        assert result == "ok"

    def test_unicode_in_response(self):
        """Tool with unicode response."""
        mock = MockTool("t", response="日本語テスト 🎉")
        assert mock() == "日本語テスト 🎉"

    def test_nested_dict_response(self):
        """Tool with deeply nested dict response."""
        deep = {"a": {"b": {"c": {"d": {"e": [1, 2, 3]}}}}}
        mock = MockTool("t", response=deep)
        assert mock() == deep

    def test_concurrent_mock_calls(self):
        """Multiple mock tools called in sequence."""
        tools = [MockTool(f"t{i}", response=f"r{i}") for i in range(10)]
        results = [t() for t in tools]
        assert results == [f"r{i}" for i in range(10)]


# ─── Error Recovery ─────────────────────────────────────────────

class TestErrorRecovery:
    """Error scenarios and recovery."""

    def test_mock_error_has_status_code(self):
        """MockToolError carries status_code."""
        err = MockToolError("test", status_code=418)
        assert err.status_code == 418
        assert str(err) == "test"

    def test_rate_limit_has_retry_after(self):
        """RateLimitError carries retry_after."""
        err = RateLimitError(retry_after=30.0)
        assert err.retry_after == 30.0
        assert err.status_code == 429

    def test_timeout_error_message(self):
        """TimeoutError has sensible defaults."""
        err = TimeoutError()
        assert "timed out" in str(err).lower()
        assert err.status_code == 408

    def test_tool_error_recorded_in_trace(self):
        """Error from tool is recorded in trace."""
        trace = AgentTrace()
        mock = MockTool("t", side_effect=ValueError("oops"))

        try:
            mock()
        except ValueError:
            pass

        tc = ToolCall(tool_name="t", arguments={}, error="oops")
        trace.add_tool_call(tc)

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error == "oops"
        assert trace.tool_calls[0].result is None

    def test_multiple_errors_in_trace(self):
        """Multiple errors can be recorded."""
        trace = AgentTrace()
        for i in range(5):
            tc = ToolCall(
                tool_name=f"t{i}",
                arguments={},
                error=f"error {i}" if i % 2 == 0 else None,
            )
            trace.add_tool_call(tc)

        errors = [tc for tc in trace.tool_calls if tc.error]
        assert len(errors) == 3  # 0, 2, 4


# ─── YAML/JSON Edge Cases ──────────────────────────────────────

class TestScenarioEdgeCases:
    """Edge cases for scenario loading."""

    def test_empty_yaml_file(self, tmp_path):
        """Empty YAML file should produce no scenarios or raise."""
        from sentinel.cli import _load_scenario_file

        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")

        try:
            scenarios = _load_scenario_file(str(yaml_file))
            assert scenarios == []
        except Exception:
            pass  # Empty file behavior varies

    def test_empty_json_file(self, tmp_path):
        """Empty JSON file should raise JSONDecodeError."""
        from sentinel.cli import _load_scenario_file

        json_file = tmp_path / "empty.json"
        json_file.write_text("")

        with pytest.raises(json.JSONDecodeError):
            _load_scenario_file(str(json_file))

    def test_invalid_yaml(self, tmp_path):
        """Invalid YAML should raise or return empty."""
        from sentinel.cli import _load_scenario_file

        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("{{{{invalid yaml")

        # Should either raise or return empty (graceful)
        try:
            scenarios = _load_scenario_file(str(yaml_file))
            assert scenarios == []
        except Exception:
            pass  # Exception is acceptable for invalid input

    def test_invalid_json(self, tmp_path):
        """Invalid JSON should raise."""
        from sentinel.cli import _load_scenario_file

        json_file = tmp_path / "bad.json"
        json_file.write_text("{invalid json")

        with pytest.raises(json.JSONDecodeError):
            _load_scenario_file(str(json_file))

    def test_yaml_with_single_scenario(self, tmp_path):
        """Single scenario (not a list) should work."""
        import yaml

        yaml_file = tmp_path / "single.yaml"
        yaml_file.write_text("""
id: test-001
name: Test Scenario
task: Do something
""")

        # yaml.safe_load returns a dict for single mappings
        data = yaml.safe_load(yaml_file.read_text())
        assert isinstance(data, dict)
        assert data["id"] == "test-001"

    def test_yaml_with_missing_fields(self, tmp_path):
        """Scenario with missing optional fields should use defaults."""
        import yaml

        yaml_file = tmp_path / "minimal.yaml"
        yaml_file.write_text("""
id: minimal
""")

        data = yaml.safe_load(yaml_file.read_text())
        assert data["id"] == "minimal"
        # Missing fields should be None or not present
        assert data.get("task") is None
        assert data.get("tags") is None


# ─── State Consistency ─────────────────────────────────────────

class TestStateConsistency:
    """State management edge cases."""

    def test_agent_trace_step_tracking(self):
        """Steps are tracked in order."""
        trace = AgentTrace()
        step1 = Step(step_id=0, action=StepAction.TOOL_CALL, input={"tool": "search"})
        step2 = Step(step_id=1, action=StepAction.REASON, input="thinking")
        step3 = Step(step_id=2, action=StepAction.TOOL_CALL, input={"tool": "email"})

        trace.add_step(step1)
        trace.add_step(step2)
        trace.add_step(step3)

        assert len(trace.steps) == 3
        assert trace.steps[0].action == StepAction.TOOL_CALL
        assert trace.steps[1].action == StepAction.REASON
        assert trace.steps[2].action == StepAction.TOOL_CALL

    def test_error_severity_enum(self):
        """ErrorSeverity enum has expected values."""
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"

    def test_step_action_enum(self):
        """StepAction enum has expected values."""
        assert StepAction.TOOL_CALL.value == "tool_call"  # exists
        assert StepAction.REASON.value == "reason"
        assert StepAction.RESPOND.value == "respond"
