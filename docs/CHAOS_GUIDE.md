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
    cascade_probability=0.7,  # 70% chance error propagates
    max_cascade_depth=3,      # Max cascade hops
    propagation_delay_steps=1, # Steps between cascade levels
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
    cascade_probability=0.5,
    max_cascade_depth=3,
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
        cascade_probability=0.6,
        max_cascade_depth=3,
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

## Advanced Injectors (Phase 6)

### NetworkPartition

Simulates partial network connectivity between services:

```python
from sentinel.chaos import NetworkPartition

partition = NetworkPartition(
    connectivity={
        "api": ["db", "cache"],      # api can reach db and cache
        "db": ["api"],               # db can reach api
        "cache": [],                 # cache is isolated
        "external_api": [],          # external API is unreachable
    },
    partition_probability=1.0,  # Always partitioned
    heal_after_calls=10,        # Heal after 10 failed calls
)

# Wrap tools
wrapper = partition.wrap(api_mock)
```

**Real-world:** Cloud provider outages, DNS failures, cross-AZ connectivity issues.

### ClockSkew

Simulates time synchronization issues:

```python
from sentinel.chaos import ClockSkew

skew = ClockSkew(
    skew_seconds=-300,  # Agent clock is 5 minutes behind
    drift_rate=10,      # Drifts 10s more each call
    affected_tools=["auth", "token_refresh"],
)

# Timestamps are offset
ts = skew.get_skewed_timestamp(tool_name="auth")  # Behind by 300s + drift
```

**Real-world:** NTP failures, VM clock drift, JWT token expiration mismatches.

### MemoryPressure

Simulates context window exhaustion:

```python
from sentinel.chaos import MemoryPressure

pressure = MemoryPressure(
    max_context_tokens=4096,
    pressure_threshold=0.8,  # Start evicting at 80%
    eviction_strategy="fifo",  # or "priority", "random"
    gc_pause_ms=100,  # GC pauses under pressure
    oom_probability=0.1,  # 10% chance of OOM at overflow
)

# Simulate token usage
result = pressure.simulate_token_usage(500)  # None if OK
result = pressure.simulate_token_usage(3000)  # May trigger eviction
```

**Real-world:** Long-running conversations, context window hard limits, OOM kills.

## Chaos Presets

Ready-made configurations for common scenarios:

```python
from sentinel.chaos_presets import (
    PRODUCTION_INCIDENT,  # Database down + cascading failures
    DEPLOY_FRIDAY,        # Everything breaks at once
    TRAFFIC_SPIKE,        # Rate limits + timeouts under load
    NETWORK_PARTITION,    # Partial connectivity
    TIME_TRAVEL,          # Clock skew + auth failures
    MEMORY_LEAK,          # Progressive context exhaustion
    COMPLETE_OUTAGE,      # Everything is down
)

# Use a preset
for injector in PRODUCTION_INCIDENT:
    if hasattr(injector, 'wrap'):
        injector.wrap(your_mock_tool)
```

### Preset Descriptions

| Preset | Injectors | Scenario |
|--------|-----------|----------|
| PRODUCTION_INCIDENT | ToolFailure (db, api, cache) + ContextDegradation | Database fails, API gets rate-limited, cache serves stale data |
| DEPLOY_FRIDAY | ToolFailure (deploy, health_check, dns) + ContextDegradation | Deploy fails, health checks timeout, DNS intermittent |
| TRAFFIC_SPIKE | ToolFailure (api, search, db) + CascadingFailures + MemoryPressure | Rate limits hit, db timeouts, cascading failures |
| NETWORK_PARTITION | NetworkPartition + ContextDegradation | Partial connectivity, context truncation |
| TIME_TRAVEL | ClockSkew + ToolFailure | Clock skew causes auth failures |
| MEMORY_LEAK | MemoryPressure + ToolFailure | Context fills up, GC pauses, OOM kills |
| COMPLETE_OUTAGE | ToolFailure (all) + NetworkPartition | Everything is down |
