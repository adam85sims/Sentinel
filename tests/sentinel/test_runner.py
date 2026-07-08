"""Tests for Sentinel runner — @sentinel_test decorator, ScenarioRunner, SentinelResult."""

import functools
import pytest
from sentinel.runner import (
    AgentConfig,
    SentinelAssertionResult,
    ScenarioRunner,
    SentinelResult,
    SentinelScenario,
    sentinel_test,
)
from sentinel.env import Environment, EnvironmentBuilder, MockTool, MockToolError
from sentinel.models import AgentTrace
from sentinel.assertions import assert_tool_called, assert_tool_not_called


# ──────────────────────────────────────────────────────
# @sentinel_test decorator
# ──────────────────────────────────────────────────────


class TestSentinelTestDecorator:
    def test_injects_trace_and_env(self):
        """Decorator injects trace and env kwargs."""
        received = {}

        @sentinel_test(
            env=EnvironmentBuilder().mock_tool("x", response="ok").build(),
        )
        def my_test(trace, env):
            received["trace"] = trace
            received["env"] = env

        my_test()

        assert isinstance(received["trace"], AgentTrace)
        assert isinstance(received["env"], Environment)
        assert received["env"].get_tool("x") is not None

    def test_builds_from_environment_builder(self):
        """Decorator builds environment from EnvironmentBuilder."""
        received = {}

        @sentinel_test(
            env=(EnvironmentBuilder()
                .mock_tool("search", response="results")
                .mock_tool("email", response="sent")
                .build()),
        )
        def my_test(trace, env):
            received["env"] = env

        my_test()

        assert received["env"].get_tool("search") is not None
        assert received["env"].get_tool("email") is not None

    def test_empty_env_when_none(self):
        """Decorator creates empty environment when env is None."""
        received = {}

        @sentinel_test()
        def my_test(trace, env):
            received["env"] = env

        my_test()

        assert received["env"].get_tools() == {}

    def test_preserves_function_metadata(self):
        """Decorator preserves the wrapped function's name and docstring."""
        @sentinel_test()
        def test_my_agent():
            """This tests the agent."""
            pass

        assert test_my_agent.__name__ == "test_my_agent"
        assert test_my_agent.__doc__ == "This tests the agent."

    def test_sets_sentinel_metadata(self):
        """Decorator sets sentinel-specific metadata."""
        @sentinel_test(
            task="Search for docs",
            tags=["search", "resilience"],
            timeout_seconds=60,
        )
        def test_search():
            pass

        assert test_search._sentinel_test is True
        assert test_search._sentinel_task == "Search for docs"
        assert test_search._sentinel_tags == ["search", "resilience"]
        assert test_search._sentinel_timeout == 60


# ──────────────────────────────────────────────────────
# ScenarioRunner
# ──────────────────────────────────────────────────────


def _simple_agent(task: str, env: Environment, trace: AgentTrace) -> None:
    """Minimal agent: calls 'search' tool, records a step."""
    search_tool = env.get_tool("search")
    if search_tool:
        result = search_tool(query=task)
        from sentinel.models import Step, StepAction, ToolCall
        step = Step(
            step_id=1,
            action=StepAction.TOOL_CALL,
            input=task,
            output=result,
            tool_calls=[ToolCall(tool_name="search", arguments={"query": task}, result=result)],
        )
        trace.add_step(step)
    else:
        from sentinel.models import Step, StepAction
        trace.add_step(Step(step_id=1, action=StepAction.RESPOND, output="no tools"))


