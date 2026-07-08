#!/usr/bin/env python3
"""Sentinel + LangChain Quickstart

Demonstrates how to test a LangChain agent's behavior using Sentinel.
This example:

1. Creates real LangChain tools (search, calculator)
2. Wraps them with Sentinel's mock environment
3. Simulates an agent calling tools in sequence
4. Injects chaos (tool failures) and verifies Sentinel catches them
5. Asserts behavioral properties using Sentinel's assertion library

Run:  python examples/langchain_quickstart.py
Requires: pip install -e ".[langchain]"
"""

from sentinel.adapters.langchain import SentinelToolAdapter, wrap_agent
from sentinel.env import MockTool, EnvironmentBuilder
from sentinel.models import AgentTrace
from sentinel.assertions import (
    assert_tool_called,
    assert_tool_call_count,
    assert_tool_call_order,
    assert_no_tool_errors,
)
from sentinel.chaos import ToolFailureInjector

# ─── Step 1: Define real LangChain tools ────────────────────────
# These are actual @tool-decorated functions with real metadata.

try:
    from langchain_core.tools import tool
except ImportError:
    print("ERROR: langchain-core not installed. Run:")
    print("  pip install -e '.[langchain]'")
    exit(1)


@tool
def web_search(query: str) -> str:
    """Search the web for information about a topic.

    Args:
        query: The search query string.
    """
    # In production, this would call a real search API
    return f"Results for '{query}': Found relevant information."


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression.

    Args:
        expression: A math expression to evaluate.
    """
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"Error: {e}"


# ─── Step 2: Create sentinel mock environment ───────────────────

print("=" * 60)
print("SENTINEL + LANGCHAIN QUICKSTART")
print("=" * 60)

# Build an environment with mocked tools
env = (
    EnvironmentBuilder()
    .mock_tool("web_search", response="Mock search results: Python is great")
    .mock_tool("calculator", response="42")
    .build()
)

print("\n[1] Environment created with mocked tools:")
print(f"    - web_search: {env.tools['web_search']}")
print(f"    - calculator: {env.tools['calculator']}")


# ─── Step 3: Wrap real tools with sentinel adapters ─────────────

trace = AgentTrace()

search_adapter = SentinelToolAdapter(
    mock=env.tools["web_search"],
    trace=trace,
    base_tool=web_search,  # Real LangChain tool
)

calc_adapter = SentinelToolAdapter(
    mock=env.tools["calculator"],
    trace=trace,
    base_tool=calculator,  # Real LangChain tool
)

print("\n[2] Real LangChain tools wrapped with sentinel adapters:")
print(f"    - search_adapter: {search_adapter}")
print(f"    - calc_adapter: {calc_adapter}")


# ─── Step 4: Simulate agent execution ───────────────────────────

print("\n[3] Simulating agent execution...")


class SimpleAgent:
    """Minimal agent that calls tools in sequence."""

    def __init__(self, adapters: dict):
        self._adapters = adapters

    def run(self, task: str, plan: list) -> str:
        results = []
        for tool_name, kwargs in plan:
            adapter = self._adapters[tool_name]
            try:
                result = adapter.invoke(kwargs)
                results.append(f"{tool_name} -> {result}")
            except Exception as e:
                results.append(f"{tool_name} -> ERROR: {e}")
        return " | ".join(results)


agent = SimpleAgent({"web_search": search_adapter, "calculator": calc_adapter})

# Agent searches first, then calculates
result = agent.run(
    task="What is 6 times 7?",
    plan=[
        ("web_search", {"query": "what is 6 times 7"}),
        ("calculator", {"expression": "6 * 7"}),
    ],
)

print(f"    Agent result: {result}")
print(f"    Tool calls recorded: {len(trace.tool_calls)}")


# ─── Step 5: Assert behavioral properties ───────────────────────

print("\n[4] Asserting behavioral properties...")

assert_tool_called(trace, "web_search")
print("    ✓ web_search was called")

assert_tool_called(trace, "calculator")
print("    ✓ calculator was called")

assert_tool_call_count(trace, "web_search", expected_count=1)
print("    ✓ web_search called exactly once")

assert_tool_call_order(trace, ["web_search", "calculator"])
print("    ✓ Tools called in correct order: search -> calculator")

assert_no_tool_errors(trace)
print("    ✓ No tool errors during execution")


# ─── Step 6: Inject chaos and verify detection ──────────────────

print("\n[5] Injecting chaos (tool failure)...")

# Create a new trace for the chaos test
chaos_trace = AgentTrace()

# Make search fail every time
failing_search = MockTool("web_search", response="should not reach here")
injector = ToolFailureInjector(
    tool_name="web_search",
    failure_type="error",
    probability=1.0,  # Always fail
    seed=42,
)
injector.wrap(failing_search)

chaos_adapter = SentinelToolAdapter(
    mock=failing_search,
    trace=chaos_trace,
    base_tool=web_search,
)

# Agent tries to search — it fails
try:
    chaos_adapter.invoke({"query": "test"})
    print("    ERROR: Should have raised!")
except Exception as e:
    print(f"    ✓ Tool failure detected: {type(e).__name__}: {e}")

# Verify the failure was captured in the trace
assert len(chaos_trace.tool_calls) == 1
assert chaos_trace.tool_calls[0].error is not None
print(f"    ✓ Failure captured in trace: {chaos_trace.tool_calls[0].error}")


# ─── Summary ────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Total tool calls across both traces: {len(trace.tool_calls) + len(chaos_trace.tool_calls)}")
print(f"Successful calls: {sum(1 for tc in trace.tool_calls if tc.error is None) + 0}")
print(f"Failed calls: {sum(1 for tc in chaos_trace.tool_calls if tc.error is not None)}")
print("\nSentinel successfully:")
print("  ✓ Wrapped real LangChain tools with mock environment")
print("  ✓ Captured all tool calls in AgentTrace")
print("  ✓ Verified behavioral properties with assertions")
print("  ✓ Detected tool failures from chaos injection")
print("\nThis is the 'proof of value' — Sentinel catches behavioral")
print("regressions that output-only evaluation would miss.")
