"""Tests for Sentinel core data models."""

from sentinel.models import (
    AgentTrace,
    Error,
    ErrorSeverity,
    StateChange,
    Step,
    StepAction,
    ToolCall,
)


class TestToolCall:
    def test_succeeded_when_no_error(self):
        tc = ToolCall(tool_name="search", arguments={"q": "test"}, result="ok")
        assert tc.succeeded is True

    def test_failed_when_error_set(self):
        tc = ToolCall(
            tool_name="search", arguments={"q": "test"}, error="timeout"
        )
        assert tc.succeeded is False


class TestAgentTrace:
    def test_empty_trace(self):
        trace = AgentTrace()
        assert trace.total_steps == 0
        assert trace.total_tool_calls == 0
        assert trace.failed_tool_calls == []
        assert trace.tool_names_called == []

    def test_add_step_indexes_tool_calls(self):
        trace = AgentTrace()
        tc1 = ToolCall(tool_name="search", arguments={"q": "test"})
        tc2 = ToolCall(tool_name="email", arguments={"to": "a@b.com"})
        step = Step(step_id=1, action=StepAction.TOOL_CALL, tool_calls=[tc1, tc2])

        trace.add_step(step)

        assert trace.total_steps == 1
        assert trace.total_tool_calls == 2
        assert trace.tool_names_called == ["search", "email"]
        assert tc1.step_id == 1
        assert tc2.step_id == 1

    def test_tool_calls_by_name(self):
        trace = AgentTrace()
        trace.tool_calls.append(
            ToolCall(tool_name="search", arguments={"q": "a"})
        )
        trace.tool_calls.append(
            ToolCall(tool_name="email", arguments={"to": "x@y.com"})
        )
        trace.tool_calls.append(
            ToolCall(tool_name="search", arguments={"q": "b"})
        )

        search_calls = trace.tool_calls_by_name("search")
        assert len(search_calls) == 2
        assert search_calls[0].arguments["q"] == "a"
        assert search_calls[1].arguments["q"] == "b"

    def test_tool_names_called_deduplicates(self):
        trace = AgentTrace()
        trace.tool_calls.append(ToolCall(tool_name="search", arguments={}))
        trace.tool_calls.append(ToolCall(tool_name="search", arguments={}))
        trace.tool_calls.append(ToolCall(tool_name="email", arguments={}))

        assert trace.tool_names_called == ["search", "email"]

    def test_failed_tool_calls(self):
        trace = AgentTrace()
        trace.tool_calls.append(
            ToolCall(tool_name="ok_tool", arguments={}, result="good")
        )
        trace.tool_calls.append(
            ToolCall(tool_name="bad_tool", arguments={}, error="boom")
        )

        failed = trace.failed_tool_calls
        assert len(failed) == 1
        assert failed[0].tool_name == "bad_tool"

    def test_finish_sets_end_time(self):
        trace = AgentTrace()
        assert trace._end_time is None
        trace.finish()
        assert trace._end_time is not None
        assert trace.total_duration_ms >= 0

    def test_to_dict(self):
        trace = AgentTrace()
        trace.tool_calls.append(
            ToolCall(tool_name="search", arguments={"q": "test"})
        )
        d = trace.to_dict()
        assert d["total_tool_calls"] == 1
        assert d["tool_names_called"] == ["search"]

    def test_add_tool_call(self):
        trace = AgentTrace()
        tc = ToolCall(tool_name="test", arguments={})
        trace.add_tool_call(tc)
        assert trace.total_tool_calls == 1

    def test_add_state_change(self):
        trace = AgentTrace()
        sc = StateChange(key="user_id", old_value=None, new_value="123")
        trace.add_state_change(sc)
        assert len(trace.state_changes) == 1

    def test_add_error(self):
        trace = AgentTrace()
        err = Error(message="something broke", severity=ErrorSeverity.HIGH)
        trace.add_error(err)
        assert len(trace.errors) == 1


class TestStep:
    def test_step_with_tool_calls(self):
        tc = ToolCall(tool_name="search", arguments={"q": "test"})
        step = Step(step_id=1, action=StepAction.TOOL_CALL, tool_calls=[tc])
        assert len(step.tool_calls) == 1
        assert step.tool_calls[0].tool_name == "search"
