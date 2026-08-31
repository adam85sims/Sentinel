"""Tests for Phase 6: Performance & State Assertions."""

import time

import pytest

from sentinel.assertions import (
    assert_latency,
    assert_state_consistent_across_traces,
    assert_state_no_collisions,
    assert_state_not_stale,
    assert_step_count,
    assert_token_usage,
    assert_tool_latency,
    detect_state_collisions,
)
from sentinel.models import AgentTrace, StateChange, Step, StepAction, ToolCall

# ──────────────────────────────────────────────────────
# Helpers — trace builders
# ──────────────────────────────────────────────────────


def _make_trace(
    steps=3,
    duration_ms=100.0,
    step_duration_ms=None,
    tool_calls=None,
    state_changes=None,
    metadata=None,
) -> AgentTrace:
    """Build a minimal AgentTrace for testing assertions."""
    trace = AgentTrace(metadata=metadata or {})
    trace._start_time = time.time() - (duration_ms / 1000.0)
    trace._end_time = time.time()

    step_dur = step_duration_ms or (duration_ms / max(steps, 1))
    for i in range(steps):
        step = Step(
            step_id=i,
            action=StepAction.TOOL_CALL if i < steps - 1 else StepAction.RESPOND,
            duration_ms=step_dur,
        )
        trace.add_step(step)

    for tc in (tool_calls or []):
        trace.add_tool_call(tc)

    for sc in (state_changes or []):
        trace.add_state_change(sc)

    return trace


def _make_tool_call(name="search", duration_ms=10.0, error=None) -> ToolCall:
    tc = ToolCall(
        tool_name=name,
        arguments={"q": "test"},
        duration_ms=duration_ms,
        error=error,
    )
    return tc


def _make_state_change(key="config", value="v1", timestamp=None) -> StateChange:
    return StateChange(
        key=key,
        old_value=None,
        new_value=value,
        timestamp=timestamp or time.time(),
    )


# ──────────────────────────────────────────────────────
# Performance Assertions Tests
# ──────────────────────────────────────────────────────


class TestAssertLatency:
    def test_passes_within_bounds(self):
        """Should pass when total latency is within max_ms."""
        trace = _make_trace(steps=3, duration_ms=50.0)
        assert_latency(trace, max_ms=100.0)

    def test_fails_exceeds_max(self):
        """Should fail when total latency exceeds max_ms."""
        trace = _make_trace(steps=3, duration_ms=200.0)
        with pytest.raises(AssertionError, match="exceeding maximum"):
            assert_latency(trace, max_ms=100.0)

    def test_fails_below_min(self):
        """Should fail when total latency is below min_ms."""
        trace = _make_trace(steps=3, duration_ms=10.0)
        with pytest.raises(AssertionError, match="below minimum"):
            assert_latency(trace, min_ms=50.0)

    def test_per_step_max(self):
        """Should fail when any step exceeds per_step_max_ms."""
        trace = _make_trace(steps=3, duration_ms=100.0)
        # Inject a slow step
        trace.steps[1].duration_ms = 500.0
        with pytest.raises(AssertionError, match="exceeded per-step limit"):
            assert_latency(trace, per_step_max_ms=100.0)

    def test_per_step_max_passes(self):
        """Should pass when all steps are within per_step_max_ms."""
        trace = _make_trace(steps=3, duration_ms=100.0, step_duration_ms=30.0)
        assert_latency(trace, per_step_max_ms=100.0)


class TestAssertTokenUsage:
    def test_passes_within_bounds(self):
        """Should pass when token usage is within max_tokens."""
        trace = _make_trace(metadata={"token_usage": {"total_tokens": 500}})
        assert_token_usage(trace, max_tokens=1000)

    def test_fails_exceeds_max(self):
        """Should fail when token usage exceeds max_tokens."""
        trace = _make_trace(metadata={"token_usage": {"total_tokens": 2000}})
        with pytest.raises(AssertionError, match="exceeding maximum"):
            assert_token_usage(trace, max_tokens=1000)

    def test_fails_below_min(self):
        """Should fail when token usage is below min_tokens."""
        trace = _make_trace(metadata={"token_usage": {"total_tokens": 100}})
        with pytest.raises(AssertionError, match="below minimum"):
            assert_token_usage(trace, min_tokens=500)

    def test_no_token_data_fails(self):
        """Should fail when no token usage data exists."""
        trace = _make_trace()
        with pytest.raises(AssertionError, match="No token usage data"):
            assert_token_usage(trace, max_tokens=1000)

    def test_no_bounds_no_error(self):
        """Should pass when no bounds are specified (just checking data exists)."""
        trace = _make_trace(metadata={"token_usage": {"total_tokens": 100}})
        assert_token_usage(trace)  # No bounds — should not raise

    def test_includes_prompt_completion_breakdown(self):
        """Error message should include prompt/completion breakdown."""
        trace = _make_trace(metadata={
            "token_usage": {
                "total_tokens": 5000,
                "prompt_tokens": 4000,
                "completion_tokens": 1000,
            }
        })
        with pytest.raises(AssertionError, match="prompt=4000"):
            assert_token_usage(trace, max_tokens=1000)


