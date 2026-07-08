"""Tests for Sentinel CrewAI adapter."""

import pytest
from sentinel.adapters.crewai import SentinelCrewTool, CrewAgentWrapper, wrap_crew_agent
from sentinel.env import MockTool, MockToolError, RateLimitError
from sentinel.models import AgentTrace


class TestSentinelCrewTool:
    def test_basic_run_records_call(self):
        """Tool records calls into AgentTrace via run()."""
        trace = AgentTrace()
        mock = MockTool("search", response={"results": ["a", "b"]})
        tool = SentinelCrewTool(mock=mock, trace=trace)

        result = tool.run(query="test")

        assert result == {"results": ["a", "b"]}
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "search"
        assert trace.tool_calls[0].arguments == {"query": "test"}

    def test_run_alias(self):
        """_run() delegates to run()."""
        trace = AgentTrace()
        mock = MockTool("calc", response=42)
        tool = SentinelCrewTool(mock=mock, trace=trace)

        result = tool._run(x=10)

        assert result == 42
        assert len(trace.tool_calls) == 1

    def test_error_records_and_reraises(self):
        """Errors are recorded in trace and re-raised."""
        trace = AgentTrace()
        mock = MockTool("fail_tool", side_effect=RateLimitError("slow down"))
        tool = SentinelCrewTool(mock=mock, trace=trace)

        with pytest.raises(RateLimitError, match="slow down"):
            tool.run(q="test")

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error == "slow down"
        assert trace.tool_calls[0].result is None

    def test_multiple_calls_tracked(self):
        """Multiple calls are all tracked."""
        trace = AgentTrace()
        mock = MockTool("counter", response_fn=lambda n=0: {"count": n})
        tool = SentinelCrewTool(mock=mock, trace=trace)

        tool.run(n=1)
        tool.run(n=2)
        tool.run(n=3)

        assert len(trace.tool_calls) == 3
        assert [tc.arguments for tc in trace.tool_calls] == [
            {"n": 1}, {"n": 2}, {"n": 3},
        ]

    def test_reset_calls(self):
        """reset_calls clears mock tool's call history."""
        trace = AgentTrace()
        mock = MockTool("x", response="ok")
        tool = SentinelCrewTool(mock=mock, trace=trace)

        tool.run(a=1)
        tool.run(a=2)
        assert mock.call_count == 2

        tool.reset_calls()
        assert mock.call_count == 0
        # Trace is NOT cleared (it's separate)
        assert len(trace.tool_calls) == 2

    def test_custom_name_and_description(self):
        """Custom name and description override mock defaults."""
        trace = AgentTrace()
        mock = MockTool("internal_name", response="ok")
        tool = SentinelCrewTool(
            mock=mock,
            trace=trace,
            name="public_name",
            description="A public tool",
        )

        assert tool.name == "public_name"
        assert tool.description == "A public tool"

    def test_default_name_from_mock(self):
        """Name defaults to mock.name when not specified."""
        trace = AgentTrace()
        mock = MockTool("my_tool", response="ok")
        tool = SentinelCrewTool(mock=mock, trace=trace)

        assert tool.name == "my_tool"
        assert "my_tool" in tool.description

    def test_repr(self):
        """Repr shows tool state."""
        trace = AgentTrace()
        mock = MockTool("search", response="ok")
        tool = SentinelCrewTool(mock=mock, trace=trace)

        r = repr(tool)
        assert "SentinelCrewTool" in r
        assert "name='search'" in r
        assert "calls=0" in r

    def test_chaos_injection_through_tool(self):
        """Chaos-wrapped tools work through the adapter."""
        from sentinel.chaos import ToolFailureInjector

        trace = AgentTrace()
        mock = MockTool("flaky", response="ok")
        injector = ToolFailureInjector(
            tool_name="flaky",
            failure_type="error",
            probability=1.0,
            seed=42,
        )
        injector.wrap(mock)

        tool = SentinelCrewTool(mock=mock, trace=trace)

        with pytest.raises(MockToolError):
            tool.run(q="test")

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error is not None


class TestCrewAgentWrapper:
    def test_wrap_crew_agent_creates_adapters(self):
        """wrap_crew_agent creates adapters for each mock tool."""
        trace = AgentTrace()
        crew = object()  # Dummy crew

        mock_search = MockTool("search", response="results")
        mock_email = MockTool("email", response="sent")

        wrapper = wrap_crew_agent(
            crew=crew,
            tool_map={"search": mock_search, "email": mock_email},
            trace=trace,
        )

        assert len(wrapper.adapters) == 2
        assert "search" in wrapper.adapters
        assert "email" in wrapper.adapters

    def test_get_mock(self):
        """get_mock returns the underlying MockTool."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")
        wrapper = wrap_crew_agent(crew=None, tool_map={"tool": mock}, trace=trace)

        assert wrapper.get_mock("tool") is mock
        assert wrapper.get_mock("nonexistent") is None

    def test_get_adapter(self):
        """get_adapter returns the SentinelCrewTool."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")
        wrapper = wrap_crew_agent(crew=None, tool_map={"tool": mock}, trace=trace)

        adapter = wrapper.get_adapter("tool")
        assert adapter is not None
        assert adapter.name == "tool"
        assert wrapper.get_adapter("nonexistent") is None

    def test_get_tool_list(self):
        """get_tool_list returns all adapters as a list."""
        trace = AgentTrace()
        wrapper = wrap_crew_agent(
            crew=None,
            tool_map={
                "a": MockTool("a", response="ok"),
                "b": MockTool("b", response="ok"),
            },
            trace=trace,
        )

        tools = wrapper.get_tool_list()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"a", "b"}

    def test_repr(self):
        """Repr shows wrapper state."""
        trace = AgentTrace()
        wrapper = wrap_crew_agent(
            crew="dummy",
            tool_map={"a": MockTool("a"), "b": MockTool("b")},
            trace=trace,
        )
        r = repr(wrapper)
        assert "CrewAgentWrapper" in r
        assert "tools=" in r

    def test_shared_trace(self):
        """All adapters share the same trace."""
        trace = AgentTrace()
        wrapper = wrap_crew_agent(
            crew=None,
            tool_map={
                "x": MockTool("x", response="ok"),
                "y": MockTool("y", response="ok"),
            },
            trace=trace,
        )

        wrapper.get_adapter("x").run(q=1)
        wrapper.get_adapter("y").run(q=2)

        assert len(trace.tool_calls) == 2
        assert trace.tool_calls[0].tool_name == "x"
        assert trace.tool_calls[1].tool_name == "y"
