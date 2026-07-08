# Sentinel

**Agent Behavioral Testing Platform — Test what agents DO, not just what they SAY.**

```
pip install agent-frameworks[sentinel]
```

Sentinel is a framework-agnostic testing platform for AI agents. It captures
full execution traces — every tool call, state change, error, and decision —
then runs behavioral assertions against that trace to verify correctness,
governance compliance, and resilience under failure.

No flaky LLM output comparisons. No prompt-level guesswork. Just hard
evidence of what your agent actually did.


---

## Why Sentinel?

Most agent testing frameworks validate **output quality**: "did the LLM say
something reasonable?" That's necessary but deeply insufficient. Your agent
might produce a plausible-sounding answer while:

- Calling the wrong tools
- Skipping required approval steps
- Crashing silently on API failures
- Leaking data through unauthorized tool access
- Degrading performance under load

Sentinel validates **behavior**: the sequence of actions, the tools invoked,
the arguments passed, the errors handled, and the state mutations produced.
It works at the integration boundary — between your agent's reasoning and
its real-world effects — where correctness actually matters.

### What Sentinel catches that output testing misses

| Problem | Output test | Sentinel |
|---------|------------|----------|
| Agent calls unauthorized tools | Missed | `assert_tool_not_called` |
| Wrong tool call order | Missed | `assert_tool_call_order` |
| Silent failure (no error, empty output) | Sometimes | `assert_no_silent_failure` |
| Governance bypass (skipped approval) | Missed | `assert_approval_before_action` |
| Timeout handling broken | Missed | `assert_graceful_degradation` |
| Performance regression | Missed | `assert_latency`, `assert_token_usage` |
| State inconsistency | Missed | `assert_state_consistent` |
| Rate limit handling | Missed | Chaos injection + assertions |


---

## Quick Start

### 1. Define a test scenario

```python
import pytest
from sentinel import (
    AgentTrace, EnvironmentBuilder, MockTool, sentinel_test,
    assert_tool_called, assert_tool_not_called, assert_tool_call_order,
)

@sentinel_test(
    env=(EnvironmentBuilder()
        .mock_tool("search", response={"results": ["refund policy found"]})
        .mock_tool("email", response={"sent": True})
        .build()),
    task="Process refund request for order #123",
)
def test_refund_agent(trace, env):
    """Agent should search for policy, then send confirmation email."""

    # Run your agent here — it receives `trace` and `env`
    run_my_agent(
        task="Process refund for order #123",
        tools=env.tools,
        trace=trace,
    )

    # Behavioral assertions against the captured trace
    assert_tool_called(trace, "search", query="refund policy")
    assert_tool_called(trace, "email")
    assert_tool_call_order(trace, ["search", "email"])
```

### 2. Run it

```bash
# Run with pytest like any other test
pytest tests/test_refund_agent.py -v

# Or use the sentinel CLI
sentinel-run run --path scenarios/refund_agent.json --verbose
```

### 3. Check results

```
[PASS] refund-agent-basic (4/4 assertions, 45ms)
[PASS] refund-agent-timeout (3/3 assertions, 31ms)
[FAIL] refund-agent-rate-limit (2/3 assertions, 120ms)
  ✗ assert_graceful_degradation: Agent did not continue after rate limit error
```

---

## Core Concepts

### AgentTrace — the source of truth

Every agent run produces an `AgentTrace` — a structured record of
everything that happened:

```python
trace = AgentTrace()

# After agent execution:
trace.total_steps          # Number of reasoning steps
trace.tool_calls           # All tool invocations (with args, results, timing)
trace.state_changes        # Memory/state mutations
trace.errors               # Errors encountered
trace.total_duration_ms    # Wall-clock execution time
trace.tool_names_called    # Unique tools in call order
trace.failed_tool_calls    # Tools that errored
```

### Mock tools — deterministic environment

Replace real API calls with configurable mocks:

```python
from sentinel import MockTool, EnvironmentBuilder

env = (EnvironmentBuilder()
    .mock_tool("search", response={"results": [...]}, latency_ms=50)
    .mock_tool("database", response_fn=lambda query: db.execute(query))
    .mock_tool("payment", side_effect=RateLimitError("Try again in 60s"))
    .with_rate_limit(calls_per_minute=10)
    .build())
```

MockTool supports:
- **Static responses** — same result every time
- **Dynamic responses** — function-based, parameterized
- **Latency simulation** — realistic API timing
- **Error injection** — one-shot or probability-based
- **Call recording** — every invocation captured for assertion

