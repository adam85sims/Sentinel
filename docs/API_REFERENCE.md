# API Reference

> Sentinel's public API. All exports are defined in `__all__` for each module.

## sentinel.env

Mock environment layer for agent testing.

### Classes

```python
class MockTool:
    """Configurable mock tool with canned responses."""
    name: str
    response: Any = None
    response_fn: Callable = None
    side_effect: Exception = None
    latency_ms: float = 0.0
    error_probability: float = 0.0
    error_factory: Callable = None

class MockAPI:
    """Mock REST/GraphQL API with route matching."""
    base_url: str
    routes: dict  # pattern -> response
    rate_limit_per_minute: int = 0

class MockDatabase:
    """In-memory database with query interception."""
    name: str

class EnvironmentBuilder:
    """Fluent API for composing test environments."""
    def mock_tool(self, name: str, **kwargs) -> "EnvironmentBuilder"
    def mock_api(self, base_url: str, **kwargs) -> "EnvironmentBuilder"
    def mock_database(self, name: str) -> "EnvironmentBuilder"
    def with_rate_limit(self, calls_per_minute: int) -> "EnvironmentBuilder"
    def build(self) -> Environment

class Environment:
    """Composed test environment with tools, APIs, databases."""
    tools: Dict[str, MockTool]
    apis: Dict[str, MockAPI]
    databases: Dict[str, MockDatabase]
    def get_tool(self, name: str) -> Optional[MockTool]
    def get_api(self, name: str) -> Optional[MockAPI]
```

### Exceptions

```python
class MockToolError(Exception):
    status_code: int = 500

class RateLimitError(MockToolError):
    retry_after: float = 60.0
    status_code: int = 429

class TimeoutError(MockToolError):
    status_code: int = 408
```

## sentinel.models

Core data structures for agent traces.

```python
class StepAction(str, Enum):
    PLAN, TOOL_CALL, REASON, RESPOND, ERROR

class ErrorSeverity(str, Enum):
    LOW, MEDIUM, HIGH, CRITICAL

class Step:
    step_id: int
    action: StepAction
    input: Any = None
    output: Any = None
    duration_ms: float = 0.0
    tool_calls: List[ToolCall]
    error: Optional[Error] = None

class ToolCall:
    tool_name: str
    arguments: Dict[str, Any]
    result: Any = None
    duration_ms: float = 0.0
    error: Optional[str] = None
    timestamp: float

class AgentTrace:
    """Full execution trace of an agent run."""
    steps: List[Step]
    tool_calls: List[ToolCall]
    def add_step(self, step: Step) -> None
    def add_tool_call(self, tool_call: ToolCall) -> None
```

## sentinel.assertions

20+ behavioral assertions across 5 categories.

### Tool Call Assertions

```python
assert_tool_called(trace: AgentTrace, tool_name: str) -> None
assert_tool_not_called(trace: AgentTrace, tool_name: str) -> None
assert_tool_call_order(trace: AgentTrace, expected: List[str]) -> None
assert_tool_call_count(trace: AgentTrace, tool_name: str, expected_count: int) -> None
assert_no_tool_errors(trace: AgentTrace) -> None
assert_tool_called_at_most(trace: AgentTrace, tool_name: str, max_count: int) -> None
assert_tool_allowlist(trace: AgentTrace, allowed: List[str]) -> None
assert_tool_denylist(trace: AgentTrace, forbidden: List[str]) -> None
```

### State Assertions

```python
assert_state_consistent(trace: AgentTrace) -> None
assert_state_changed(trace: AgentTrace, key: str) -> None
assert_state_not_stale(trace: AgentTrace, key: str, max_age_seconds: float) -> None
assert_state_consistent_across_traces(traces: List[AgentTrace], key: str) -> None
assert_state_no_collisions(traces: List[AgentTrace]) -> None
```

### Governance Assertions

```python
assert_permission_respected(trace: AgentTrace, permission: str) -> None
assert_permission_violated(trace: AgentTrace, permission: str) -> None
assert_approval_before_action(trace: AgentTrace, action: str, approval: str) -> None
```

