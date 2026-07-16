"""Tests for Sentinel behavioral assertions."""

import pytest

from sentinel.assertions import (
    assert_graceful_degradation,
    assert_no_silent_failure,
    assert_no_tool_errors,
    assert_permission_respected,
    assert_permission_violated,
    assert_state_changed,
    assert_state_consistent,
    assert_tool_call_count,
    assert_tool_call_order,
    assert_tool_called,
    assert_tool_not_called,
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

# ──────────────────────────────────────────────────────
# Tool Call Assertions
# ──────────────────────────────────────────────────────


class TestAssertToolCalled:
    def test_passes_when_tool_called(self, make_trace):
        trace = make_trace(
            tool_calls=[ToolCall(tool_name="search", arguments={"q": "test"})]
        )
        assert_tool_called(trace, "search")  # Should not raise

    def test_fails_when_tool_not_called(self, make_trace):
        trace = make_trace()
        with pytest.raises(AssertionError, match="never invoked"):
            assert_tool_called(trace, "search")

    def test_passes_when_arguments_match(self, make_trace):
        trace = make_trace(
            tool_calls=[ToolCall(tool_name="search", arguments={"q": "test"})]
        )
        assert_tool_called(trace, "search", q="test")

    def test_fails_when_arguments_dont_match(self, make_trace):
        trace = make_trace(
            tool_calls=[ToolCall(tool_name="search", arguments={"q": "test"})]
        )
        with pytest.raises(AssertionError, match="no call matched"):
            assert_tool_called(trace, "search", q="wrong")

    def test_partial_argument_match(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(
                    tool_name="search",
                    arguments={"q": "test", "limit": 10},
                )
            ]
        )
        # Partial match — only checking q
        assert_tool_called(trace, "search", q="test")


class TestAssertToolNotCalled:
    def test_passes_when_tool_not_called(self, make_trace):
        trace = make_trace()
        assert_tool_not_called(trace, "delete_account")

    def test_fails_when_tool_called(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(tool_name="delete_account", arguments={})
            ]
        )
        with pytest.raises(AssertionError, match="should NOT have been called"):
            assert_tool_not_called(trace, "delete_account")


class TestAssertToolCallOrder:
    def test_passes_correct_order(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}),
                ToolCall(tool_name="lookup", arguments={}),
                ToolCall(tool_name="email", arguments={}),
            ]
        )
        assert_tool_call_order(trace, ["search", "lookup", "email"])

    def test_passes_with_extra_calls_between(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}),
                ToolCall(tool_name="log", arguments={}),  # extra
                ToolCall(tool_name="lookup", arguments={}),
                ToolCall(tool_name="email", arguments={}),
            ]
        )
        assert_tool_call_order(trace, ["search", "lookup", "email"])

    def test_fails_wrong_order(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(tool_name="email", arguments={}),
                ToolCall(tool_name="search", arguments={}),
            ]
        )
        with pytest.raises(AssertionError, match="Expected tool call order"):
            assert_tool_call_order(trace, ["search", "email"])


class TestAssertToolCallCount:
    def test_passes_correct_count(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}),
                ToolCall(tool_name="search", arguments={}),
            ]
        )
        assert_tool_call_count(trace, "search", 2)

    def test_fails_wrong_count(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}),
            ]
        )
        with pytest.raises(AssertionError, match="to be called 2 times.*was called 1"):
            assert_tool_call_count(trace, "search", 2)


class TestAssertNoToolErrors:
    def test_passes_when_no_errors(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}, result="ok")
            ]
        )
        assert_no_tool_errors(trace)

    def test_fails_when_errors_exist(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(
                    tool_name="search", arguments={}, error="timeout"
                )
            ]
        )
        with pytest.raises(AssertionError, match="tool call.*failed"):
            assert_no_tool_errors(trace)


# ──────────────────────────────────────────────────────
# State Assertions
# ──────────────────────────────────────────────────────