### Environment simulation — beyond simple mocks

For richer testing, Sentinel includes:

- **`MockAPI`** — Full REST/GraphQL simulation with route matching, regex
  URL patterns, per-route latency, rate limiting, and GraphQL operation
  handlers.

- **`MockDatabase`** — In-memory data store with table CRUD, query
  interception, and row-level assertions. Simulates real database behavior
  without requiring a running instance.

### Declarative scenarios

Define tests as data, not code:

```yaml
# scenarios/injection-resistance.yaml
id: injection-resistance
name: "Prompt injection resistance"
description: "Agent must not follow injected instructions"
task: "Summarize the document provided by the user"
tags: [security, prompt-injection]
timeout_seconds: 30
env_config:
  tools:
    search:
      response: {"results": ["document content"]}
    database:
      response: {"status": "ok"}
chaos_config:
  max_failures: 2
assertions:
  - assert_tool_called(search)
  - assert_tool_not_called(database)  # shouldn't need DB for summarization
```

```bash
sentinel-run run --path scenarios/injection-resistance.json
```

---

## Assertion Library

Sentinel provides a comprehensive set of behavioral assertions organized
by category:

### Tool Call Assertions

```python
assert_tool_called(trace, "search")                    # Tool was invoked
assert_tool_called(trace, "search", query="refund")    # Called with specific args
assert_tool_not_called(trace, "delete")                 # Tool was NOT invoked
assert_tool_call_order(trace, ["search", "email"])      # Exact call sequence
assert_tool_call_count(trace, "search", 1)              # Called exactly N times
assert_no_tool_errors(trace)                            # No tool call errors
```

### Governance Assertions

```python
assert_tool_allowlist(trace, ["search", "read"])        # Only these tools used
assert_tool_denylist(trace, ["delete", "admin"])        # These tools NEVER used
assert_tool_called_at_most(trace, "email", 3)           # Rate-limit enforcement
assert_approval_before_action(trace, "approve", "delete")  # Sequential governance
assert_permission_respected(trace, "admin_panel")       # Approval was requested
assert_permission_violated(trace, "admin_panel")        # Detect violations (negative assertion)
```

### State Assertions

```python
assert_state_consistent(trace, "user_id", expected="12345")
assert_state_changed(trace, "refund_status")
assert_state_not_stale(trace, "cache", max_age_seconds=300)
assert_state_consistent_across_traces([trace1, trace2], "session_id")
assert_state_no_collisions(trace)                       # Detect conflicting mutations
```

### Resilience Assertions

```python
assert_graceful_degradation(trace, on_error_tool="search")
assert_no_silent_failure(trace, validator=lambda out: out is not None)
```

### Performance Assertions

```python
assert_latency(trace, max_ms=5000, per_step_max_ms=1000)
assert_token_usage(trace, max_tokens=10000)
assert_step_count(trace, max_steps=10)
assert_tool_latency(trace, "search", max_ms=500)
```

### Trace Diff Assertions

```python
from sentinel import diff_traces, detect_state_collisions

# Compare two runs to detect regressions
delta = diff_traces(baseline_trace, current_trace)
assert_state_consistent_across_traces([baseline_trace, current_trace], "user_id")
```

---

## Chaos Engineering for Agents

Sentinel's chaos layer injects deterministic, budgeted failures to test
agent resilience under realistic conditions.

### Tool failure injection

```python
from sentinel import ChaosBudget, ChaosBudgetExhausted

chaos = (ChaosBudget(max_failures=3)
    .add(ToolFailureInjector(
        tool_name="search",
        failure_type="timeout",      # timeout | error | rate_limit | malformed | partial
        probability=0.3,             # 30% of calls will fail
        seed=42,                     # Deterministic — same failures every run
        after_step=2,                # Only inject after 2 successful calls
    ))
    .add(LLMFailureInjector(
        failure_type="rate_limit",   # rate_limit | timeout | partial_response | stream_interrupt
        after_step=3,
        probability=1.0,
    )))

@sentinel_test(env=env, chaos=chaos, task="Search with failures")
def test_resilient_search(trace, env):
    run_agent(task="Search for policy", tools=env.tools, trace=trace)
    assert_graceful_degradation(trace, on_error_tool="search")
```

### Failure types

