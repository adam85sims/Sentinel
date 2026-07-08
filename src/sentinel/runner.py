"""Sentinel test runner — pytest-native test execution with declarative scenarios.

Provides the ``@sentinel_test`` decorator for defining behavioral tests
in a declarative way, and the ``ScenarioRunner`` for loading/executing
scenarios programmatically or via CLI.

Usage with pytest decorator:
    import pytest
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
        # trace is pre-created AgentTrace, env is the built Environment
        # Run your agent here, then assert
        assert_tool_called(trace, "search")

Usage with ScenarioRunner:
    from sentinel.runner import ScenarioRunner, SentinelScenario

    scenario = SentinelScenario(
        id="refund-001",
        name="Refund agent handles timeout",
        task="Process refund for order #123",
        env_config={"tools": {"search": {"response": "no results"}}},
    )
    runner = ScenarioRunner()
    result = runner.run(scenario, agent_fn=my_agent)
"""

from __future__ import annotations

import functools
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from sentinel.env import Environment, EnvironmentBuilder, MockTool
from sentinel.models import AgentTrace, Error, ErrorSeverity, Step, StepAction


# ──────────────────────────────────────────────────────
# AgentConfig — how to instantiate an agent
# ──────────────────────────────────────────────────────


@dataclass
class AgentConfig:
    """Configuration for instantiating an agent under test.

    Describes HOW to create the agent, not the agent itself.
    The runner uses this to construct the agent before each test.

    Attributes:
        agent_type: Import path or class name for the agent.
                    e.g. "my_agent:RefundAgent" or a callable factory.
        model: Model identifier (for display/logging; not used to instantiate).
        tools: List of tool names this agent is expected to use.
        prompt: System prompt or prompt template (for display/logging).
        kwargs: Extra keyword arguments passed to the agent constructor.
        factory: A callable that returns the agent instance.
                 If provided, takes precedence over agent_type.
    """

    agent_type: Optional[str] = None
    model: str = "unknown"
    tools: List[str] = field(default_factory=list)
    prompt: str = ""
    kwargs: Dict[str, Any] = field(default_factory=dict)
    factory: Optional[Callable[..., Any]] = field(default=None, repr=False)


# ──────────────────────────────────────────────────────
# SentinelScenario — declarative test definition
# Named "Sentinel" prefix to avoid pytest collection.
# ──────────────────────────────────────────────────────


@dataclass
class SentinelScenario:
    """A declarative test scenario for sentinel.

    Encapsulates everything needed to run a behavioral test:
    the agent config, environment setup, chaos injection rules,
    task description, and assertions.

    Scenarios can be defined in code (via @sentinel_test) or loaded
    from YAML/JSON files (via ScenarioRunner).
    """

    id: str
    name: str
    description: str = ""
    agent_config: Optional[AgentConfig] = None
    environment: Optional[Environment] = None
    env_config: Dict[str, Any] = field(default_factory=dict)
    chaos_config: Dict[str, Any] = field(default_factory=dict)
    task: str = ""
    assertions: List[Callable[..., None]] = field(default_factory=list)
    timeout_seconds: int = 30
    tags: List[str] = field(default_factory=list)


# TestScenario is the canonical public name (architecture §6.1).
# SentinelScenario is kept for backward compatibility.
TestScenario = SentinelScenario


# ──────────────────────────────────────────────────────
# SentinelResult — outcome of a scenario run
# Named "Sentinel" prefix to avoid pytest collection.
# ──────────────────────────────────────────────────────


@dataclass
class SentinelAssertionResult:
    """Result of a single assertion check."""

    assertion_name: str
    passed: bool
    error_message: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class SentinelResult:
    """Outcome of running a single test scenario.

    Captures pass/fail, the full trace, assertion results, and timing.
    """

    scenario_id: str
    scenario_name: str
    passed: bool
    trace: AgentTrace = field(default_factory=AgentTrace)
    assertion_results: List[SentinelAssertionResult] = field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def summary(self) -> str:
        """One-line human-readable summary."""
        status = "PASS" if self.passed else "FAIL"
        n_assertions = len(self.assertion_results)
        n_passed = sum(1 for a in self.assertion_results if a.passed)
        return (
            f"[{status}] {self.scenario_name} "
            f"({n_passed}/{n_assertions} assertions, "
            f"{self.duration_ms:.0f}ms)"
        )

    def failed_assertions(self) -> List[SentinelAssertionResult]:
        """Get all failed assertions."""
        return [a for a in self.assertion_results if not a.passed]


