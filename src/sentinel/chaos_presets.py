# Chaos Scenario Presets
#
# Ready-made chaos configurations for common production failure scenarios.
# Import and use directly, or customize for your specific test needs.
#
# Usage:
#   from sentinel.chaos.presets import PRODUCTION_INCIDENT, DEPLOY_FRIDAY
#   from sentinel.chaos import ChaosBudget
#
#   budget = ChaosBudget(max_failures=10)
#   for injector in PRODUCTION_INCIDENT:
#       injector.wrap(tool_mock)

from sentinel.chaos import (
    CascadingFailures,
    ClockSkew,
    ContextDegradation,
    DegradationStrategy,
    MemoryPressure,
    NetworkPartition,
    ToolFailureInjector,
)

# ──────────────────────────────────────────────────────
# Production Incident — database goes down
# ──────────────────────────────────────────────────────

PRODUCTION_INCIDENT = [
    # Database fails — cascades to API
    ToolFailureInjector(
        tool_name="database",
        failure_type="error",
        probability=0.8,
        seed=42,
    ),
    # API gets overwhelmed
    ToolFailureInjector(
        tool_name="api",
        failure_type="rate_limit",
        probability=0.4,
        seed=42,
    ),
    # Cache serves stale data
    ToolFailureInjector(
        tool_name="cache",
        failure_type="partial",
        probability=0.3,
        seed=42,
    ),
    # Context degrades as agent tries to recover
    ContextDegradation(
        strategy=DegradationStrategy.NOISE,
        degradation_rate=0.2,
    ),
]

# ──────────────────────────────────────────────────────
# Deploy Friday — everything breaks at once
# ──────────────────────────────────────────────────────

DEPLOY_FRIDAY = [
    # Deploy tool fails
    ToolFailureInjector(
        tool_name="deploy",
        failure_type="error",
        probability=0.9,
        seed=42,
    ),
    # Health checks timeout
    ToolFailureInjector(
        tool_name="health_check",
        failure_type="timeout",
        probability=0.6,
        seed=42,
    ),
    # DNS intermittently fails
    ToolFailureInjector(
        tool_name="dns",
        failure_type="timeout",
        probability=0.3,
        seed=42,
    ),
    # Context gets noisy from error logs
    ContextDegradation(
        strategy=DegradationStrategy.NOISE,
        degradation_rate=0.3,
    ),
]

# ──────────────────────────────────────────────────────
# Traffic Spike — system under load
# ──────────────────────────────────────────────────────

TRAFFIC_SPIKE = [
    # Rate limits hit across services
    ToolFailureInjector(
        tool_name="api",
        failure_type="rate_limit",
        probability=0.5,
        seed=42,
    ),
    ToolFailureInjector(
        tool_name="search",
        failure_type="rate_limit",
        probability=0.4,
        seed=42,
    ),
    # Database timeouts under load
    ToolFailureInjector(
        tool_name="database",
        failure_type="timeout",
        probability=0.3,
        seed=42,
    ),
    # Cascading failures from database
    CascadingFailures(
        cascade_probability=0.6,
        max_cascade_depth=2,
    ),
    # Memory pressure from high traffic
    MemoryPressure(
        max_context_tokens=8192,
        pressure_threshold=0.7,
        eviction_strategy="fifo",
    ),
]

# ──────────────────────────────────────────────────────
# Network Partition — partial connectivity
# ──────────────────────────────────────────────────────

NETWORK_PARTITION = [
    # API can reach database but not external services
    NetworkPartition(
        connectivity={
            "api": ["database", "cache"],
            "database": ["api"],
            "cache": ["api"],
            "external_api": [],  # Isolated
            "webhook": [],       # Isolated
        },
        partition_probability=1.0,
    ),
    # Context degrades during partition
    ContextDegradation(
        strategy=DegradationStrategy.TRUNCATION,
    ),
]

# ──────────────────────────────────────────────────────
# Time Travel — clock skew across services
# ──────────────────────────────────────────────────────

TIME_TRAVEL = [
    # Auth service has 5-minute clock skew
    ClockSkew(
        skew_seconds=-300,
        affected_tools=["auth", "token_refresh"],
    ),
    # API calls fail due to stale tokens
    ToolFailureInjector(
        tool_name="api",
        failure_type="error",
        probability=0.4,
        error_message="Token expired due to clock skew",
        seed=42,
    ),
]

# ──────────────────────────────────────────────────────
# Memory Leak — progressive context exhaustion
# ──────────────────────────────────────────────────────

MEMORY_LEAK = [
    MemoryPressure(
        max_context_tokens=4096,
        pressure_threshold=0.6,
        eviction_strategy="fifo",
        gc_pause_ms=100,  # GC pauses under pressure
        oom_probability=0.1,
    ),
    # As context fills, agent makes more tool calls
    ToolFailureInjector(
        tool_name="search",
        failure_type="timeout",
        probability=0.2,
        seed=42,
    ),
]

# ──────────────────────────────────────────────────────
# Complete Outage — everything is down
# ──────────────────────────────────────────────────────

COMPLETE_OUTAGE = [
    ToolFailureInjector(
        tool_name="database",
        failure_type="error",
        probability=1.0,
    ),
    ToolFailureInjector(
        tool_name="api",
        failure_type="timeout",
        probability=1.0,
    ),
    ToolFailureInjector(
        tool_name="cache",
        failure_type="error",
        probability=1.0,
    ),
    ToolFailureInjector(
        tool_name="search",
        failure_type="timeout",
        probability=1.0,
    ),
    NetworkPartition(
        connectivity={
            "database": [],
            "api": [],
            "cache": [],
            "search": [],
        },
        partition_probability=1.0,
    ),
]

# ──────────────────────────────────────────────────────
# Registry for easy lookup
# ──────────────────────────────────────────────────────

PRESETS = {
    "production_incident": PRODUCTION_INCIDENT,
    "deploy_friday": DEPLOY_FRIDAY,
    "traffic_spike": TRAFFIC_SPIKE,
    "network_partition": NETWORK_PARTITION,
    "time_travel": TIME_TRAVEL,
    "memory_leak": MEMORY_LEAK,
    "complete_outage": COMPLETE_OUTAGE,
}