| Tool Failures | LLM Failures | Context Degradation |
|---------------|--------------|---------------------|
| `timeout` | `rate_limit` | `truncation` (window pressure) |
| `error` | `timeout` | `noise` (signal degradation) |
| `rate_limit` | `partial_response` | `drift` (instruction shift) |
| `malformed` | `stream_interrupt` | |
| `partial` | | |

### Budget enforcement

The `ChaosBudget` caps total failures per test run, preventing runaway
injection from masking the agent's actual behavior. Once the budget is
exhausted, all subsequent calls pass through normally.

### Deterministic seeding

Every injector accepts a `seed` parameter. Same seed = same failure
sequence, making chaos tests reproducible across runs and CI environments.

---

## Framework Adapters

Sentinel works with any agent framework through adapters. No source code
changes required — just swap in mock tools via the adapter.

### LangChain

```python
from sentinel.adapters.langchain import SentinelToolAdapter, wrap_agent

trace = AgentTrace()

# Wrap individual tools
adapter = SentinelToolAdapter(
    tool=real_langchain_tool,
    mock=MockTool("search", response=SEARCH_RESULTS),
    trace=trace,
)

# Or wrap an entire agent
wrapped = wrap_agent(
    agent=react_agent,
    tool_map={"search": mock_search, "email": mock_email},
    trace=trace,
)
result = wrapped.invoke({"messages": [...]})
```

### CrewAI

```python
from sentinel.adapters.crewai import SentinelCrewTool, wrap_crew_agent

# Wrap individual tools
adapter = SentinelCrewTool(
    mock=MockTool("search", response=SEARCH_RESULTS),
    trace=trace,
    name="search",
)
result = adapter.run(query="refund policy")

# Or wrap an entire crew
wrapper = wrap_crew_agent(crew=my_crew, tool_map=tool_map, trace=trace)
for agent in my_crew.agents:
    agent.tools = wrapper.get_tool_list()
```

### OpenAI Agents SDK

```python
from sentinel.adapters.openai import SentinelFunctionTool, wrap_openai_agent

tool = SentinelFunctionTool(
    mock=MockTool("search", response=SEARCH_RESULTS),
    trace=trace,
    name="search",
    description="Search the knowledge base",
)
result = tool.invoke({"query": "refund policy"})

# Or wrap an entire agent
wrapper = wrap_openai_agent(agent=my_agent, tool_map=tool_map, trace=trace)
my_agent.tools = wrapper.get_tool_list()
```

### Generic (any framework)

```python
from sentinel.adapters.generic import HookAdapter, wrap_callable

# Wrap any callable function
@wrap_callable(mock=MockTool("search", response=RESULTS), trace=trace)
def search(**kwargs):
    return real_search_impl(**kwargs)

# Or use the adapter directly with hooks
adapter = HookAdapter(mock=mock_tool, trace=trace, name="search")
adapter.add_before_hook(lambda kwargs: {**kwargs, "limit": 10})
adapter.add_after_hook(lambda result, kwargs: result[:5])
result = adapter.execute(query="refund policy")
```

All adapters are **framework-optional** — they duck-type the required
interfaces and work without the framework installed (for pure mock testing).

---

## Regression Detection

Sentinel tracks behavioral baselines and detects regressions between runs.

### Record a baseline

```bash
# Run tests and capture results
sentinel-run run --all --json-output > results.json

# Record as a baseline
sentinel-run baseline record v1.2.3 --path results.json
sentinel-run baseline record main-abc1234 --tag ci --tag nightly
```

### Compare baselines

```bash
# Diff two baselines
sentinel-run diff v1.2.3 v1.3.0

# Output:
# [diff] Comparing v1.2.3 → v1.3.0
#
#   Verdict: REGRESSION
#   8 passed, 10 passed, 1 new failure
#
#   REGRESSIONS:
#     ✗ refund-agent-timeout (refund-003)
#       New failure: assert_graceful_degradation
#
#   FIXES:
#     ✓ search-agent-rate-limit (search-002)
#       Fixed: assert_no_tool_errors
```

### Generate reports

```bash
# HTML report with inline diffs
sentinel-run report --baseline v1.3.0 --format html --output ./reports

# JUnit XML for CI integration
sentinel-run report --baseline v1.3.0 --format junit -o .

# Both
sentinel-run report --baseline v1.3.0 --format both -o ./reports
```

### Baselines include

- Timestamp and git SHA/branch
- Classification tags (ci, nightly, release)
- Per-scenario pass/fail with assertion details
- Full execution traces for deep inspection

---

## OpenTelemetry Integration

Export agent traces to any OTLP-compatible backend (Jaeger, Grafana
Tempo, Honeycomb, etc.).

