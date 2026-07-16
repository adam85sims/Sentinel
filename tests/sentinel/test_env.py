"""Tests for Sentinel mock tool environment."""

import pytest

from sentinel.env import (
    EnvironmentBuilder,
    MockTool,
    MockToolError,
    RateLimitError,
)


class TestMockTool:
    def test_static_response(self):
        tool = MockTool("search", response={"results": ["a", "b"]})
        result = tool(q="test")
        assert result == {"results": ["a", "b"]}
        assert tool.call_count == 1

    def test_dynamic_response_fn(self):
        tool = MockTool(
            "search", response_fn=lambda q: {"query": q, "count": len(q)}
        )
        result = tool(q="hello")
        assert result == {"query": "hello", "count": 5}

    def test_side_effect_raises(self):
        tool = MockTool("search", side_effect=RateLimitError())
        with pytest.raises(RateLimitError):
            tool(q="test")
        # Side effect is one-shot — second call should work
        tool.response = {"ok": True}
        result = tool(q="test2")
        assert result == {"ok": True}

    def test_error_probability(self):
        import random

        random.seed(42)  # Deterministic
        tool = MockTool(
            "search", response="ok", error_probability=1.0  # Always error
        )
        with pytest.raises(MockToolError):
            tool(q="test")

    def test_error_probability_zero_never_fails(self):
        tool = MockTool("search", response="ok", error_probability=0.0)
        for _ in range(100):
            result = tool(q="test")
        assert result == "ok"
        assert tool.call_count == 100

    def test_records_calls(self):
        tool = MockTool("search", response="ok")
        tool(q="first")
        tool(q="second")

        assert tool.call_count == 2
        assert tool.calls[0].arguments == {"q": "first"}
        assert tool.calls[1].arguments == {"q": "second"}

    def test_last_call(self):
        tool = MockTool("search", response="ok")
        assert tool.last_call is None
        tool(q="test")
        assert tool.last_call is not None
        assert tool.last_call.arguments == {"q": "test"}


class TestEnvironmentBuilder:
    def test_build_empty(self):
        env = EnvironmentBuilder().build()
        assert env.get_tool("anything") is None
        assert env.get_tools() == {}

    def test_build_with_tool(self):
        env = (
            EnvironmentBuilder()
            .mock_tool("search", response="results")
            .build()
        )
        tool = env.get_tool("search")
        assert tool is not None
        assert tool.name == "search"

    def test_build_with_multiple_tools(self):
        env = (
            EnvironmentBuilder()
            .mock_tool("search", response="results")
            .mock_tool("email", response="sent")
            .build()
        )
        assert len(env.get_tools()) == 2
        assert env.get_tool("search") is not None
        assert env.get_tool("email") is not None


class TestEnvironment:
    def test_all_calls_sorted_chronologically(self):
        env = (
            EnvironmentBuilder()
            .mock_tool("a", response=1)
            .mock_tool("b", response=2)
            .build()
        )
        env.get_tool("a")()
        env.get_tool("b")()
        env.get_tool("a")()

        calls = env.all_calls
        assert len(calls) == 3
        assert [c.tool_name for c in calls] == ["a", "b", "a"]

    def test_reset_clears_calls(self):
        env = EnvironmentBuilder().mock_tool("x", response="ok").build()
        env.get_tool("x")()
        assert len(env.all_calls) == 1
        env.reset()
        assert len(env.all_calls) == 0
