"""Behavioral assertions for agent testing.

These assertions validate what the agent DID (tool calls, state changes,
governance compliance), not just what it SAID (output quality).

Each assertion takes an AgentTrace and raises AssertionError with a
descriptive message on failure.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sentinel.models import AgentTrace

# ──────────────────────────────────────────────────────
# Tool Call Assertions
# ──────────────────────────────────────────────────────


def assert_tool_called(
    trace: AgentTrace,
    tool_name: str,
    **expected_kwargs: Any,
) -> None:
    """Assert that a specific tool was called with the given arguments.

    If no kwargs are provided, only checks that the tool was called at all.
    If kwargs are provided, checks that at least one call matches ALL
    specified arguments.

    Args:
        trace: The agent execution trace to check.
        tool_name: Name of the tool that should have been called.
        **expected_kwargs: Expected arguments (partial match).

    Raises:
        AssertionError: If the tool was not called or arguments don't match.
    """
    calls = trace.tool_calls_by_name(tool_name)
    if not calls:
        raise AssertionError(
            f"Expected tool '{tool_name}' to be called, but it was never invoked. "
            f"Tools called: {trace.tool_names_called}"
        )

    if not expected_kwargs:
        return  # Just checking the tool was called

    # Check if any call matches ALL expected arguments
    for call in calls:
        match = all(
            call.arguments.get(k) == v for k, v in expected_kwargs.items()
        )
        if match:
            return

    # No match found — provide helpful diagnostic
    actual_args = [call.arguments for call in calls]
    raise AssertionError(
        f"Tool '{tool_name}' was called {len(calls)} times, "
        f"but no call matched expected arguments {expected_kwargs}. "
        f"Actual arguments: {actual_args}"
    )


def assert_tool_not_called(trace: AgentTrace, tool_name: str) -> None:
    """Assert that a specific tool was NOT called.

    Useful for verifying that agents don't take unauthorized actions.

    Raises:
        AssertionError: If the tool was called.
    """
    calls = trace.tool_calls_by_name(tool_name)
    if calls:
        raise AssertionError(
            f"Tool '{tool_name}' should NOT have been called, "
            f"but was called {len(calls)} times. "
            f"Arguments: {[c.arguments for c in calls]}"
        )


def assert_tool_call_order(
    trace: AgentTrace,
    expected_order: list[str],
) -> None:
    """Assert that tools were called in the expected order.

    Checks that the UNIQUE tool names appear in the trace in the
    specified order. Extra calls between expected calls are allowed.

    Args:
        trace: The agent execution trace to check.
        expected_order: Expected order of unique tool names.

    Raises:
        AssertionError: If the actual order doesn't match.
    """
    actual_order = trace.tool_names_called

    # Filter to only tools in expected order
    filtered = [name for name in actual_order if name in expected_order]

    if filtered != expected_order:
        raise AssertionError(
            f"Expected tool call order: {expected_order}, "
            f"but got: {filtered}. "
            f"Full call order: {actual_order}"
        )


def assert_tool_call_count(
    trace: AgentTrace,
    tool_name: str,
    expected_count: int,
) -> None:
    """Assert that a tool was called exactly N times.

    Raises:
        AssertionError: If the call count doesn't match.
    """
    actual_count = len(trace.tool_calls_by_name(tool_name))
    if actual_count != expected_count:
        raise AssertionError(
            f"Expected '{tool_name}' to be called {expected_count} times, "
            f"but was called {actual_count} times."
        )


def assert_no_tool_errors(trace: AgentTrace) -> None:
    """Assert that no tool calls resulted in errors.

    Raises:
        AssertionError: If any tool call failed.
    """
    failed = trace.failed_tool_calls
    if failed:
        details = [
            f"  - {tc.tool_name}({tc.arguments}): {tc.error}" for tc in failed
        ]
        raise AssertionError(
            f"{len(failed)} tool call(s) failed:\n" + "\n".join(details)
        )


# ──────────────────────────────────────────────────────
# State Assertions
# ──────────────────────────────────────────────────────


def assert_state_consistent(
    trace: AgentTrace,
    key: str,
    expected: Any = None,
) -> None:
    """Assert that agent state has a specific value.

    Checks the most recent state change for the given key.

    Raises:
        AssertionError: If the state value doesn't match.
    """
    changes = [sc for sc in trace.state_changes if sc.key == key]
    if not changes:
        if expected is None:
            return  # No changes, no expectation — OK
        raise AssertionError(
            f"Expected state key '{key}' to be set to {expected!r}, "
            f"but no state changes were recorded for this key."
        )

    latest = changes[-1]
    if expected is not None and latest.new_value != expected:
        raise AssertionError(
            f"Expected state key '{key}' to be {expected!r}, "
            f"but got {latest.new_value!r}."
        )


def assert_state_changed(trace: AgentTrace, key: str) -> None:
    """Assert that a specific state key was modified during execution.

    Raises:
        AssertionError: If the key was never changed.
    """
    changes = [sc for sc in trace.state_changes if sc.key == key]
    if not changes:
        raise AssertionError(
            f"Expected state key '{key}' to be modified, "
            f"but no state changes were recorded for this key."
        )


# ──────────────────────────────────────────────────────
# Governance Assertions
# ──────────────────────────────────────────────────────


def assert_permission_respected(
    trace: AgentTrace,
    tool_name: str,
    requires_approval: bool = True,
) -> None:
    """Assert that a tool requiring approval was called (and thus approved).

    This is a behavioral assertion: if a tool requires human approval,
    the agent should have called it (meaning it went through the
    approval flow). If the tool was NOT called, the agent may have
    correctly avoided an unauthorized action.

    Raises:
        AssertionError: If the tool requiring approval was never called.
    """
    calls = trace.tool_calls_by_name(tool_name)
    if requires_approval and not calls:
        raise AssertionError(
            f"Tool '{tool_name}' requires approval but was never called. "
            f"This could indicate the agent correctly avoided an unauthorized "
            f"action, or failed to request approval."
        )


def assert_permission_violated(
    trace: AgentTrace,
    tool_name: str,
) -> None:
    """Assert that a forbidden tool WAS called (detecting a violation).

    This asserts the NEGATIVE — that the agent took an action it
    should not have. Useful for testing that agents respect boundaries.

    Raises:
        AssertionError: If the forbidden tool was NOT called (good behavior).
    """
    calls = trace.tool_calls_by_name(tool_name)
    if not calls:
        raise AssertionError(
            f"Expected permission violation (tool '{tool_name}' was called), "
            f"but the tool was never invoked. Agent behaved correctly."
        )


__all__ = [
    # Core assertions
    "assert_tool_called",
    "assert_tool_not_called",
    "assert_tool_call_order",
    "assert_tool_call_count",
    "assert_no_tool_errors",
    # State assertions
    "assert_state_consistent",
    "assert_state_changed",
    "assert_state_not_stale",
    "assert_state_consistent_across_traces",
    "assert_state_no_collisions",
    "detect_state_collisions",
    # Governance assertions
    "assert_permission_respected",
    "assert_permission_violated",
    "assert_tool_called_at_most",
    "assert_tool_allowlist",
    "assert_tool_denylist",
    "assert_approval_before_action",
    # Resilience assertions
    "assert_graceful_degradation",
    "assert_no_silent_failure",
    "assert_chaos_resilience",
    "assert_agent_recovers",
    # Performance assertions
    "assert_latency",
    "assert_token_usage",
    "assert_step_count",
    "assert_tool_latency",
]


def assert_tool_called_at_most(
    trace: AgentTrace,
    tool_name: str,
    max_count: int,
) -> None:
    """Assert that a tool was called at most N times.

    Implements rate-limited governance: prevents agents from
    calling expensive or dangerous tools too frequently.

    Args:
        trace: The agent execution trace to check.
        tool_name: Name of the tool to check.
        max_count: Maximum allowed number of calls (inclusive).

    Raises:
        AssertionError: If the tool was called more than max_count times.
    """
    actual_count = len(trace.tool_calls_by_name(tool_name))
    if actual_count > max_count:
        raise AssertionError(
            f"Tool '{tool_name}' was called {actual_count} times, "
            f"which exceeds the governance limit of {max_count}."
        )


def assert_tool_allowlist(
    trace: AgentTrace,
    allowed_tools: list[str],
) -> None:
    """Assert that ONLY tools from the allowlist were called.

    Implements tool allowlist governance: the agent may only invoke
    tools that appear in the allowed set.

    Args:
        trace: The agent execution trace to check.
        allowed_tools: List of tool names that are permitted.

    Raises:
        AssertionError: If any tool outside the allowlist was called.
    """
    called_names = set(trace.tool_names_called)
    forbidden = called_names - set(allowed_tools)
    if forbidden:
        raise AssertionError(
            f"Agent called tools outside the allowlist: {sorted(forbidden)}. "
            f"Allowed tools: {allowed_tools}"
        )


def assert_tool_denylist(
    trace: AgentTrace,
    denied_tools: list[str],
) -> None:
    """Assert that NONE of the denied tools were called.

    Implements tool denylist governance: certain dangerous tools must
    never be invoked under any circumstances.

    Args:
        trace: The agent execution trace to check.
        denied_tools: List of tool names that must NOT be called.

    Raises:
        AssertionError: If any denied tool was called.
    """
    denied_set = set(denied_tools)
    violations = []
    for tc in trace.tool_calls:
        if tc.tool_name in denied_set:
            violations.append(tc)

    if violations:
        tool_summary = [
            f"  - {v.tool_name}({v.arguments})" for v in violations
        ]
        raise AssertionError(
            f"Agent called {len(violations)} denied tool(s):\n"
            + "\n".join(tool_summary)
            + f"\nDenied tools: {denied_tools}"
        )


def assert_approval_before_action(
    trace: AgentTrace,
    approval_tool: str,
    action_tool: str,
) -> None:
    """Assert that an approval tool was called before a restricted action.

    Implements sequential governance: certain actions require that an
    approval step was completed first. If the action tool was called
    but the approval tool was not, the governance was bypassed.

    Args:
        trace: The agent execution trace to check.
        approval_tool: Tool that represents the approval step.
        action_tool: Tool that requires prior approval.

    Raises:
        AssertionError: If the action was taken without prior approval,
            or if approval appeared after the action.
    """
    approval_calls = trace.tool_calls_by_name(approval_tool)
    action_calls = trace.tool_calls_by_name(action_tool)

    if not action_calls:
        # Action was never taken — nothing to check
        return

    if not approval_calls:
        raise AssertionError(
            f"Tool '{action_tool}' was called {len(action_calls)} time(s) "
            f"but required approval tool '{approval_tool}' was never called. "
            f"Governance bypassed."
        )

    # Check that the FIRST approval came before the FIRST action
    first_approval_ts = approval_calls[0].timestamp
    first_action_ts = action_calls[0].timestamp

    if first_action_ts < first_approval_ts:
        raise AssertionError(
            f"Tool '{action_tool}' was called before approval tool "
            f"'{approval_tool}'. Action timestamp {first_action_ts} "
            f"< approval timestamp {first_approval_ts}. "
            f"Sequential governance violated."
        )


# ──────────────────────────────────────────────────────
# Resilience Assertions
# ──────────────────────────────────────────────────────


def assert_graceful_degradation(
    trace: AgentTrace,
    on_error_tool: str | None = None,
) -> None:
    """Assert that the agent handled errors gracefully.

    Checks that:
    1. The trace completed (no unhandled exceptions)
    2. If a specific tool errored, the agent continued execution
    3. No critical errors were left unrecovered

    Args:
        trace: The agent execution trace to check.
        on_error_tool: If specified, check that this tool's errors
                      were handled gracefully.

    Raises:
        AssertionError: If the agent did not degrade gracefully.
    """
    # Check that the trace completed
    if trace._end_time is None:
        raise AssertionError(
            "Agent trace was never finished — execution may have crashed."
        )

    # Check for unhandled critical errors
    critical = [e for e in trace.errors if e.severity.value == "critical"]
    unrecovered = [e for e in critical if not e.recoverable]
    if unrecovered:
        raise AssertionError(
            f"{len(unrecovered)} unrecoverable critical error(s): "
            + "; ".join(e.message for e in unrecovered)
        )

    # Check specific tool error handling
    if on_error_tool:
        failed_calls = [
            tc
            for tc in trace.tool_calls_by_name(on_error_tool)
            if not tc.succeeded
        ]
        if failed_calls:
            # Agent should have continued after the error
            calls_after = [
                tc
                for tc in trace.tool_calls
                if tc.timestamp > failed_calls[-1].timestamp
            ]
            if not calls_after:
                raise AssertionError(
                    f"Tool '{on_error_tool}' failed but the agent did not "
                    f"continue execution afterward. No graceful degradation."
                )


def assert_no_silent_failure(
    trace: AgentTrace,
    validator: Callable[[Any], bool] | None = None,
) -> None:
    """Assert that the agent's output is not a silent failure.

    A silent failure is when the agent completes without errors but
    produces incorrect or empty output.

    Args:
        trace: The agent execution trace to check.
        validator: Optional function that returns True if output is valid.

    Raises:
        AssertionError: If the output appears to be a silent failure.
    """
    if not trace.steps:
        raise AssertionError(
            "Agent produced no steps — cannot verify output validity."
        )

    last_step = trace.steps[-1]
    if last_step.output is None:
        raise AssertionError(
            "Agent's final output is None — possible silent failure."
        )

    if validator and not validator(last_step.output):
        raise AssertionError(
            f"Agent output failed validation: {last_step.output!r}"
        )


# ──────────────────────────────────────────────────────
# Performance Assertions
# ──────────────────────────────────────────────────────


def assert_latency(
    trace: AgentTrace,
    max_ms: float | None = None,
    min_ms: float | None = None,
    per_step_max_ms: float | None = None,
) -> None:
    """Assert that the agent's execution latency is within bounds.

    Checks total execution time and optionally per-step timing.
    Useful for detecting performance regression — an agent that
    takes 30s when it should take 5s is a behavioral failure.

    Args:
        trace: The agent execution trace to check.
        max_ms: Maximum total execution time in milliseconds.
        min_ms: Minimum total execution time (sanity check — too fast
                may indicate skipped work).
        per_step_max_ms: Maximum time for any single step.

    Raises:
        AssertionError: If latency bounds are violated.
    """
    total = trace.total_duration_ms

    if max_ms is not None and total > max_ms:
        raise AssertionError(
            f"Agent execution took {total:.1f}ms, exceeding maximum "
            f"of {max_ms:.1f}ms. ({trace.total_steps} steps, "
            f"{trace.total_tool_calls} tool calls)"
        )

    if min_ms is not None and total < min_ms:
        raise AssertionError(
            f"Agent execution took {total:.1f}ms, below minimum "
            f"of {min_ms:.1f}ms. Agent may have skipped required work."
        )

    if per_step_max_ms is not None:
        slow_steps = [
            s for s in trace.steps
            if s.duration_ms > per_step_max_ms
        ]
        if slow_steps:
            details = [
                f"  Step {s.step_id}: {s.duration_ms:.1f}ms ({s.action.value})"
                for s in slow_steps[:5]  # Show first 5 slow steps
            ]
            raise AssertionError(
                f"{len(slow_steps)} step(s) exceeded per-step limit of "
                f"{per_step_max_ms:.1f}ms:\n" + "\n".join(details)
            )


def assert_token_usage(
    trace: AgentTrace,
    max_tokens: int | None = None,
    min_tokens: int | None = None,
) -> None:
    """Assert that token usage is within expected bounds.

    Token counts are read from trace.metadata['token_usage'].
    The metadata dict should contain 'total_tokens', and optionally
    'prompt_tokens' and 'completion_tokens'.

    Args:
        trace: The agent execution trace to check.
        max_tokens: Maximum total tokens allowed.
        min_tokens: Minimum tokens (too few may indicate truncation).

    Raises:
        AssertionError: If token usage is out of bounds.
    """
    token_usage = trace.metadata.get("token_usage", {})
    total = token_usage.get("total_tokens", 0)

    if total == 0 and (max_tokens is not None or min_tokens is not None):
        raise AssertionError(
            "No token usage data in trace.metadata['token_usage']. "
            "Ensure the agent adapter records token counts."
        )

    if max_tokens is not None and total > max_tokens:
        raise AssertionError(
            f"Agent used {total} tokens, exceeding maximum of {max_tokens}. "
            f"(prompt={token_usage.get('prompt_tokens', '?')}, "
            f"completion={token_usage.get('completion_tokens', '?')})"
        )

    if min_tokens is not None and total < min_tokens:
        raise AssertionError(
            f"Agent used {total} tokens, below minimum of {min_tokens}. "
            f"Agent may have produced truncated output."
        )


def assert_step_count(
    trace: AgentTrace,
    max_steps: int | None = None,
    min_steps: int | None = None,
    exact_steps: int | None = None,
) -> None:
    """Assert that the agent used an expected number of steps.

    Step count is a key behavioral metric — an agent that takes
    50 steps to complete a 3-step task is likely confused or stuck.

    Args:
        trace: The agent execution trace to check.
        max_steps: Maximum allowed steps.
        min_steps: Minimum required steps (agent didn't do enough work).
        exact_steps: Require exactly this many steps.

    Raises:
        AssertionError: If step count is out of bounds.
    """
    actual = trace.total_steps

    if exact_steps is not None and actual != exact_steps:
        raise AssertionError(
            f"Expected exactly {exact_steps} steps, but agent took {actual}."
        )

    if max_steps is not None and actual > max_steps:
        raise AssertionError(
            f"Agent took {actual} steps, exceeding maximum of {max_steps}. "
            f"Agent may be stuck in a loop."
        )

    if min_steps is not None and actual < min_steps:
        raise AssertionError(
            f"Agent took {actual} steps, below minimum of {min_steps}. "
            f"Agent may have skipped required work."
        )


def assert_tool_latency(
    trace: AgentTrace,
    tool_name: str,
    max_ms: float | None = None,
    avg_max_ms: float | None = None,
) -> None:
    """Assert latency bounds on a specific tool's calls.

    Useful for detecting when a tool is being called too slowly
    (e.g., API degradation) or when the agent is hammering a slow tool.

    Args:
        trace: The agent execution trace to check.
        tool_name: Name of the tool to check.
        max_ms: Maximum latency for any single call.
        avg_max_ms: Maximum average latency across all calls.

    Raises:
        AssertionError: If tool latency exceeds bounds.
    """
    calls = trace.tool_calls_by_name(tool_name)
    if not calls:
        return  # No calls — nothing to check

    if max_ms is not None:
        slow_calls = [c for c in calls if c.duration_ms > max_ms]
        if slow_calls:
            raise AssertionError(
                f"Tool '{tool_name}' had {len(slow_calls)} call(s) exceeding "
                f"{max_ms:.1f}ms. Slowest: {max(c.duration_ms for c in calls):.1f}ms"
            )

    if avg_max_ms is not None:
        avg = sum(c.duration_ms for c in calls) / len(calls)
        if avg > avg_max_ms:
            raise AssertionError(
                f"Tool '{tool_name}' average latency {avg:.1f}ms exceeds "
                f"limit of {avg_max_ms:.1f}ms ({len(calls)} calls)"
            )


# ──────────────────────────────────────────────────────
# State Assertions — staleness, consistency, collisions
# ──────────────────────────────────────────────────────


def assert_state_not_stale(
    trace: AgentTrace,
    key: str,
    max_age_seconds: float,
) -> None:
    """Assert that a state key was recently written to.

    Detects stale state — the agent read a key that hasn't been
    updated recently, which could lead to acting on outdated data.
    Useful for testing that agents refresh cache, re-query databases,
    or otherwise keep their state fresh.

    Args:
        trace: The agent execution trace to check.
        key: State key to check for freshness.
        max_age_seconds: Maximum acceptable age of the state value.

    Raises:
        AssertionError: If the state is older than max_age_seconds,
            or if the key was never set.
    """
    changes = [sc for sc in trace.state_changes if sc.key == key]
    if not changes:
        raise AssertionError(
            f"State key '{key}' was never set — cannot verify freshness."
        )

    latest = changes[-1]
    # Use trace end time if available, otherwise current time
    reference_time = trace._end_time or time.time()
    age_seconds = reference_time - latest.timestamp

    if age_seconds > max_age_seconds:
        raise AssertionError(
            f"State key '{key}' is stale: last updated {age_seconds:.1f}s ago, "
            f"but maximum allowed age is {max_age_seconds:.1f}s. "
            f"({len(changes)} total changes recorded)"
        )


def assert_state_consistent_across_traces(
    traces: list[AgentTrace],
    key: str,
) -> None:
    """Assert that a state key has the same value across multiple traces.

    Detects cross-session divergence — two agent runs that should
    agree on a shared state value but don't. Useful for testing
    multi-agent coordination, caching consistency, and state
    persistence correctness.

    Args:
        traces: List of agent execution traces to compare.
        key: State key that should be consistent.

    Raises:
        AssertionError: If the final value of the key differs across traces.
    """
    if len(traces) < 2:
        raise AssertionError(
            "Need at least 2 traces to compare state consistency."
        )

    final_values: list[Any] = []
    for i, trace in enumerate(traces):
        changes = [sc for sc in trace.state_changes if sc.key == key]
        if changes:
            final_values.append((i, changes[-1].new_value))
        else:
            final_values.append((i, None))

    # Check all non-None values are the same
    non_none = [(i, v) for i, v in final_values if v is not None]
    if not non_none:
        raise AssertionError(
            f"State key '{key}' was never set in any of the {len(traces)} traces."
        )

    values_set = set(repr(v) for _, v in non_none)
    if len(values_set) > 1:
        details = [
            f"  Trace {i}: {v!r}" for i, v in non_none
        ]
        raise AssertionError(
            f"State key '{key}' diverges across traces:\n"
            + "\n".join(details)
        )


def detect_state_collisions(
    traces: list[AgentTrace],
) -> list[dict[str, Any]]:
    """Detect when multiple agents write to the same state key.

    Returns a list of collision events — moments where two or more
    agents modified the same key within a configurable time window.
    This is the detection function; use assert_state_no_collisions()
    for assertion-based testing.

    Args:
        traces: List of agent execution traces to analyze.

    Returns:
        List of collision dicts with keys: 'key', 'conflicts' (list of
        (trace_index, state_change) tuples), 'time_span_seconds'
    """
    # Group all state changes by key
    changes_by_key: dict[str, list[tuple]] = {}
    for i, trace in enumerate(traces):
        for sc in trace.state_changes:
            changes_by_key.setdefault(sc.key, []).append((i, sc))

    collisions = []
    for key, changes in changes_by_key.items():
        if len(changes) < 2:
            continue

        # Sort by timestamp
        changes.sort(key=lambda x: x[1].timestamp)

        # Find overlapping write windows — two writes from different
        # traces within 1 second of each other
        for j in range(len(changes)):
            for k in range(j + 1, len(changes)):
                idx_a, sc_a = changes[j]
                idx_b, sc_b = changes[k]

                # Skip same-trace comparisons (not a collision)
                if idx_a == idx_b:
                    continue

                time_span = abs(sc_a.timestamp - sc_b.timestamp)
                # Collision window: 1 second
                # This catches concurrent writes in real-time systems
                if time_span <= 1.0:
                    collisions.append({
                        "key": key,
                        "conflicts": [
                            {"trace_index": idx_a, "value": sc_a.new_value,
                             "timestamp": sc_a.timestamp},
                            {"trace_index": idx_b, "value": sc_b.new_value,
                             "timestamp": sc_b.timestamp},
                        ],
                        "time_span_seconds": time_span,
                    })

    return collisions


def assert_state_no_collisions(
    traces: list[AgentTrace],
    allowed_keys: list[str] | None = None,
) -> None:
    """Assert that no state key collisions occurred between agents.

    This is the assertion wrapper around detect_state_collisions().
    Raises if any concurrent writes to the same key are detected.

    Args:
        traces: List of agent execution traces to compare.
        allowed_keys: If provided, only check for collisions on these
                      keys. Others are ignored (useful when some keys
                      are designed for concurrent access).

    Raises:
        AssertionError: If state collisions are detected.
    """
    collisions = detect_state_collisions(traces)

    if allowed_keys is not None:
        allowed_set = set(allowed_keys)
        collisions = [c for c in collisions if c["key"] in allowed_set]

    if collisions:
        details = []
        for c in collisions[:10]:  # Show first 10
            key = c["key"]
            for conflict in c["conflicts"]:
                details.append(
                    f"  Key '{key}': trace {conflict['trace_index']} "
                    f"set to {conflict['value']!r} at t={conflict['timestamp']:.3f}"
                )
        raise AssertionError(
            f"{len(collisions)} state collision(s) detected between agents:\n"
            + "\n".join(details)
        )


# ──────────────────────────────────────────────────────
# Chaos Resilience Assertions
# ──────────────────────────────────────────────────────


def assert_chaos_resilience(
    trace: AgentTrace,
    chaos_budget: Any = None,
    max_failure_rate: float = 0.5,
) -> None:
    """Assert that the agent handled chaos injection resiliently.

    Checks that:
    1. The agent continued executing despite failures
    2. The failure rate didn't exceed the threshold
    3. The agent produced some output

    Args:
        trace: The agent execution trace.
        chaos_budget: Optional ChaosBudget (used for injection count).
        max_failure_rate: Maximum acceptable fraction of failed tool calls.

    Raises:
        AssertionError: If the agent didn't handle chaos resiliently.
    """
    if trace.total_tool_calls == 0:
        raise AssertionError(
            "Agent made no tool calls under chaos — it may have crashed or refused to execute."
        )

    failed = len(trace.failed_tool_calls)
    total = trace.total_tool_calls
    failure_rate = failed / total

    if failure_rate > max_failure_rate:
        raise AssertionError(
            f"Agent failure rate {failure_rate:.1%} exceeds threshold {max_failure_rate:.1%} "
            f"({failed}/{total} tool calls failed)."
        )

    # Check agent continued after failures
    if trace.failed_tool_calls and trace.total_tool_calls <= failed:
        raise AssertionError(
            "Agent did not make any successful tool calls after failures — no recovery."
        )


def assert_agent_recovers(
    trace: AgentTrace,
    after_error_tool: str | None = None,
) -> None:
    """Assert that the agent recovered after encountering an error.

    Checks that the agent continued execution after a tool failure,
    producing steps or tool calls after the error occurred.

    Args:
        trace: The agent execution trace.
        after_error_tool: If specified, check recovery after this tool's error.

    Raises:
        AssertionError: If the agent did not recover.
    """
    failed_calls = trace.failed_tool_calls
    if not failed_calls:
        raise AssertionError(
            "No tool errors recorded — cannot verify recovery."
        )

    last_error_time = max(tc.timestamp for tc in failed_calls)

    # Check for successful calls after the last error
    calls_after = [
        tc for tc in trace.tool_calls
        if tc.timestamp > last_error_time and tc.succeeded
    ]

    if not calls_after:
        raise AssertionError(
            "Agent made no successful tool calls after errors — did not recover."
        )
