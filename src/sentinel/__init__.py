"""
Sentinel — Agent Behavioral Testing Platform
Tests what agents DO, not just what they SAY.
"""
__version__ = "0.1.0"

from sentinel.assertions import (
    assert_graceful_degradation,
    assert_latency,
    assert_no_silent_failure,
    assert_no_tool_errors,
    assert_state_changed,
    assert_state_consistent,
    assert_state_consistent_across_traces,
    assert_state_no_collisions,
    assert_state_not_stale,
    assert_step_count,
    assert_token_usage,
    assert_tool_call_count,
    assert_tool_call_order,
    assert_tool_called,
    assert_tool_latency,
    assert_tool_not_called,
    detect_state_collisions,
)
from sentinel.baseline import (
    BaselineMetadata,
    delete_baseline,
    list_baselines,
    load_baseline,
    record_baseline,
)
from sentinel.chaos import (
    CascadingFailures,
    ChaosBudget,
    ChaosBudgetExhausted,
    ContextDegradation,
    DegradationStrategy,
    DriftIntensity,
    SpecDrift,
)
from sentinel.env import (
    Environment,
    EnvironmentBuilder,
    MockAPI,
    MockDatabase,
    MockTool,
    MockToolCall,
    MockToolError,
    RateLimitError,
    TimeoutError,
)
from sentinel.models import AgentTrace, Step, StepAction, ToolCall
from sentinel.otel import (
    OTelSpan,
    SpanAttribute,
    SpanEvent,
    export_to_otel,
    trace_to_spans,
)
from sentinel.reporting import (
    RegressionReport,
    ResultDelta,
    ScenarioDelta,
    build_regression_report,
    diff_traces,
    generate_html_report,
    generate_junit_xml,
    generate_junit_xml_from_report,
)
from sentinel.runner import (
    AgentConfig,
    ScenarioRunner,
    SentinelResult,
    SentinelScenario,
    TestResult,
    TestScenario,
    sentinel_test,
)

__all__ = [
    # Env
    "Environment",
    "EnvironmentBuilder",
    "MockAPI",
    "MockDatabase",
    "MockTool",
    "MockToolCall",
    "MockToolError",
    "RateLimitError",
    "TimeoutError",
    # Models
    "AgentTrace",
    "ToolCall",
    "Step",
    "StepAction",
    # Runner
    "AgentConfig",
    "ScenarioRunner",
    "SentinelResult",
    "SentinelScenario",
    "TestResult",
    "TestScenario",
    "sentinel_test",
    # Assertions
    "assert_tool_called",
    "assert_tool_not_called",
    "assert_tool_call_order",
    "assert_tool_call_count",
    "assert_no_tool_errors",
    "assert_state_consistent",
    "assert_state_changed",
    "assert_graceful_degradation",
    "assert_no_silent_failure",
    "assert_latency",
    "assert_token_usage",
    "assert_step_count",
    "assert_tool_latency",
    "assert_state_not_stale",
    "assert_state_consistent_across_traces",
    "detect_state_collisions",
    "assert_state_no_collisions",
    # Chaos
    "ChaosBudget",
    "ChaosBudgetExhausted",
    "ContextDegradation",
    "CascadingFailures",
    "SpecDrift",
    "DegradationStrategy",
    "DriftIntensity",
    # Reporting
    "RegressionReport",
    "ScenarioDelta",
    "ResultDelta",
    "build_regression_report",
    "diff_traces",
    "generate_html_report",
    "generate_junit_xml",
    "generate_junit_xml_from_report",
    # OTel
    "OTelSpan",
    "SpanAttribute",
    "SpanEvent",
    "trace_to_spans",
    "export_to_otel",
    # Baseline
    "BaselineMetadata",
    "record_baseline",
    "load_baseline",
    "list_baselines",
    "delete_baseline",
]
