# Quickstart — 5 Minutes to First Test

> Get Sentinel running, write a test, and see it catch a behavioral regression.

## Install

```bash
# Basic install (zero dependencies)
pip install git+https://github.com/adam85sims/Sentinel.git

# With LangChain adapter support
pip install "git+https://github.com/adam85sims/Sentinel.git[langchain]"

# Or with all adapters
pip install "git+https://github.com/adam85sims/Sentinel.git[adapters]"
```

## Your First Test (Python)

```python
from sentinel.env import MockTool, EnvironmentBuilder
from sentinel.models import AgentTrace
from sentinel.assertions import assert_tool_called, assert_no_tool_errors

# 1. Create a mock environment
env = (
    EnvironmentBuilder()
    .mock_tool("search", response={"results": ["Python is great"]})
    .mock_tool("email", response="sent")
    .build()
)

# 2. Create a trace to record calls
trace = AgentTrace()

# 3. Simulate your agent using tools
#    (Replace this with your actual agent code)
search_result = env.tools["search"](query="tell me about Python")
email_result = env.tools["email"](to="alice@example.com", subject="Hello")

# 4. Assert behavioral properties
assert_tool_called(trace, "search")
assert_no_tool_errors(trace)
print("All assertions passed!")
```

## Your First Test (pytest decorator)

```python
from sentinel.runner import sentinel_test
from sentinel.env import EnvironmentBuilder, MockTool
from sentinel.assertions import assert_tool_called

@sentinel_test(
    env=(EnvironmentBuilder()
        .mock_tool("search", response={"results": []})
        .build()),
    task="Search for refund policy",
)
def test_search_agent(trace, env):
    # trace is pre-created AgentTrace
    # env is the built Environment

    # Run your agent here
    result = env.tools["search"](query="refund policy")

    # Assert
    assert_tool_called(trace, "search")
```

## Adding Chaos

```python
from sentinel.chaos import ToolFailureInjector
from sentinel.env import MockTool

# Make the search tool fail 50% of the time
mock = MockTool("search", response="results")
injector = ToolFailureInjector(
    tool_name="search",
    failure_type="error",
    probability=0.5,
    seed=42,  # Deterministic for reproducibility
)
injector.wrap(mock)

# Now calls to mock() will sometimes raise MockToolError
try:
    mock(query="test")
except Exception as e:
    print(f"Tool failed as expected: {e}")
```

## Running from CLI

```bash
# Run a YAML scenario
sentinel run --path scenarios/basic.yaml

# Run with verbose output
sentinel run --path scenarios/basic.yaml --verbose

# List available scenarios
sentinel list

# Show scenario details
sentinel info refund-agent

# Record a baseline
sentinel baseline record

# Compare against baseline
sentinel diff

# Generate a report
sentinel report
```

## What Just Happened?

1. **MockTool** — You created a mock tool that returns canned responses
2. **AgentTrace** — You recorded what the agent actually did
3. **Assertions** — You verified the agent's behavior, not just its output
4. **Chaos** — You injected failures and verified the agent handles them

This is what makes Sentinel different from output-only evaluation:
you're testing what the agent **does**, not just what it **says**.

## Next Steps

- [Chaos Guide](CHAOS_GUIDE.md) — Deep dive on failure injection patterns
- [Adapters Guide](ADAPTERS_GUIDE.md) — Test real LangChain/CrewAI agents
- [Examples](../examples/) — Runnable demos and scenario files
