"""Tests for Sentinel LangChain adapter."""

import pytest
from sentinel.adapters.langchain import SentinelToolAdapter, AgentWrapper, wrap_agent
from sentinel.env import MockTool, MockToolError, RateLimitError
from sentinel.models import AgentTrace


class TestSentinelToolAdapter:
    def test_basic_invoke_records_call(self):
        """Adapter records calls into AgentTrace."""
        trace = AgentTrace()
        mock = MockTool("search", response={"results": ["a", "b"]})
        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        result = adapter.invoke({"query": "test"})

        assert result == {"results": ["a", "b"]}
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "search"
        assert trace.tool_calls[0].arguments == {"query": "test"}

    def test_direct_call_records_call(self):
        """__call__ also records calls."""
        trace = AgentTrace()
        mock = MockTool("email", response="sent")
        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        result = adapter(to="alice@example.com")

        assert result == "sent"
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "email"

    def test_error_records_and_reraises(self):
        """Errors are recorded in trace and re-raised."""
        trace = AgentTrace()
        mock = MockTool("fail_tool", side_effect=RateLimitError("slow down"))
        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        with pytest.raises(RateLimitError, match="slow down"):
            adapter.invoke({"q": "test"})

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error == "slow down"
        assert trace.tool_calls[0].result is None

    def test_multiple_calls_tracked(self):
        """Multiple calls are all tracked."""
        trace = AgentTrace()
        mock = MockTool("counter", response_fn=lambda n=0: {"count": n})
        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        adapter.invoke({"n": 1})
        adapter.invoke({"n": 2})
        adapter.invoke({"n": 3})

        assert len(trace.tool_calls) == 3
        assert [tc.arguments for tc in trace.tool_calls] == [
            {"n": 1},
            {"n": 2},
            {"n": 3},
        ]

    def test_reset_calls(self):
        """reset_calls clears mock tool's call history."""
        trace = AgentTrace()
        mock = MockTool("x", response="ok")
        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        adapter.invoke({"a": 1})
        adapter.invoke({"a": 2})
        assert mock.call_count == 2

        adapter.reset_calls()
        assert mock.call_count == 0
        # Trace is NOT cleared (it's separate)
        assert len(trace.tool_calls) == 2

    def test_adapter_properties(self):
        """Adapter exposes name, description, args."""
        trace = AgentTrace()
        mock = MockTool("my_tool", response="ok")
        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        assert adapter.name == "my_tool"
        assert adapter.description == "Sentinel mock tool: my_tool"
        assert adapter.args == {}

    def test_repr(self):
        """Repr shows adapter state."""
        trace = AgentTrace()
        mock = MockTool("search", response="ok")
        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        r = repr(adapter)
        assert "SentinelToolAdapter" in r
        assert "mock='search'" in r
        assert "calls=0" in r

    def test_chaos_injection_through_adapter(self):
        """Chaos-wrapped tools work through the adapter."""
        from sentinel.chaos import ToolFailureInjector

        trace = AgentTrace()
        mock = MockTool("flaky", response="ok")
        injector = ToolFailureInjector(
            tool_name="flaky",
            failure_type="error",
            probability=1.0,  # Always fail
            seed=42,
        )
        injector.wrap(mock)

        adapter = SentinelToolAdapter(mock=mock, trace=trace)

        with pytest.raises(MockToolError):
            adapter.invoke({"q": "test"})

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error is not None


class TestAgentWrapper:
    def test_wrap_agent_creates_adapters(self):
        """wrap_agent creates adapters for each mock tool."""
        trace = AgentTrace()
        agent = object()  # Dummy agent

        mock_search = MockTool("search", response="results")
        mock_email = MockTool("email", response="sent")

        wrapper = wrap_agent(
            agent=agent,
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
        wrapper = wrap_agent(agent=None, tool_map={"tool": mock}, trace=trace)

        assert wrapper.get_mock("tool") is mock
        assert wrapper.get_mock("nonexistent") is None

    def test_repr(self):
        """Repr shows wrapper state."""
        trace = AgentTrace()
        wrapper = wrap_agent(
            agent="dummy",
            tool_map={"a": MockTool("a"), "b": MockTool("b")},
            trace=trace,
        )
        r = repr(wrapper)
        assert "AgentWrapper" in r
        assert "tools=" in r

    def test_invoke_delegates_to_agent(self):
        """invoke delegates to the underlying agent's invoke."""
        class FakeAgent:
            def invoke(self, input, **kwargs):
                return {"agent_response": True}

        trace = AgentTrace()
        wrapper = wrap_agent(agent=FakeAgent(), tool_map={}, trace=trace)

        result = wrapper.invoke({"messages": ["hello"]})
        assert result == {"agent_response": True}

    def test_call_delegates_to_invoke(self):
        """__call__ delegates to invoke."""
        class FakeAgent:
            def invoke(self, input, **kwargs):
                return "called"

        trace = AgentTrace()
        wrapper = wrap_agent(agent=FakeAgent(), tool_map={}, trace=trace)

        result = wrapper()
        assert result == "called"
