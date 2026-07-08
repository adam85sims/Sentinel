"""Integration tests with real LangChain tools and agent patterns.

These tests prove that sentinel's adapter layer works correctly with
REAL LangChain BaseTool instances and real agent execution patterns.
Not mock-on-mock — real LangChain tools going through sentinel's
mock environment and trace capture.

Strategy:
    We create real LangChain @tool-decorated functions, wrap them with
    sentinel's SentinelToolAdapter, and simulate agent execution loops.
    This tests the full integration path without requiring a real LLM API.

    For tests that need actual tool-calling behavior from an LLM, we use
    a simulated ReAct loop that mirrors how langchain.agents works but
    with deterministic control.
"""

import pytest
from sentinel.adapters.langchain import SentinelToolAdapter, wrap_agent
from sentinel.env import MockTool, MockToolError, TimeoutError, RateLimitError
from sentinel.models import AgentTrace
from sentinel.assertions import (
    assert_tool_called,
    assert_tool_not_called,
    assert_tool_call_order,
    assert_tool_call_count,
    assert_no_tool_errors,
    assert_graceful_degradation,
)

# ─── Real LangChain tools ──────────────────────────────────────
# These are actual @tool-decorated functions, not mocks.
# They have real name, description, args_schema, and invoke().

try:
    from langchain_core.tools import tool

    @tool
    def web_search(query: str) -> str:
        """Search the web for information about a topic.

        Args:
            query: The search query string.
        """
        return f"Search results for '{query}': Found relevant information about {query}."

    @tool
    def calculator(expression: str) -> str:
        """Evaluate a mathematical expression.

        Args:
            expression: A math expression to evaluate (e.g., '2 + 2').
        """
        # Safe eval for demo — production would use a real math parser
        try:
            result = eval(expression, {"__builtins__": {}}, {})
            return str(result)
        except Exception as e:
            return f"Error: {e}"

    @tool
    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email to a recipient.

        Args:
            to: Email address of the recipient.
            subject: Email subject line.
            body: Email body content.
        """
        return f"Email sent to {to}: {subject}"

    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False


# ─── Simulated ReAct Agent ─────────────────────────────────────
# This simulates the langchain.agents.create_react_agent loop.
# It demonstrates how a real agent would interact with sentinel's
# adapter layer.

class SimulatedReActAgent:
    """A minimal ReAct agent that uses tools through sentinel adapters.

    This mirrors how langchain.agents.create_react_agent works:
    1. Receives a task
    2. Reasons about what tool to call
    3. Calls the tool (through sentinel adapter)
    4. Observes the result
    5. Decides if done or needs another tool call

    The "reasoning" is pre-scripted for deterministic testing.
    """

    def __init__(self, adapters: dict, plan: list):
        """
        Args:
            adapters: Dict of tool_name -> SentinelToolAdapter
            plan: List of (tool_name, kwargs) tuples representing
                  the agent's planned tool calls. The agent will
                  call each tool in sequence.
        """
        self._adapters = adapters
        self._plan = plan
        self._step = 0

    def run(self, task: str) -> str:
        """Execute the agent's plan, calling tools through adapters.

        Returns a summary of what the agent did.
        """
        results = []
        for tool_name, kwargs in self._plan:
            adapter = self._adapters.get(tool_name)
            if adapter is None:
                results.append(f"No adapter for tool '{tool_name}'")
                continue

            try:
                result = adapter.invoke(kwargs)
                results.append(f"Called {tool_name}: {result}")
            except Exception as e:
                results.append(f"Called {tool_name}: ERROR - {e}")

        return "; ".join(results)


# ─── Tests: Real LangChain Tools Through Sentinel ──────────────

@pytest.mark.skipif(not HAS_LANGCHAIN, reason="langchain-core not installed")
class TestRealToolIntegration:
    """Test sentinel adapters with real LangChain @tool-decorated functions."""

    def test_wrap_real_search_tool(self):
        """SentinelToolAdapter wraps a real LangChain search tool."""
        trace = AgentTrace()
        mock = MockTool("web_search", response="Mock search results")
        adapter = SentinelToolAdapter(
            mock=mock,
            trace=trace,
            base_tool=web_search,  # Real LangChain tool
        )

        # The adapter should preserve the real tool's metadata
        assert adapter.name == "web_search"
        assert "Search the web for information" in adapter.description
        assert "query" in adapter.args

        # But delegate to the mock for execution
        result = adapter.invoke({"query": "test"})
        assert result == "Mock search results"
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].tool_name == "web_search"

    def test_wrap_real_calculator_tool(self):
        """SentinelToolAdapter wraps a real LangChain calculator tool."""
        trace = AgentTrace()
        mock = MockTool("calculator", response="42")
        adapter = SentinelToolAdapter(
            mock=mock,
            trace=trace,
            base_tool=calculator,
        )

        assert adapter.name == "calculator"
        assert "expression" in adapter.args

        result = adapter.invoke({"expression": "6 * 7"})
        assert result == "42"

    def test_wrap_real_email_tool(self):
        """SentinelToolAdapter wraps a real LangChain email tool."""
        trace = AgentTrace()
        mock = MockTool("send_email", response="Email sent successfully")
        adapter = SentinelToolAdapter(
            mock=mock,
            trace=trace,
            base_tool=send_email,
        )

        assert adapter.name == "send_email"
        assert "to" in adapter.args
        assert "subject" in adapter.args
        assert "body" in adapter.args

        result = adapter.invoke({
            "to": "alice@example.com",
            "subject": "Hello",
            "body": "Test email",
        })
        assert result == "Email sent successfully"

    def test_multiple_real_tools_share_trace(self):
        """Multiple real tools recording to the same trace."""
        trace = AgentTrace()

        search_adapter = SentinelToolAdapter(
            mock=MockTool("web_search", response="search results"),
            trace=trace,
            base_tool=web_search,
        )
        calc_adapter = SentinelToolAdapter(
            mock=MockTool("calculator", response="42"),
            trace=trace,
            base_tool=calculator,
        )

        # Simulate agent calling search then calculator
        search_adapter.invoke({"query": "what is 6*7"})
        calc_adapter.invoke({"expression": "6*7"})

        # Both calls should be in the trace
        assert len(trace.tool_calls) == 2
        assert trace.tool_calls[0].tool_name == "web_search"
        assert trace.tool_calls[1].tool_name == "calculator"

    def test_type_validation_rejects_non_tool(self):
        """Adapter rejects non-BaseTool objects when base_tool is provided."""
        trace = AgentTrace()
        mock = MockTool("test", response="ok")

        with pytest.raises(TypeError, match="must be a langchain BaseTool"):
            SentinelToolAdapter(
                mock=mock,
                trace=trace,
                base_tool="not a tool",  # Wrong type
            )


# ─── Tests: Agent Loop Through Sentinel ────────────────────────

@pytest.mark.skipif(not HAS_LANGCHAIN, reason="langchain-core not installed")
class TestAgentLoopIntegration:
    """Test a simulated ReAct agent loop going through sentinel adapters."""

    def test_search_then_calculate(self):
        """Agent searches, then calculates — both calls tracked."""
        trace = AgentTrace()

        adapters = {
            "web_search": SentinelToolAdapter(
                mock=MockTool("web_search", response="6 * 7 = 42"),
                trace=trace,
                base_tool=web_search,
            ),
            "calculator": SentinelToolAdapter(
                mock=MockTool("calculator", response="42"),
                trace=trace,
                base_tool=calculator,
            ),
        }

        agent = SimulatedReActAgent(
            adapters=adapters,
            plan=[
                ("web_search", {"query": "what is 6 times 7"}),
                ("calculator", {"expression": "6 * 7"}),
            ],
        )

        result = agent.run("Calculate 6 * 7")
        assert "web_search" in result
        assert "calculator" in result

        # Verify trace captured both calls
        assert_tool_call_count(trace, "web_search", expected_count=1)
        assert_tool_call_count(trace, "calculator", expected_count=1)
        assert_tool_call_order(trace, ["web_search", "calculator"])

    def test_agent_with_failing_tool(self):
        """Agent calls a tool that raises an error — error is tracked."""
        trace = AgentTrace()

        failing_mock = MockTool(
            "web_search",
            side_effect=RateLimitError("API rate limit exceeded"),
        )

        adapters = {
            "web_search": SentinelToolAdapter(
                mock=failing_mock,
                trace=trace,
                base_tool=web_search,
            ),
            "calculator": SentinelToolAdapter(
                mock=MockTool("calculator", response="42"),
                trace=trace,
                base_tool=calculator,
            ),
        }

        agent = SimulatedReActAgent(
            adapters=adapters,
            plan=[
                ("web_search", {"query": "test"}),
                ("calculator", {"expression": "1+1"}),  # Should still work
            ],
        )

        result = agent.run("Search and calculate")
        assert "ERROR" in result
        assert "calculator" in result  # Second call succeeded

        # Search failed, calculator succeeded
        assert trace.tool_calls[0].error == "API rate limit exceeded"
        assert trace.tool_calls[1].error is None

    def test_agent_tool_call_arguments_recorded(self):
        """All tool call arguments are accurately recorded in trace."""
        trace = AgentTrace()

        adapters = {
            "send_email": SentinelToolAdapter(
                mock=MockTool("send_email", response="sent"),
                trace=trace,
                base_tool=send_email,
            ),
        }

        agent = SimulatedReActAgent(
            adapters=adapters,
            plan=[
                ("send_email", {
                    "to": "alice@example.com",
                    "subject": "Hello",
                    "body": "Test message",
                }),
            ],
        )

        agent.run("Send an email")

        call = trace.tool_calls[0]
        assert call.tool_name == "send_email"
        assert call.arguments["to"] == "alice@example.com"
        assert call.arguments["subject"] == "Hello"
        assert call.arguments["body"] == "Test message"


# ─── Tests: Chaos Through Real Tools ───────────────────────────

@pytest.mark.skipif(not HAS_LANGCHAIN, reason="langchain-core not installed")
class TestChaosWithRealTools:
    """Test chaos injection through real LangChain tool adapters."""

    def test_tool_failure_mid_agent_run(self):
        """Tool fails mid-run — agent detects the regression."""
        from sentinel.chaos import ToolFailureInjector

        trace = AgentTrace()

        # Search tool fails on every call
        failing_mock = MockTool("web_search", response="should not reach here")
        injector = ToolFailureInjector(
            tool_name="web_search",
            failure_type="error",
            probability=1.0,  # Always fail
            seed=42,
        )
        injector.wrap(failing_mock)

        adapters = {
            "web_search": SentinelToolAdapter(
                mock=failing_mock,
                trace=trace,
                base_tool=web_search,
            ),
            "calculator": SentinelToolAdapter(
                mock=MockTool("calculator", response="42"),
                trace=trace,
                base_tool=calculator,
            ),
        }

        agent = SimulatedReActAgent(
            adapters=adapters,
            plan=[
                ("web_search", {"query": "test"}),
                ("calculator", {"expression": "1+1"}),
            ],
        )

        result = agent.run("Search and calculate")

        # Search failed, calculator still worked
        assert "ERROR" in result
        assert trace.tool_calls[0].error is not None
        assert trace.tool_calls[1].error is None

        # This IS the behavioral regression sentinel catches:
        # The agent's search capability is broken, but it can still calculate.
        # In production, this would mean the agent can't find information
        # but can still do math — a partial degradation.

    def test_rate_limit_triggers_retry_behavior(self):
        """Rate limit error — sentinel captures the pattern."""
        from sentinel.chaos import ToolFailureInjector

        trace = AgentTrace()

        mock = MockTool("web_search", response="ok")
        injector = ToolFailureInjector(
            tool_name="web_search",
            failure_type="rate_limit",
            probability=1.0,
            seed=42,
        )
        injector.wrap(mock)

        adapter = SentinelToolAdapter(
            mock=mock,
            trace=trace,
            base_tool=web_search,
        )

        with pytest.raises(RateLimitError):
            adapter.invoke({"query": "test"})

        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].error is not None
        assert "Rate limit exceeded" in trace.tool_calls[0].error

    def test_timeout_error_captured(self):
        """Timeout error through real tool adapter."""
        trace = AgentTrace()

        mock = MockTool(
            "web_search",
            side_effect=TimeoutError("Request timed out after 30s"),
        )

        adapter = SentinelToolAdapter(
            mock=mock,
            trace=trace,
            base_tool=web_search,
        )

        with pytest.raises(TimeoutError):
            adapter.invoke({"query": "slow query"})

        assert trace.tool_calls[0].error == "Request timed out after 30s"


# ─── Tests: Environment Builder With Real Tools ────────────────

@pytest.mark.skipif(not HAS_LANGCHAIN, reason="langchain-core not installed")
class TestEnvironmentWithRealTools:
    """Test EnvironmentBuilder creating environments for real LangChain agents."""

    def test_builder_with_langchain_tool_names(self):
        """EnvironmentBuilder creates mocks matching LangChain tool names."""
        from sentinel.env import EnvironmentBuilder

        env = (
            EnvironmentBuilder()
            .mock_tool("web_search", response="search results")
            .mock_tool("calculator", response="42")
            .mock_tool("send_email", response="sent")
            .build()
        )

        # All tools should be available
        assert "web_search" in env.tools
        assert "calculator" in env.tools
        assert "send_email" in env.tools

        # Create adapters with real LangChain tools
        trace = AgentTrace()
        search_adapter = SentinelToolAdapter(
            mock=env.tools["web_search"],
            trace=trace,
            base_tool=web_search,
        )

        result = search_adapter.invoke({"query": "test"})
        assert result == "search results"

    def test_environment_with_api_and_tools(self):
        """Environment with both tools and API for complex agents."""
        from sentinel.env import EnvironmentBuilder

        env = (
            EnvironmentBuilder()
            .mock_tool("web_search", response="search results")
            .mock_api(base_url="https://api.example.com")
            .build()
        )

        assert "web_search" in env.tools
        assert len(env.apis) > 0


# ─── Tests: Assertion Integration ──────────────────────────────

@pytest.mark.skipif(not HAS_LANGCHAIN, reason="langchain-core not installed")
class TestAssertionIntegration:
    """Test sentinel assertions against real tool call traces."""

    def test_assert_tool_called_with_real_tool(self):
        """assert_tool_called works with traces from real LangChain tools."""
        trace = AgentTrace()

        adapter = SentinelToolAdapter(
            mock=MockTool("web_search", response="results"),
            trace=trace,
            base_tool=web_search,
        )

        adapter.invoke({"query": "test"})

        # Should pass — tool was called
        assert_tool_called(trace, "web_search")

        # Should fail — different tool was not called
        with pytest.raises(AssertionError):
            assert_tool_called(trace, "calculator")

    def test_assert_no_errors_after_clean_run(self):
        """assert_no_tool_errors passes after clean execution."""
        trace = AgentTrace()

        for tool_name, lc_tool in [("web_search", web_search), ("calculator", calculator)]:
            adapter = SentinelToolAdapter(
                mock=MockTool(tool_name, response="ok"),
                trace=trace,
                base_tool=lc_tool,
            )
            adapter.invoke({"query": "test"})

        assert_no_tool_errors(trace)

    def test_assert_tool_order_after_sequential_calls(self):
        """assert_tool_call_order works with sequential real tool calls."""
        trace = AgentTrace()

        search_adapter = SentinelToolAdapter(
            mock=MockTool("web_search", response="results"),
            trace=trace,
            base_tool=web_search,
        )
        calc_adapter = SentinelToolAdapter(
            mock=MockTool("calculator", response="42"),
            trace=trace,
            base_tool=calculator,
        )

        search_adapter.invoke({"query": "math"})
        calc_adapter.invoke({"expression": "1+1"})

        assert_tool_call_order(trace, ["web_search", "calculator"])

        # Wrong order should fail
        with pytest.raises(AssertionError):
            assert_tool_call_order(trace, ["calculator", "web_search"])