# TestResult is the canonical public name (architecture §6.2).
# SentinelResult is kept for backward compatibility.
TestResult = SentinelResult


# ──────────────────────────────────────────────────────
# ScenarioRunner — execute scenarios
# ──────────────────────────────────────────────────────


class ScenarioRunner:
    """Executes test scenarios against agents.

    The runner:
    1. Builds the environment from config (if not pre-built)
    2. Constructs the agent (if agent_config.factory is provided)
    3. Creates an AgentTrace
    4. Invokes the agent's task
    5. Runs assertions against the trace
    6. Returns a SentinelResult

    Usage:
        runner = ScenarioRunner()
        result = runner.run(scenario, agent_fn=my_agent_fn)
        assert result.passed
    """

    def run(
        self,
        scenario: SentinelScenario,
        agent_fn: Optional[Callable[..., Any]] = None,
        env: Optional[Environment] = None,
    ) -> SentinelResult:
        """Run a single test scenario.

        Args:
            scenario: The test scenario to execute.
            agent_fn: Callable that accepts (task, env, trace) and runs
                      the agent. If None, scenario.agent_config.factory is used.
            env: Pre-built environment. Overrides scenario.environment.

        Returns:
            SentinelResult with pass/fail status and assertion details.
        """
        start_time = time.time()
        trace = AgentTrace()

        # Resolve environment
        if env is not None:
            resolved_env = env
        elif scenario.environment is not None:
            resolved_env = scenario.environment
        elif scenario.env_config:
            resolved_env = self._build_env(scenario.env_config)
        else:
            resolved_env = Environment()

        # Resolve agent function
        if agent_fn is None and scenario.agent_config:
            agent_fn = scenario.agent_config.factory

        # Run the agent
        try:
            if agent_fn is not None:
                agent_fn(
                    task=scenario.task,
                    env=resolved_env,
                    trace=trace,
                )
            trace.finish()
        except Exception as exc:
            trace.add_error(
                Error(
                    message=f"Agent execution failed: {exc}",
                    severity=ErrorSeverity.CRITICAL,
                    recoverable=False,
                )
            )
            trace.finish()
            duration_ms = (time.time() - start_time) * 1000
            return SentinelResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                passed=False,
                trace=trace,
                duration_ms=duration_ms,
                error=f"Agent crashed: {exc}\n{traceback.format_exc()}",
            )

        # Run assertions
        assertion_results: List[SentinelAssertionResult] = []
        all_passed = True

        for assertion in scenario.assertions:
            a_start = time.time()
            try:
                assertion(trace)
                assertion_results.append(
                    SentinelAssertionResult(
                        assertion_name=getattr(assertion, "__name__", str(assertion)),
                        passed=True,
                        duration_ms=(time.time() - a_start) * 1000,
                    )
                )
            except (AssertionError, Exception) as exc:
                all_passed = False
                assertion_results.append(
                    SentinelAssertionResult(
                        assertion_name=getattr(assertion, "__name__", str(assertion)),
                        passed=False,
                        error_message=str(exc),
                        duration_ms=(time.time() - a_start) * 1000,
                    )
                )

        duration_ms = (time.time() - start_time) * 1000
        return SentinelResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            passed=all_passed,
            trace=trace,
            assertion_results=assertion_results,
            duration_ms=duration_ms,
        )

    def run_batch(
        self,
        scenarios: List[SentinelScenario],
        agent_fn: Optional[Callable[..., Any]] = None,
    ) -> List[SentinelResult]:
        """Run multiple scenarios sequentially.

        Returns a list of SentinelResults in the same order as the input.
        """
        return [self.run(scenario, agent_fn=agent_fn) for scenario in scenarios]

    def _build_env(self, config: Dict[str, Any]) -> Environment:
        """Build an Environment from a configuration dict.

        Config format:
            {
                "tools": {
                    "tool_name": {"response": ..., "latency_ms": ...},
                    ...
                },
                "rate_limit": {"calls_per_minute": 10}
            }
        """
        builder = EnvironmentBuilder()
        tools_config = config.get("tools", {})

        for name, tool_cfg in tools_config.items():
            builder.mock_tool(
                name=name,
                response=tool_cfg.get("response"),
                response_fn=tool_cfg.get("response_fn"),
                latency_ms=tool_cfg.get("latency_ms", 0.0),
            )

        rate_limit = config.get("rate_limit")
        if rate_limit:
            builder.with_rate_limit(**rate_limit)

        return builder.build()