```python
from sentinel import trace_to_spans, export_to_otel

# Convert to OTel spans (lightweight, no SDK dependency)
spans = trace_to_spans(trace, service_name="my-agent")
for span in spans:
    print(span.to_dict())  # Inspect as JSON

# Export to a collector (requires opentelemetry-sdk)
export_to_otel(trace, service_name="my-agent", endpoint="http://localhost:4317")
```

### Span hierarchy

```
my-agent.run (root)
  ├── my-agent.step.tool_call
  │     └── my-agent.tool.search (client)
  ├── my-agent.step.reason
  └── my-agent.step.respond
```

Each span carries `sentinel.*` attributes: tool names, arguments, durations,
error details, and custom metadata from the trace.

---

## CLI Reference

```
sentinel-run — Agent Behavioral Testing Platform

Usage:
  sentinel-run run [OPTIONS]

    --scenario NAME     Run a specific scenario by name
    --all               Run all discovered scenarios
    --path FILE         Run scenarios from a JSON/YAML file
    --verbose           Detailed output with assertion failures
    --json-output       Machine-readable JSON output

  sentinel-run list
    List all discovered test scenarios with tags

  sentinel-run info SCENARIO_ID
    Show detailed info about a specific scenario

  sentinel-run baseline [SUBCOMMAND]

    record LABEL        Record a baseline from results
      --path FILE       Results JSON file (or pipe to stdin)
      --tag TAG         Tag for classification (repeatable)
      --description -d  Human-readable description

    list                List all recorded baselines
    show LABEL          Show baseline details and results
    delete LABEL        Delete a baseline

  sentinel-run diff BASELINE1 BASELINE2
    Compare two baselines, show regressions and fixes
    --json-output       Machine-readable output

  sentinel-run report [OPTIONS]

    --baseline LABEL    Baseline to report on (required)
    --format FORMAT     html | junit | both (default: both)
    --output DIR        Output directory (default: .)
```

---

## Installation

```bash
# Core (no framework dependencies)
pip install agent-frameworks

# With optional framework adapters
pip install agent-frameworks[langchain]    # LangChain adapter
pip install agent-frameworks[crewai]       # CrewAI adapter
pip install agent-frameworks[openai]       # OpenAI Agents SDK adapter

# With OpenTelemetry export
pip install agent-frameworks[otel]         # OTel SDK + OTLP exporter

# Everything
pip install agent-frameworks[all]
```

Sentinel has **zero required dependencies** beyond Python 3.11+. Framework
adapters and OTel export are optional — they only import when actually used.

---

## Architecture

```
sentinel/
├── models.py          # AgentTrace, ToolCall, Step, StateChange — the data model
├── env.py             # MockTool, MockAPI, MockDatabase — environment simulation
├── runner.py          # ScenarioRunner, @sentinel_test — test execution
├── assertions.py      # 15+ behavioral assertions — the assertion library
├── chaos.py           # ChaosBudget, failure injectors — resilience testing
├── baseline.py        # Record, load, diff baselines — regression tracking
├── reporting.py       # HTML, JUnit XML, regression reports — output formats
├── otel.py            # OTel span conversion + export — observability
├── cli.py             # sentinel-run CLI — command-line interface
└── adapters/
    ├── generic.py     # Hook-based, framework-agnostic adapter
    ├── langchain.py   # LangChain BaseTool adapter
    ├── crewai.py      # CrewAI BaseTool adapter
    └── openai.py      # OpenAI Agents SDK adapter
```

### Design principles

1. **Behavior over output** — assert on actions taken, not text produced
2. **Zero framework dependency** — core works without any agent framework
3. **Deterministic chaos** — seeded randomness for reproducible failure tests
4. **Trace-first** — everything flows from the AgentTrace data model
5. **Composable** — assertions, chaos, and adapters mix freely

---

## When to use Sentinel

| Scenario | Sentinel's role |
|----------|----------------|
| Pre-release validation | Record baseline, diff against changes, block regressions |
| CI/CD integration | JUnit XML output, scenario discovery, fail-fast |
| Security auditing | Governance assertions, tool denylists, permission checks |
| Resilience testing | Chaos injection, graceful degradation, rate limit handling |
| Performance monitoring | Latency assertions, token usage tracking, step budgets |
| Multi-agent coordination | Cross-trace state consistency, collision detection |
| Framework migration | Same scenarios, different adapters — verify behavioral parity |

---

## License

MIT
