"""Shared pytest fixtures and helpers for the Sentinel test suite.

All fixtures here are auto-discovered by pytest and available to every test
under ``tests/`` and ``tests/sentinel/`` without explicit import.

Conventions:
    * Factory fixtures (``make_*``) return a callable that builds the object
      on demand. They never mutate shared state.
    * Path/dir fixtures (``tmp_*``) rely on ``tmp_path`` so each test gets
      an isolated filesystem location that pytest cleans up automatically.
    * Nothing here may call ``monkeypatch.setattr`` outside of an explicit
      ``monkeypatch`` fixture argument — that keeps teardown safe.
"""

from __future__ import annotations

from typing import Any

import pytest

from sentinel.models import (
    AgentTrace,
    Error,
    ErrorSeverity,
    StateChange,
    Step,
    ToolCall,
)
from sentinel.runner import SentinelAssertionResult, SentinelResult

# ──────────────────────────────────────────────────────
# Trace builders
# ──────────────────────────────────────────────────────


@pytest.fixture
def make_trace():
    """Factory: build an AgentTrace with the given collections.

    Example::

        def test_x(make_trace):
            trace = make_trace(tool_calls=[ToolCall(...)])

    The returned trace is NOT finished — callers should call
    ``trace.finish()`` themselves if they need timing data, or use the
    ``assertions_phase6`` helper which handles timing.
    """

    def _make(
        tool_calls: list[ToolCall] | None = None,
        state_changes: list[StateChange] | None = None,
        errors: list[Error] | None = None,
        steps: list[Step] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTrace:
        trace = AgentTrace(metadata=metadata or {})
        for step in steps or []:
            trace.add_step(step)
        for tc in tool_calls or []:
            trace.add_tool_call(tc)
        for sc in state_changes or []:
            trace.add_state_change(sc)
        for err in errors or []:
            trace.add_error(err)
        return trace

    return _make


@pytest.fixture
def make_tool_call():
    """Factory: build a ToolCall with sensible defaults.

    Example::

        tc = make_tool_call("search", arguments={"q": "test"})
    """

    def _make(
        name: str = "search",
        arguments: dict[str, Any] | None = None,
        result: Any = None,
        error: str | None = None,
        duration_ms: float = 0.0,
        timestamp: float = 0.0,
    ) -> ToolCall:
        return ToolCall(
            tool_name=name,
            arguments=arguments or {},
            result=result,
            error=error,
            duration_ms=duration_ms,
            timestamp=timestamp,
        )

    return _make


@pytest.fixture
def make_state_change():
    """Factory: build a StateChange with sensible defaults.

    Example::

        sc = make_state_change("config", "v1", old_value=None)
    """

    def _make(
        key: str = "config",
        new_value: Any = "v1",
        old_value: Any = None,
        timestamp: float = 0.0,
        step_id: int | None = None,
    ) -> StateChange:
        return StateChange(
            key=key,
            old_value=old_value,
            new_value=new_value,
            timestamp=timestamp,
            step_id=step_id,
        )

    return _make


@pytest.fixture
def make_error():
    """Factory: build an Error with sensible defaults."""

    def _make(
        message: str = "boom",
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        recoverable: bool = True,
    ) -> Error:
        return Error(message=message, severity=severity, recoverable=recoverable)

    return _make


# ──────────────────────────────────────────────────────
# SentinelResult builder
# ──────────────────────────────────────────────────────


@pytest.fixture
def make_result():
    """Factory: build a SentinelResult with given scenario attributes.

    Example::

        result = make_result("s1", passed=True, tool_names=["search"])
    """

    def _make(
        scenario_id: str = "s1",
        passed: bool = True,
        assertion_names: list[str] | None = None,
        tool_names: list[str] | None = None,
        duration_ms: float = 100.0,
        metadata: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> SentinelResult:
        trace = AgentTrace(metadata=metadata or {})
        for name in tool_names or []:
            trace.add_tool_call(ToolCall(tool_name=name, arguments={}))
        trace.finish()

        if assertion_names:
            assertion_results = [
                SentinelAssertionResult(assertion_name=n, passed=passed)
                for n in assertion_names
            ]
        elif passed:
            assertion_results = [
                SentinelAssertionResult(assertion_name="default_assert", passed=True)
            ]
        else:
            assertion_results = [
                SentinelAssertionResult(
                    assertion_name="default_assert",
                    passed=False,
                    error_message=error_message or "boom",
                )
            ]

        return SentinelResult(
            scenario_id=scenario_id,
            scenario_name=f"Scenario {scenario_id}",
            passed=passed,
            trace=trace,
            assertion_results=assertion_results,
            duration_ms=duration_ms,
        )

    return _make


# ──────────────────────────────────────────────────────
# Filesystem / module isolation
# ──────────────────────────────────────────────────────


@pytest.fixture
def tmp_baseline_dir(tmp_path, monkeypatch):
    """Override ``sentinel.baseline.get_baseline_dir`` to a temp directory.

    Replaces the hand-rolled module monkey-patch that used to live in
    ``test_otel_baseline.py``. Uses ``monkeypatch.setattr`` so teardown
    is automatic and safe even if the test fails mid-way.

    Returns the fake baseline directory path so tests can inspect it.
    """
    import sentinel.baseline as bl_mod

    fake_dir = tmp_path / ".sentinel" / "baselines"
    monkeypatch.setattr(bl_mod, "get_baseline_dir", lambda pr=None: fake_dir)
    return fake_dir