### Resilience Assertions

```python
assert_graceful_degradation(trace: AgentTrace, error_count: int) -> None
assert_no_silent_failure(trace: AgentTrace, validators: List[Callable]) -> None
```

### Performance Assertions

```python
assert_latency(trace: AgentTrace, max_ms: float) -> None
assert_token_usage(trace: AgentTrace, max_tokens: int) -> None
assert_step_count(trace: AgentTrace, min_steps: int, max_steps: int) -> None
assert_tool_latency(trace: AgentTrace, tool_name: str, max_ms: float) -> None
```

## sentinel.chaos

Failure injection for behavioral testing.

### Classes

```python
class ToolFailureInjector:
    """Inject tool-level failures."""
    def __init__(self, tool_name: str, failure_type: str,
                 probability: float = 1.0, seed: int = None)
    def wrap(self, mock: MockTool) -> None
    def make_validator(self) -> Callable

class LLMFailureInjector:
    """Inject LLM-level failures."""
    def __init__(self, failure_type: str, probability: float = 1.0)

class ContextDegradation:
    """Simulate context window pressure."""
    def __init__(self, strategy: DegradationStrategy, **kwargs)

class SpecDrift:
    """Simulate agent improvisation under pressure."""
    def __init__(self, intensity: DriftIntensity, drift_probability: float = 0.3)

class CascadingFailures:
    """Simulate multi-agent error propagation."""
    def __init__(self, dependency_graph: Dict[str, List[str]],
                 cascade_probability: float = 0.7, max_depth: int = 3)

class ChaosBudget:
    """Hard cap on total failures per run."""
    def __init__(self, max_failures: int = 10)
```

### Enums

```python
class DegradationStrategy(str, Enum):
    TRUNCATION, NOISE, DRIFT

class DriftIntensity(str, Enum):
    SUBTLE, MODERATE, AGGRESSIVE
```

## sentinel.runner

Test execution and scenario management.

```python
class AgentConfig:
    """Configuration for agent under test."""
    agent_type: Optional[str] = None
    model: str = "unknown"
    tools: List[str] = []
    prompt: str = ""
    kwargs: Dict[str, Any] = {}
    factory: Optional[Callable] = None

class SentinelScenario:
    """Declarative test scenario."""
    id: str
    name: str
    description: str = ""
    task: str = ""
    env_config: Dict[str, Any] = {}
    chaos_config: Dict[str, Any] = {}
    assertions: List[Callable] = []
    timeout_seconds: int = 30
    tags: List[str] = []

class ScenarioRunner:
    """Executes test scenarios."""
    def run(self, scenario: SentinelScenario, agent_fn: Callable = None) -> SentinelResult
    def run_batch(self, scenarios: List[SentinelScenario], agent_fn: Callable = None) -> List[SentinelResult]

def sentinel_test(env: Environment = None, task: str = "", **kwargs) -> Callable
```

## sentinel.reporting

Regression detection and report generation.

```python
class ResultDelta(Enum):
    NEW_PASS, NEW_FAIL, STILL_PASS, STILL_FAIL, NEW_SCENARIO, REMOVED

class RegressionReport:
    """Compare current results against baseline."""
    def __init__(self, baseline: dict, current: List[SentinelResult])
    def to_dict(self) -> dict
    def to_html(self) -> str
    def to_junit_xml(self) -> str
```

## sentinel.baseline

JSON-based baseline storage with git integration.

```python
def record_baseline(results: List[SentinelResult], path: str = None) -> str
def load_baseline(path: str) -> dict
def compare_baselines(old: dict, new: dict) -> RegressionReport
```

## sentinel.otel

OpenTelemetry span model (no SDK dependency for core).

```python
class OTelSpan:
    """Lightweight span representation."""
    name: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    start_time: float
    end_time: Optional[float]
    attributes: Dict[str, SpanAttribute]
    events: List[SpanEvent]
    status: SpanStatus

def trace_to_spans(trace: AgentTrace) -> List[OTelSpan]
def export_spans_otlp(spans: List[OTelSpan], endpoint: str = None) -> None
```