class TestAssertStepCount:
    def test_exact_match(self):
        """Should pass when step count matches exactly."""
        trace = _make_trace(steps=5)
        assert_step_count(trace, exact_steps=5)

    def test_exact_mismatch(self):
        """Should fail when step count doesn't match exactly."""
        trace = _make_trace(steps=5)
        with pytest.raises(AssertionError, match="Expected exactly 3"):
            assert_step_count(trace, exact_steps=3)

    def test_max_steps(self):
        """Should fail when step count exceeds max_steps."""
        trace = _make_trace(steps=10)
        with pytest.raises(AssertionError, match="exceeding maximum"):
            assert_step_count(trace, max_steps=5)

    def test_min_steps(self):
        """Should fail when step count is below min_steps."""
        trace = _make_trace(steps=2)
        with pytest.raises(AssertionError, match="below minimum"):
            assert_step_count(trace, min_steps=5)

    def test_passes_range(self):
        """Should pass when step count is within min/max range."""
        trace = _make_trace(steps=5)
        assert_step_count(trace, min_steps=3, max_steps=10)


class TestAssertToolLatency:
    def test_passes_within_bounds(self):
        """Should pass when tool latency is within max_ms."""
        tc = _make_tool_call("search", duration_ms=50.0)
        trace = _make_trace(tool_calls=[tc])
        assert_tool_latency(trace, "search", max_ms=100.0)

    def test_fails_exceeds_max(self):
        """Should fail when tool call exceeds max_ms."""
        tc = _make_tool_call("search", duration_ms=200.0)
        trace = _make_trace(tool_calls=[tc])
        with pytest.raises(AssertionError, match="exceeding"):
            assert_tool_latency(trace, "search", max_ms=100.0)

    def test_avg_max(self):
        """Should fail when average latency exceeds avg_max_ms."""
        calls = [
            _make_tool_call("search", duration_ms=100.0),
            _make_tool_call("search", duration_ms=200.0),
            _make_tool_call("search", duration_ms=300.0),
        ]
        trace = _make_trace(tool_calls=calls)
        with pytest.raises(AssertionError, match="average latency"):
            assert_tool_latency(trace, "search", avg_max_ms=150.0)

    def test_no_calls_passes(self):
        """Should pass silently when tool was never called."""
        trace = _make_trace()
        assert_tool_latency(trace, "nonexistent_tool", max_ms=100.0)


# ──────────────────────────────────────────────────────
# State Assertions Tests
# ──────────────────────────────────────────────────────


class TestAssertStateNotStale:
    def test_fresh_state_passes(self):
        """Should pass when state was recently updated."""
        sc = _make_state_change("config", "v1")
        trace = _make_trace(state_changes=[sc])
        trace._end_time = time.time()
        assert_state_not_stale(trace, "config", max_age_seconds=60.0)

    def test_stale_state_fails(self):
        """Should fail when state is older than max_age_seconds."""
        sc = _make_state_change("config", "v1", timestamp=time.time() - 120.0)
        trace = _make_trace(state_changes=[sc])
        trace._end_time = time.time()
        with pytest.raises(AssertionError, match="stale"):
            assert_state_not_stale(trace, "config", max_age_seconds=60.0)

    def test_unknown_key_fails(self):
        """Should fail when key was never set."""
        trace = _make_trace()
        with pytest.raises(AssertionError, match="never set"):
            assert_state_not_stale(trace, "nonexistent", max_age_seconds=60.0)

    def test_uses_latest_change(self):
        """Should check the most recent change, not the first."""
        sc1 = _make_state_change("config", "v1", timestamp=time.time() - 200.0)
        sc2 = _make_state_change("config", "v2", timestamp=time.time() - 5.0)
        trace = _make_trace(state_changes=[sc1, sc2])
        trace._end_time = time.time()
        # Should pass because the latest change is fresh
        assert_state_not_stale(trace, "config", max_age_seconds=60.0)