class TestScenarioRunner:
    def test_run_passes(self):
        """Runner passes when assertions succeed."""
        env = EnvironmentBuilder().mock_tool("search", response="results").build()

        # Runner calls assertion(trace, env), so we bind tool_name with partial
        check_search = functools.partial(assert_tool_called, tool_name="search")
        scenario = SentinelScenario(
            id="test-001",
            name="Search works",
            task="find stuff",
            assertions=[check_search],
        )

        runner = ScenarioRunner()
        result = runner.run(scenario, agent_fn=_simple_agent, env=env)

        assert result.passed
        assert result.scenario_id == "test-001"
        assert len(result.assertion_results) == 1
        assert result.assertion_results[0].passed

    def test_run_fails_on_assertion(self):
        """Runner fails when assertions fail."""
        env = EnvironmentBuilder().mock_tool("search", response="results").build()

        # assert_tool_not_called will fail because search IS called
        check_no_search = functools.partial(assert_tool_not_called, tool_name="search")
        scenario = SentinelScenario(
            id="test-002",
            name="Should not call search",
            task="find stuff",
            assertions=[check_no_search],
        )

        runner = ScenarioRunner()
        result = runner.run(scenario, agent_fn=_simple_agent, env=env)

        assert not result.passed
        assert result.assertion_results[0].passed is False
        assert result.assertion_results[0].error_message is not None

    def test_run_with_agent_crash(self):
        """Runner handles agent exceptions gracefully."""
        def crashing_agent(task, env, trace):
            raise ValueError("Agent exploded!")

        scenario = SentinelScenario(
            id="test-crash",
            name="Crashing agent",
            task="do something",
            assertions=[],
        )

        runner = ScenarioRunner()
        result = runner.run(scenario, agent_fn=crashing_agent)

        assert not result.passed
        assert result.error is not None
        assert "Agent exploded" in result.error

    def test_run_with_env_config(self):
        """Runner builds environment from env_config dict."""
        check_search = functools.partial(assert_tool_called, tool_name="search")
        scenario = SentinelScenario(
            id="test-config",
            name="Config-based env",
            task="search",
            env_config={
                "tools": {
                    "search": {"response": {"found": True}},
                }
            },
            assertions=[check_search],
        )

        runner = ScenarioRunner()
        result = runner.run(scenario, agent_fn=_simple_agent)

        assert result.passed

    def test_run_batch(self):
        """run_batch executes multiple scenarios."""
        env = EnvironmentBuilder().mock_tool("search", response="ok").build()

        scenarios = [
            SentinelScenario(id=f"batch-{i}", name=f"Batch {i}", task="task")
            for i in range(3)
        ]

        runner = ScenarioRunner()
        results = runner.run_batch(scenarios, agent_fn=_simple_agent)

        assert len(results) == 3
        assert all(r.passed for r in results)

    def test_multiple_assertions(self):
        """Multiple assertions are all checked."""
        env = EnvironmentBuilder().mock_tool("search", response="ok").build()

        def check_search_and_no_email(trace):
            assert_tool_called(trace, tool_name="search")
            assert_tool_not_called(trace, tool_name="email")

        scenario = SentinelScenario(
            id="multi",
            name="Multi assertion",
            task="search",
            assertions=[check_search_and_no_email],
        )

        runner = ScenarioRunner()
        result = runner.run(scenario, agent_fn=_simple_agent, env=env)

        assert result.passed
        assert len(result.assertion_results) == 1  # The composite assertion

    def test_result_summary(self):
        """SentinelResult.summary formats nicely."""
        scenario = SentinelScenario(id="x", name="Test X")
        runner = ScenarioRunner()
        result = runner.run(scenario, agent_fn=lambda **kw: None)

        summary = result.summary
        assert "[PASS]" in summary
        assert "Test X" in summary

    def test_result_failed_assertions(self):
        """failed_assertions() returns only failures."""
        result = SentinelResult(
            scenario_id="x",
            scenario_name="X",
            passed=False,
            assertion_results=[
                SentinelAssertionResult(assertion_name="a1", passed=True),
                SentinelAssertionResult(assertion_name="a2", passed=False, error_message="bad"),
                SentinelAssertionResult(assertion_name="a3", passed=False, error_message="worse"),
            ],
        )

        failed = result.failed_assertions()
        assert len(failed) == 2
        assert all(not a.passed for a in failed)


# ──────────────────────────────────────────────────────
# SentinelScenario
# ──────────────────────────────────────────────────────


class TestSentinelScenario:
    def test_defaults(self):
        """Scenario has sensible defaults."""
        s = SentinelScenario(id="x", name="X")
        assert s.description == ""
        assert s.task == ""
        assert s.tags == []
        assert s.assertions == []
        assert s.timeout_seconds == 30

    def test_with_all_fields(self):
        """Scenario accepts all fields."""
        s = SentinelScenario(
            id="full",
            name="Full Scenario",
            description="Tests everything",
            task="Do the thing",
            tags=["edge-case", "memory"],
            timeout_seconds=60,
            assertions=[lambda t, e: None],
            env_config={"tools": {"x": {"response": "y"}}},
        )
        assert s.id == "full"
        assert len(s.assertions) == 1


# ──────────────────────────────────────────────────────
# AgentConfig
# ──────────────────────────────────────────────────────


class TestAgentConfig:
    def test_defaults(self):
        """AgentConfig has sensible defaults."""
        config = AgentConfig()
        assert config.agent_type is None
        assert config.model == "unknown"
        assert config.tools == []
        assert config.prompt == ""
        assert config.kwargs == {}
        assert config.factory is None

    def test_with_factory(self):
        """AgentConfig with factory callable."""
        def make_agent():
            return "agent"

        config = AgentConfig(factory=make_agent, model="gpt-4")
        assert config.factory is make_agent
        assert config.model == "gpt-4"
