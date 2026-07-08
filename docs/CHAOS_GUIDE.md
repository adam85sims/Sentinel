# Chaos Guide — Failure Injection Patterns

> Sentinel's chaos module is the commercial differentiator.
> It simulates real production failure modes that no other tool tests.

## Why Chaos?

88% of AI agents fail in production. The dominant failure modes are
operational — tool errors, memory issues, edge cases — NOT hallucination.
Yet no testing tool simulates these failures before deployment.

Sentinel's chaos module fills that gap.

## The Injectors

### ToolFailureInjector

Simulates tool-level failures: timeouts, errors, rate limits, malformed
responses, and partial failures.

```python
from sentinel.chaos import ToolFailureInjector
from sentinel.env import MockTool

mock = MockTool("search", response="ok")

# Timeout every call
injector = ToolFailureInjector(
    tool_name="search",
    failure_type="timeout",
    probability=1.0,  # 100% failure rate
)
injector.wrap(mock)

# Rate limit every 3rd call
injector = ToolFailureInjector(
    tool_name="search",
    failure_type="rate_limit",
    probability=0.33,  # ~33% failure rate
    seed=42,  # Deterministic
)
injector.wrap(mock)
```

**Failure types:**
- `timeout` — Request takes too long (408)
- `error` — Internal server error (500)
- `rate_limit` — Too many requests (429)
- `malformed` — Garbled response
- `partial` — Incomplete response

### LLMFailureInjector

Simulates LLM-level failures: rate limits, timeouts, partial responses,
stream interrupts.

```python
from sentinel.chaos import LLMFailureInjector

injector = LLMFailureInjector(
    failure_type="stream_interrupt",
    probability=0.2,
)
```

### ContextDegradation

Simulates context window pressure with three strategies:

```python
from sentinel.chaos import ContextDegradation, DegradationStrategy

# Truncation — oldest messages dropped first
degradation = ContextDegradation(
    strategy=DegradationStrategy.TRUNCATION,
    max_context_tokens=4096,
)

# Noise — irrelevant context injected
degradation = ContextDegradation(
    strategy=DegradationStrategy.NOISE,
    noise_level=0.3,
)

# Drift — agent's understanding gradually shifts
degradation = ContextDegradation(
    strategy=DegradationStrategy.DRIFT,
    drift_rate=0.1,
)
```

**The quadratic curve:** ContextDegradation uses a quadratic acceleration
curve. This matches how context window pressure actually works — the last
20% of the context window is much worse than the first 20%. This is a
realistic simulation of production behavior.

### CascadingFailures

Simulates multi-agent error propagation:

```python
from sentinel.chaos import CascadingFailures

cascade = CascadingFailures(
    dependency_graph={
        "database": ["api_server"],
        "api_server": ["ui"],
        "scheduler": ["database", "cache"],
    },
    cascade_probability=0.7,  # 70% chance error propagates
    max_depth=3,              # Max cascade hops
    propagation_delay=0.1,    # Seconds between hops
)

# When database fails, api_server likely fails too
# When api_server fails, ui likely fails too
```

### SpecDrift

Simulates agent improvisation under pressure:

```python
from sentinel.chaos import SpecDrift, DriftIntensity

drift = SpecDrift(
    intensity=DriftIntensity.MODERATE,
    drift_probability=0.3,
)

# Agent starts cutting corners when under pressure
# - Skipping validation steps
# - Using outdated information
# - Making assumptions instead of checking
```

### ChaosBudget

Hard cap on total failures per test run:

```python
from sentinel.chaos import ChaosBudget

budget = ChaosBudget(max_failures=10)

# Even with multiple injectors, total failures won't exceed 10
# This prevents cascade from making tests unrecoverable
```

## Combining Injectors

Real production failures are rarely single-injector. Combine them:

```python
from sentinel.chaos import (
    ToolFailureInjector,
    ContextDegradation,
    CascadingFailures,
    ChaosBudget,
    DegradationStrategy,
)

# Budget: max 5 failures total
budget = ChaosBudget(max_failures=5)

# Search tool fails 30% of the time
search_injector = ToolFailureInjector(
    tool_name="search",
    failure_type="timeout",
    probability=0.3,
    seed=42,
)

# Context degrades over time
context = ContextDegradation(
    strategy=DegradationStrategy.TRUNCATION,
    max_context_tokens=2048,
)

# Database failure cascades to API
cascade = CascadingFailures(
    dependency_graph={"database": ["api"]},
    cascade_probability=0.5,
)

# Apply to mocks
search_injector.wrap(search_mock)
```

## The make_validator Pattern

Every chaos injector produces a validator that plugs into assertions:

```python
from sentinel.chaos import ToolFailureInjector
from sentinel.assertions import assert_no_silent_failure

injector = ToolFailureInjector(
    tool_name="search",
    failure_type="error",
    probability=0.5,
    seed=42,
)

# Get a validator function
validator = injector.make_validator()

# Use with assert_no_silent_failure
# This catches cases where the agent silently ignores failures
assert_no_silent_failure(trace, validators=[validator])
```

This is clean architecture — chaos and assertions don't depend on each
other directly. The validator is the bridge.

## Production Scenarios

### "Deploy Friday"
```python
# Multiple things failing at once
injectors = [
    ToolFailureInjector("deploy", failure_type="error", probability=0.8),
    ToolFailureInjector("health_check", failure_type="timeout", probability=0.5),
    ContextDegradation(strategy=DegradationStrategy.NOISE, noise_level=0.2),
]
```

### "Traffic Spike"
```python
# Rate limits and timeouts under load
injectors = [
    ToolFailureInjector("api", failure_type="rate_limit", probability=0.4),
    ToolFailureInjector("database", failure_type="timeout", probability=0.2),
    CascadingFailures(
        dependency_graph={"database": ["api", "cache"]},
        cascade_probability=0.6,
    ),
]
```

### "Network Partition"
```python
# Partial connectivity
injectors = [
    ToolFailureInjector("external_api", failure_type="timeout", probability=0.7),
    ToolFailureInjector("database", failure_type="error", probability=0.3),
    ContextDegradation(
        strategy=DegradationStrategy.DRIFT,
        drift_rate=0.15,  # Agent's context drifts during partition
    ),
]
```

## Deterministic Testing

All injectors accept a `seed` parameter. This makes chaos deterministic:

```python
# Same seed = same failure pattern
injector1 = ToolFailureInjector(..., seed=42)
injector2 = ToolFailureInjector(..., seed=42)

# Both will fail on the same calls
```

This is critical for regression testing — you can reproduce exact
failure patterns across runs.
