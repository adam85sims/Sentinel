"""Tests for Sentinel OpenAI Agents SDK adapter."""

import json

import pytest

from sentinel.adapters.openai import SentinelFunctionTool, wrap_openai_agent
from sentinel.env import MockTool, MockToolError, RateLimitError
from sentinel.models import AgentTrace


class TestSentinelFunctionTool:
    def test_basic_invoke_dict(self):
        """invoke() with dict records calls into AgentTrace."""
        trace = AgentTrace()
        mock = MockTool("search", response={"results": ["a", "b"]})
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        result = tool.invoke({"query": "test"})

        assert result == {"results": ["a", "b"]}
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "search"
        assert trace.tool_calls[0].arguments == {"query": "test"}

    def test_invoke_json_string(self):
        """invoke() with JSON string parses and records correctly."""
        trace = AgentTrace()
        mock = MockTool("lookup", response="found")
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        args_json = json.dumps({"id": 42, "name": "alice"})
        result = tool.invoke(args_json)

        assert result == "found"
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].arguments == {"id": 42, "name": "alice"}

    def test_invoke_none(self):
        """invoke() with None uses empty kwargs."""
        trace = AgentTrace()
        mock = MockTool("ping", response="pong")
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        result = tool.invoke(None)

        assert result == "pong"
        assert trace.tool_calls[0].arguments == {}

    def test_invoke_non_dict_non_string(self):
        """invoke() with non-dict/non-string wraps as input."""
        trace = AgentTrace()
        mock = MockTool("accept", response="ok")
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        result = tool.invoke(42)

        assert result == "ok"
        assert trace.tool_calls[0].arguments == {"input": 42}

    def test_invoke_invalid_json(self):
        """invoke() with invalid JSON wraps as input."""
        trace = AgentTrace()
        mock = MockTool("raw", response="ok")
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        result = tool.invoke("not valid json {{{")

        assert result == "ok"
        assert trace.tool_calls[0].arguments == {"input": "not valid json {{{"}

    def test_call_interface(self):
        """__call__ delegates to mock and records the call."""
        trace = AgentTrace()
        mock = MockTool("email", response="sent")
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        result = tool(to="alice@example.com")

        assert result == "sent"
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "email"

    def test_error_records_and_reraises(self):
        """Errors are recorded in trace and re-raised."""
        trace = AgentTrace()
        mock = MockTool("fail_tool", side_effect=RateLimitError("slow down"))
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        with pytest.raises(RateLimitError, match="slow down"):
            tool.invoke({"q": "test"})

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error == "slow down"
        assert trace.tool_calls[0].result is None

    def test_multiple_calls_tracked(self):
        """Multiple calls are all tracked."""
        trace = AgentTrace()
        mock = MockTool("counter", response_fn=lambda n=0: {"count": n})
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        tool.invoke({"n": 1})
        tool.invoke({"n": 2})
        tool.invoke({"n": 3})

        assert len(trace.tool_calls) == 3
        assert [tc.arguments for tc in trace.tool_calls] == [
            {"n": 1}, {"n": 2}, {"n": 3},
        ]

    def test_params_json_schema_default(self):
        """Default schema is a generic object with additionalProperties."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        schema = tool.params_json_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is True

    def test_params_json_schema_custom(self):
        """Custom schema is preserved."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")
        custom_schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        tool = SentinelFunctionTool(mock=mock, trace=trace, params_json_schema=custom_schema)

        assert tool.params_json_schema == custom_schema

    def test_reset_calls(self):
        """reset_calls clears mock tool's call history."""
        trace = AgentTrace()
        mock = MockTool("x", response="ok")
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        tool.invoke({"a": 1})
        tool.invoke({"a": 2})
        assert mock.call_count == 2

        tool.reset_calls()
        assert mock.call_count == 0
        assert len(trace.tool_calls) == 2

    def test_custom_name_and_description(self):
        """Custom name and description override mock defaults."""
        trace = AgentTrace()
        mock = MockTool("internal_name", response="ok")
        tool = SentinelFunctionTool(
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
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        assert tool.name == "my_tool"

    def test_repr(self):
        """Repr shows tool state."""
        trace = AgentTrace()
        mock = MockTool("search", response="ok")
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        r = repr(tool)
        assert "SentinelFunctionTool" in r
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

        tool = SentinelFunctionTool(mock=mock, trace=trace)

        with pytest.raises(MockToolError):
            tool.invoke({"q": "test"})

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error is not None

    @pytest.mark.asyncio
    async def test_async_invoke(self):
        """async_invoke delegates to sync invoke."""
        trace = AgentTrace()
        mock = MockTool("async_tool", response="async_result")
        tool = SentinelFunctionTool(mock=mock, trace=trace)

        result = await tool.async_invoke({"key": "value"})

        assert result == "async_result"
        assert len(trace.tool_calls) == 1


class TestOpenAIAgentWrapper:
    def test_wrap_openai_agent_creates_adapters(self):
        """wrap_openai_agent creates adapters for each mock tool."""
        trace = AgentTrace()
        agent = object()  # Dummy agent

        mock_search = MockTool("search", response="results")
        mock_email = MockTool("email", response="sent")

        wrapper = wrap_openai_agent(
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
        wrapper = wrap_openai_agent(agent=None, tool_map={"tool": mock}, trace=trace)

        assert wrapper.get_mock("tool") is mock
        assert wrapper.get_mock("nonexistent") is None

    def test_get_adapter(self):
        """get_adapter returns the SentinelFunctionTool."""
        trace = AgentTrace()
        mock = MockTool("tool", response="ok")
        wrapper = wrap_openai_agent(agent=None, tool_map={"tool": mock}, trace=trace)

        adapter = wrapper.get_adapter("tool")
        assert adapter is not None
        assert adapter.name == "tool"
        assert wrapper.get_adapter("nonexistent") is None

    def test_get_tool_list(self):
        """get_tool_list returns all adapters as a list."""
        trace = AgentTrace()
        wrapper = wrap_openai_agent(
            agent=None,
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
        wrapper = wrap_openai_agent(
            agent="dummy",
            tool_map={"a": MockTool("a"), "b": MockTool("b")},
            trace=trace,
        )
        r = repr(wrapper)
        assert "OpenAIAgentWrapper" in r
        assert "tools=" in r

    def test_shared_trace(self):
        """All adapters share the same trace."""
        trace = AgentTrace()
        wrapper = wrap_openai_agent(
            agent=None,
            tool_map={
                "x": MockTool("x", response="ok"),
                "y": MockTool("y", response="ok"),
            },
            trace=trace,
        )

        wrapper.get_adapter("x").invoke({"q": 1})
        wrapper.get_adapter("y").invoke({"q": 2})

        assert len(trace.tool_calls) == 2
        assert trace.tool_calls[0].tool_name == "x"
        assert trace.tool_calls[1].tool_name == "y"