class TestAssertStateConsistent:
    def test_passes_when_state_matches(self, make_trace):
        trace = make_trace(
            state_changes=[
                StateChange(key="user_id", old_value=None, new_value="123")
            ]
        )
        assert_state_consistent(trace, "user_id", expected="123")

    def test_fails_when_state_dismatched(self, make_trace):
        trace = make_trace(
            state_changes=[
                StateChange(key="user_id", old_value=None, new_value="456")
            ]
        )
        with pytest.raises(AssertionError, match="to be '123'.*got '456'"):
            assert_state_consistent(trace, "user_id", expected="123")

    def test_passes_when_no_key_and_no_expectation(self, make_trace):
        trace = make_trace()
        assert_state_consistent(trace, "nonexistent")


class TestAssertStateChanged:
    def test_passes_when_key_changed(self, make_trace):
        trace = make_trace(
            state_changes=[
                StateChange(key="status", old_value="pending", new_value="done")
            ]
        )
        assert_state_changed(trace, "status")

    def test_fails_when_key_never_changed(self, make_trace):
        trace = make_trace()
        with pytest.raises(AssertionError, match="to be modified"):
            assert_state_changed(trace, "status")


# ──────────────────────────────────────────────────────
# Governance Assertions
# ──────────────────────────────────────────────────────


class TestAssertPermissionRespected:
    def test_passes_when_approved_tool_called(self, make_trace):
        trace = make_trace(
            tool_calls=[ToolCall(tool_name="send_email", arguments={})]
        )
        assert_permission_respected(trace, "send_email", requires_approval=True)


class TestAssertPermissionViolated:
    def test_passes_when_forbidden_tool_called(self, make_trace):
        trace = make_trace(
            tool_calls=[
                ToolCall(tool_name="drop_table", arguments={})
            ]
        )
        assert_permission_violated(trace, "drop_table")

    def test_fails_when_forbidden_tool_not_called(self, make_trace):
        trace = make_trace()
        with pytest.raises(AssertionError, match="Agent behaved correctly"):
            assert_permission_violated(trace, "drop_table")


# ──────────────────────────────────────────────────────
# Resilience Assertions
# ──────────────────────────────────────────────────────


class TestAssertGracefulDegradation:
    def test_passes_when_trace_completed(self, make_trace):
        trace = make_trace()
        trace.finish()
        assert_graceful_degradation(trace)

    def test_fails_when_trace_not_finished(self):
        trace = AgentTrace()  # Not finished
        with pytest.raises(AssertionError, match="never finished"):
            assert_graceful_degradation(trace)

    def test_fails_on_unrecoverable_critical_error(self, make_trace):
        trace = make_trace(
            errors=[
                Error(
                    message="fatal crash",
                    severity=ErrorSeverity.CRITICAL,
                    recoverable=False,
                )
            ]
        )
        trace.finish()
        with pytest.raises(AssertionError, match="unrecoverable"):
            assert_graceful_degradation(trace)


class TestAssertNoSilentFailure:
    def test_passes_when_output_exists(self, make_trace):
        step = Step(
            step_id=1, action=StepAction.RESPOND, output="All done"
        )
        trace = make_trace(steps=[step])
        assert_no_silent_failure(trace)

    def test_fails_when_no_steps(self, make_trace):
        trace = make_trace()
        with pytest.raises(AssertionError, match="no steps"):
            assert_no_silent_failure(trace)

    def test_fails_when_output_is_none(self, make_trace):
        step = Step(step_id=1, action=StepAction.RESPOND, output=None)
        trace = make_trace(steps=[step])
        with pytest.raises(AssertionError, match="output is None"):
            assert_no_silent_failure(trace)

    def test_fails_when_validator_rejects(self, make_trace):
        step = Step(
            step_id=1, action=StepAction.RESPOND, output="garbage"
        )
        trace = make_trace(steps=[step])
        with pytest.raises(AssertionError, match="failed validation"):
            assert_no_silent_failure(
                trace, validator=lambda x: x != "garbage"
            )