# ──────────────────────────────────────────────────────
# @sentinel_test — pytest decorator
# ──────────────────────────────────────────────────────


def sentinel_test(
    env: Optional[Union[Environment, EnvironmentBuilder]] = None,
    chaos: Any = None,
    task: str = "",
    timeout_seconds: int = 30,
    tags: Optional[List[str]] = None,
) -> Callable:
    """Pytest decorator for declarative sentinel test definition.

    Wraps a test function so it receives a pre-built ``trace`` (AgentTrace)
    and ``env`` (Environment) as arguments. The test function can then run
    its agent and assert behaviors.

    The decorator handles:
    - Creating and injecting the AgentTrace
    - Building the environment if an EnvironmentBuilder is provided
    - Optionally wiring chaos injectors into the environment
    - Timing the test execution

    Args:
        env: Pre-built Environment or EnvironmentBuilder. If None, an empty
             Environment is created.
        chaos: ChaosBudget for failure injection. Applied to the env's tools.
        task: The task description for the agent (for logging).
        timeout_seconds: Maximum allowed test duration (informational).
        tags: Classification tags for the test.

    Example:
        @sentinel_test(
            env=(EnvironmentBuilder()
                .mock_tool("search", response=SEARCH_RESULTS)
                .build()),
            task="Search for refund policy",
        )
        def test_search_agent(trace, env):
            # Run agent, then assert
            assert_tool_called(trace, "search")
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Build environment
            if isinstance(env, EnvironmentBuilder):
                resolved_env = env.build()
            elif isinstance(env, Environment):
                resolved_env = env
            else:
                resolved_env = Environment()

            # Apply chaos injectors if provided
            if chaos is not None:
                _apply_chaos(chaos, resolved_env)

            # Create trace
            trace = AgentTrace()

            # Inject trace and env into kwargs for the test function
            kwargs["trace"] = trace
            kwargs["env"] = resolved_env

            # Run the test
            return fn(*args, **kwargs)

        # Attach metadata for discovery/reporting
        wrapper._sentinel_test = True  # type: ignore[attr-defined]
        wrapper._sentinel_task = task  # type: ignore[attr-defined]
        wrapper._sentinel_tags = tags or []  # type: ignore[attr-defined]
        wrapper._sentinel_timeout = timeout_seconds  # type: ignore[attr-defined]
        wrapper._sentinel_chaos = chaos  # type: ignore[attr-defined]

        return wrapper

    return decorator


def _apply_chaos(chaos: Any, env: Environment) -> None:
    """Wire chaos injectors into the environment's tools.

    If ``chaos`` is a ChaosBudget, wraps matching tools with their
    configured injectors.
    """
    try:
        from sentinel.chaos import ChaosBudget
    except ImportError:
        return

    if not isinstance(chaos, ChaosBudget):
        return

    for injector in chaos.get_injectors():
        # Try to find a matching ToolFailureInjector
        from sentinel.chaos import ToolFailureInjector

        if isinstance(injector, ToolFailureInjector):
            tool = env.get_tool(injector.tool_name)
            if tool is not None:
                injector.wrap(tool)