class TestAssertStateConsistentAcrossTraces:
    def test_consistent_passes(self):
        """Should pass when all traces have the same final value."""
        trace1 = _make_trace(state_changes=[
            _make_state_change("config", "v1"),
        ])
        trace2 = _make_trace(state_changes=[
            _make_state_change("config", "v1"),
        ])
        assert_state_consistent_across_traces([trace1, trace2], "config")

    def test_divergent_fails(self):
        """Should fail when traces have different final values."""
        trace1 = _make_trace(state_changes=[
            _make_state_change("config", "v1"),
        ])
        trace2 = _make_trace(state_changes=[
            _make_state_change("config", "v2"),
        ])
        with pytest.raises(AssertionError, match="diverges"):
            assert_state_consistent_across_traces([trace1, trace2], "config")

    def test_never_set_fails(self):
        """Should fail when key was never set in any trace."""
        trace1 = _make_trace()
        trace2 = _make_trace()
        with pytest.raises(AssertionError, match="never set"):
            assert_state_consistent_across_traces([trace1, trace2], "config")

    def test_single_trace_fails(self):
        """Should fail with fewer than 2 traces."""
        trace1 = _make_trace()
        with pytest.raises(AssertionError, match="at least 2"):
            assert_state_consistent_across_traces([trace1], "config")


class TestDetectStateCollisions:
    def test_no_collisions(self):
        """Should detect no collisions when agents write at different times."""
        trace1 = _make_trace(state_changes=[
            _make_state_change("counter", "1", timestamp=1000.0),
        ])
        trace2 = _make_trace(state_changes=[
            _make_state_change("counter", "2", timestamp=2000.0),
        ])
        collisions = detect_state_collisions([trace1, trace2])
        assert len(collisions) == 0

    def test_collision_detected(self):
        """Should detect collision when agents write to same key simultaneously."""
        now = time.time()
        trace1 = _make_trace(state_changes=[
            _make_state_change("counter", "1", timestamp=now),
        ])
        trace2 = _make_trace(state_changes=[
            _make_state_change("counter", "2", timestamp=now + 0.1),
        ])
        collisions = detect_state_collisions([trace1, trace2])
        assert len(collisions) == 1
        assert collisions[0]["key"] == "counter"
        assert collisions[0]["time_span_seconds"] <= 1.0

    def test_different_keys_no_collision(self):
        """Different keys should not collide."""
        now = time.time()
        trace1 = _make_trace(state_changes=[
            _make_state_change("key_a", "v1", timestamp=now),
        ])
        trace2 = _make_trace(state_changes=[
            _make_state_change("key_b", "v2", timestamp=now + 0.1),
        ])
        collisions = detect_state_collisions([trace1, trace2])
        assert len(collisions) == 0

    def test_same_trace_not_collision(self):
        """Same trace writing same key is not a collision."""
        now = time.time()
        trace = _make_trace(state_changes=[
            _make_state_change("counter", "1", timestamp=now),
            _make_state_change("counter", "2", timestamp=now + 0.1),
        ])
        collisions = detect_state_collisions([trace])
        assert len(collisions) == 0


class TestAssertStateNoCollisions:
    def test_no_collisions_passes(self):
        """Should pass when no collisions detected."""
        trace1 = _make_trace(state_changes=[
            _make_state_change("counter", "1", timestamp=1000.0),
        ])
        trace2 = _make_trace(state_changes=[
            _make_state_change("counter", "2", timestamp=2000.0),
        ])
        assert_state_no_collisions([trace1, trace2])

    def test_collision_fails(self):
        """Should fail when collisions are detected."""
        now = time.time()
        trace1 = _make_trace(state_changes=[
            _make_state_change("counter", "1", timestamp=now),
        ])
        trace2 = _make_trace(state_changes=[
            _make_state_change("counter", "2", timestamp=now + 0.1),
        ])
        with pytest.raises(AssertionError, match="collision"):
            assert_state_no_collisions([trace1, trace2])

    def test_allowed_keys_filters(self):
        """Should only check collisions on allowed keys."""
        now = time.time()
        trace1 = _make_trace(state_changes=[
            _make_state_change("counter", "1", timestamp=now),
        ])
        trace2 = _make_trace(state_changes=[
            _make_state_change("counter", "2", timestamp=now + 0.1),
        ])
        # "counter" is not in allowed_keys — should pass
        assert_state_no_collisions([trace1, trace2], allowed_keys=["other_key"])
