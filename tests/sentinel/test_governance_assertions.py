"""Comprehensive governance assertion tests for Sentinel.

Tests governance boundary validation including:
- Permission boundary enforcement
- Tool allowlist/denylist governance
- Sequential governance (approval before action)
- Rate-limited governance
- State-based governance tracking
- Edge cases and integration scenarios
"""
import pytest
from sentinel.assertions import (
    assert_approval_before_action,
    assert_permission_respected,
    assert_permission_violated,
    assert_state_changed,
    assert_state_consistent,
    assert_tool_allowlist,
    assert_tool_called_at_most,
    assert_tool_denylist,
)
from sentinel.models import (
    AgentTrace,
    Error,
    ErrorSeverity,
    StateChange,
    Step,
    StepAction,
    ToolCall,
)


# ──────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────

def _make_trace(
    tool_calls=None,
    state_changes=None,
    errors=None,
    steps=None,
) -> AgentTrace:
    """Build an AgentTrace with given data and mark it finished."""
    trace = AgentTrace()
    if steps:
        for step in steps:
            trace.add_step(step)
    for tc in tool_calls or []:
        trace.add_tool_call(tc)
    for sc in state_changes or []:
        trace.add_state_change(sc)
    for err in errors or []:
        trace.add_error(err)
    trace.finish()
    return trace


def _tc(name: str, args: dict = None, ts: float = 0.0, error: str = None) -> ToolCall:
    """Shorthand to create a ToolCall with a given timestamp."""
    return ToolCall(
        tool_name=name,
        arguments=args or {},
        error=error,
        timestamp=ts,
    )


def _sc(key: str, old, new, ts: float = 0.0) -> StateChange:
    """Shorthand to create a StateChange."""
    return StateChange(key=key, old_value=old, new_value=new, timestamp=ts)


# ──────────────────────────────────────────────────────
# 1. Permission Boundary Validation
# ──────────────────────────────────────────────────────

class TestPermissionBoundary:
    """Agent respects read-only boundary and approval flows."""

    def test_read_only_boundary_respected(self):
        """Agent calls only read tools — no write tools invoked."""
        trace = _make_trace(
            tool_calls=[
                _tc("read_file", {"path": "/tmp/data.txt"}),
                _tc("search", {"q": "hello"}),
                _tc("list_dir", {"path": "/"}),
            ]
        )
        # These assertions should all pass — no forbidden tools called
        assert_tool_denylist(trace, ["write_file", "delete_file", "drop_table"])

    def test_approval_flow_for_dangerous_operation(self):
        """Agent requests approval before performing a dangerous op."""
        trace = _make_trace(
            tool_calls=[
                _tc("request_approval", {"action": "deploy"}, ts=100.0),
                _tc("deploy", {"env": "prod"}, ts=200.0),
            ]
        )
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_violation_detected_when_forbidden_tool_called(self):
        """Guard catches forbidden tool calls."""
        trace = _make_trace(
            tool_calls=[_tc("drop_table", {"table": "users"})]
        )
        with pytest.raises(AssertionError, match="denied tool"):
            assert_tool_denylist(trace, ["drop_table", "truncate_db"])

    def test_multi_tool_boundary_mixed(self):
        """Agent calls allowed tools and avoids restricted ones."""
        trace = _make_trace(
            tool_calls=[
                _tc("read_config", {}),
                _tc("run_tests", {}),
                _tc("read_log", {}),
            ]
        )
        # Allowlist: only read/config/test tools allowed
        assert_tool_allowlist(trace, ["read_config", "run_tests", "read_log"])
        # Denylist: destructive tools must not be called
        assert_tool_denylist(trace, ["rm_rf", "sudo", "format_disk"])

    def test_permission_respected_when_tool_skipped(self):
        """Agent avoids calling an approval-requiring tool entirely."""
        trace = _make_trace(
            tool_calls=[_tc("search", {"q": "docs"})]
        )
        # assert_permission_respected raises when requires_approval=True and
        # tool was never called — it's ambiguous whether the agent correctly
        # avoided an unauthorized action or failed to request approval.
        with pytest.raises(AssertionError, match="requires approval but was never called"):
            assert_permission_respected(trace, "send_email", requires_approval=True)


# ──────────────────────────────────────────────────────
# 2. Governance Policy Enforcement
# ──────────────────────────────────────────────────────

class TestToolAllowlist:
    """Tool allowlist governance: only certain tools permitted."""

    def test_allowlist_passes_when_all_tools_permitted(self):
        trace = _make_trace(
            tool_calls=[
                _tc("read_file", {}),
                _tc("search", {}),
            ]
        )
        assert_tool_allowlist(trace, ["read_file", "search", "list_dir"])

    def test_allowlist_fails_on_single_violation(self):
        trace = _make_trace(
            tool_calls=[
                _tc("read_file", {}),
                _tc("rm_rf", {}),  # not in allowlist
            ]
        )
        with pytest.raises(AssertionError, match="outside the allowlist"):
            assert_tool_allowlist(trace, ["read_file", "search"])

    def test_allowlist_empty_trace_passes(self):
        """An empty trace has no tool calls, so it trivially satisfies any allowlist."""
        trace = _make_trace()
        assert_tool_allowlist(trace, ["read_file", "write_file"])

    def test_allowlist_fails_on_empty_list(self):
        """Allowlist is empty but agent called a tool."""
        trace = _make_trace(
            tool_calls=[_tc("search", {})]
        )
        with pytest.raises(AssertionError, match="outside the allowlist"):
            assert_tool_allowlist(trace, [])

    def test_allowlist_passes_on_empty_list_no_calls(self):
        """Allowlist is empty AND no calls made — clean."""
        trace = _make_trace()
        assert_tool_allowlist(trace, [])


class TestToolDenylist:
    """Tool denylist governance: certain tools must never be called."""

    def test_denylist_passes_when_no_denied_called(self):
        trace = _make_trace(
            tool_calls=[
                _tc("read_file", {}),
                _tc("search", {}),
            ]
        )
        assert_tool_denylist(trace, ["drop_table", "rm_rf"])

    def test_denylist_fails_on_denied_call(self):
        trace = _make_trace(
            tool_calls=[_tc("rm_rf", {"path": "/etc"})]
        )
        with pytest.raises(AssertionError, match="1 denied tool"):
            assert_tool_denylist(trace, ["rm_rf", "format_disk"])

    def test_denylist_fails_on_multiple_violations(self):
        trace = _make_trace(
            tool_calls=[
                _tc("rm_rf", {}),
                _tc("drop_table", {}),
                _tc("rm_rf", {}),  # duplicate
            ]
        )
        with pytest.raises(AssertionError, match="3 denied tool"):
            assert_tool_denylist(trace, ["rm_rf", "drop_table"])

    def test_denylist_empty_trace_passes(self):
        trace = _make_trace()
        assert_tool_denylist(trace, ["rm_rf", "sudo"])

    def test_denylist_passes_on_empty_denied_list(self):
        """No tools are denied — everything is allowed."""
        trace = _make_trace(
            tool_calls=[_tc("rm_rf", {})]
        )
        assert_tool_denylist(trace, [])

    def test_denylist_error_message_includes_arguments(self):
        """Violation message should help debugging by including args."""
        trace = _make_trace(
            tool_calls=[_tc("rm_rf", {"path": "/important"}, ts=1.0)]
        )
        with pytest.raises(AssertionError, match="rm_rf.*path"):
            assert_tool_denylist(trace, ["rm_rf"])


class TestSequentialGovernance:
    """Sequential governance: tool B requires tool A first."""

    def test_approval_before_action_passes(self):
        trace = _make_trace(
            tool_calls=[
                _tc("request_approval", {}, ts=100.0),
                _tc("deploy", {}, ts=200.0),
            ]
        )
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_approval_before_action_fails_no_approval(self):
        trace = _make_trace(
            tool_calls=[_tc("deploy", {}, ts=100.0)]
        )
        with pytest.raises(AssertionError, match="Governance bypassed"):
            assert_approval_before_action(trace, "request_approval", "deploy")

    def test_approval_before_action_fails_action_first(self):
        """Action happened before approval — wrong order."""
        trace = _make_trace(
            tool_calls=[
                _tc("deploy", {}, ts=100.0),
                _tc("request_approval", {}, ts=200.0),
            ]
        )
        with pytest.raises(AssertionError, match="before approval"):
            assert_approval_before_action(trace, "request_approval", "deploy")

    def test_approval_before_action_passes_when_action_never_called(self):
        """Action tool was never called — nothing to check."""
        trace = _make_trace(
            tool_calls=[_tc("request_approval", {})]
        )
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_approval_before_action_passes_empty_trace(self):
        """No tool calls at all — no governance violation."""
        trace = _make_trace()
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_multiple_actions_single_approval(self):
        """One approval covers multiple subsequent actions."""
        trace = _make_trace(
            tool_calls=[
                _tc("request_approval", {}, ts=100.0),
                _tc("deploy", {}, ts=200.0),
                _tc("deploy", {}, ts=300.0),
                _tc("deploy", {}, ts=400.0),
            ]
        )
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_interleaved_approval_and_action(self):
        """Each action has its own preceding approval."""
        trace = _make_trace(
            tool_calls=[
                _tc("request_approval", {}, ts=100.0),
                _tc("deploy", {}, ts=200.0),
                _tc("request_approval", {}, ts=300.0),
                _tc("deploy", {}, ts=400.0),
            ]
        )
        assert_approval_before_action(trace, "request_approval", "deploy")


class TestRateLimitedGovernance:
    """Rate-limited governance: tool X can only be called N times."""

    def test_rate_limit_passes_within_bounds(self):
        trace = _make_trace(
            tool_calls=[
                _tc("send_email", {}),
                _tc("send_email", {}),
                _tc("send_email", {}),
            ]
        )
        assert_tool_called_at_most(trace, "send_email", 5)

    def test_rate_limit_passes_at_exact_limit(self):
        trace = _make_trace(
            tool_calls=[
                _tc("send_email", {}),
                _tc("send_email", {}),
            ]
        )
        assert_tool_called_at_most(trace, "send_email", 2)

    def test_rate_limit_fails_when_exceeded(self):
        trace = _make_trace(
            tool_calls=[
                _tc("send_email", {}),
                _tc("send_email", {}),
                _tc("send_email", {}),
            ]
        )
        with pytest.raises(AssertionError, match="exceeds the governance limit"):
            assert_tool_called_at_most(trace, "send_email", 2)

    def test_rate_limit_passes_when_tool_never_called(self):
        trace = _make_trace()
        assert_tool_called_at_most(trace, "send_email", 3)

    def test_rate_limit_with_zero_allowed(self):
        """Max count of 0 means the tool must never be called."""
        trace = _make_trace(
            tool_calls=[_tc("send_email", {})]
        )
        with pytest.raises(AssertionError, match="exceeds the governance limit"):
            assert_tool_called_at_most(trace, "send_email", 0)

    def test_rate_limit_zero_tool_not_called(self):
        """Max count of 0 and tool not called — passes."""
        trace = _make_trace()
        assert_tool_called_at_most(trace, "send_email", 0)


# ──────────────────────────────────────────────────────
# 3. Edge Cases
# ──────────────────────────────────────────────────────

class TestGovernanceEdgeCases:
    """Edge cases in governance validation."""

    def test_empty_trace_passes_all_governance(self):
        """An empty trace should pass all governance checks."""
        trace = _make_trace()
        assert_tool_allowlist(trace, ["search", "read_file"])
        assert_tool_denylist(trace, ["rm_rf", "sudo"])
        assert_tool_called_at_most(trace, "rm_rf", 0)
        assert_approval_before_action(trace, "approve", "deploy")

    def test_trace_with_only_forbidden_tool_calls(self):
        """Trace has exclusively forbidden tools — denylist should catch all."""
        trace = _make_trace(
            tool_calls=[
                _tc("rm_rf", {"path": "/"}),
                _tc("sudo", {"cmd": "shutdown"}),
            ]
        )
        with pytest.raises(AssertionError, match="2 denied tool"):
            assert_tool_denylist(trace, ["rm_rf", "sudo"])

    def test_trace_with_mixed_allowed_and_forbidden_calls(self):
        """Mix of clean and forbidden calls — denylist catches violations."""
        trace = _make_trace(
            tool_calls=[
                _tc("search", {"q": "hello"}),
                _tc("rm_rf", {"path": "/tmp"}),
                _tc("read_file", {"path": "/etc/passwd"}),
            ]
        )
        # Allowlist says only search and read_file are OK — rm_rf violates it
        with pytest.raises(AssertionError, match="outside the allowlist"):
            assert_tool_allowlist(trace, ["search", "read_file"])
        # Denylist also catches rm_rf
        with pytest.raises(AssertionError, match="denied tool"):
            assert_tool_denylist(trace, ["rm_rf"])

    def test_governance_on_errored_tool_calls(self):
        """Tool was attempted but errored — still counts for governance."""
        trace = _make_trace(
            tool_calls=[
                _tc("rm_rf", {"path": "/"}, error="Permission denied"),
                _tc("search", {"q": "hello"}),
            ]
        )
        # The errored rm_rf still counts as a denied tool call
        with pytest.raises(AssertionError, match="denied tool"):
            assert_tool_denylist(trace, ["rm_rf"])

    def test_rate_limit_counts_errored_calls(self):
        """Errored calls still count toward rate limits."""
        trace = _make_trace(
            tool_calls=[
                _tc("send_email", {}, error="SMTP error"),
                _tc("send_email", {}),
                _tc("send_email", {}),
            ]
        )
        with pytest.raises(AssertionError, match="exceeds the governance limit"):
            assert_tool_called_at_most(trace, "send_email", 2)

    def test_denylist_multiple_different_violations(self):
        """Multiple different denied tools called — error lists them all."""
        trace = _make_trace(
            tool_calls=[
                _tc("rm_rf", {}),
                _tc("sudo", {}),
                _tc("format_disk", {}),
            ]
        )
        with pytest.raises(AssertionError, match="3 denied tool"):
            assert_tool_denylist(trace, ["rm_rf", "sudo", "format_disk"])

    def test_approval_needs_only_first_occurrence(self):
        """Approval before action only checks first occurrence timestamps."""
        trace = _make_trace(
            tool_calls=[
                _tc("deploy", {}, ts=50.0),   # action before any approval
                _tc("request_approval", {}, ts=100.0),
                _tc("deploy", {}, ts=200.0),
            ]
        )
        # First deploy (ts=50) is before first approval (ts=100) → violation
        with pytest.raises(AssertionError, match="before approval"):
            assert_approval_before_action(trace, "request_approval", "deploy")


# ──────────────────────────────────────────────────────
# 4. Integration with State Assertions
# ──────────────────────────────────────────────────────

class TestGovernanceStateTracking:
    """Governance state tracking: approval granted/denied via state changes."""

    def test_approval_granted_state_tracking(self):
        """Approval state change recorded when approval is granted."""
        trace = _make_trace(
            tool_calls=[
                _tc("request_approval", {"action": "deploy"}),
                _tc("deploy", {"env": "prod"}),
            ],
            state_changes=[
                _sc("approval_status", None, "granted"),
                _sc("last_approved_action", None, "deploy"),
            ],
        )
        assert_approval_before_action(trace, "request_approval", "deploy")
        assert_state_changed(trace, "approval_status")
        assert_state_consistent(trace, "approval_status", expected="granted")

    def test_approval_denied_state_tracking(self):
        """Agent records denial and does not take the action."""
        trace = _make_trace(
            tool_calls=[
                _tc("request_approval", {"action": "drop_db"}),
            ],
            state_changes=[
                _sc("approval_status", None, "denied"),
            ],
        )
        # Approval was requested, action was NOT taken — that's compliant
        assert_approval_before_action(trace, "request_approval", "drop_db")
        assert_state_consistent(trace, "approval_status", expected="denied")

    def test_cross_step_governance(self):
        """Approval in step 1, action in step 3 — governance across steps."""
        step1 = Step(
            step_id=1,
            action=StepAction.TOOL_CALL,
            tool_calls=[_tc("request_approval", {"action": "deploy"}, ts=100.0)],
        )
        step2 = Step(
            step_id=2,
            action=StepAction.REASON,
            output="Approval granted, proceeding with deployment.",
        )
        step3 = Step(
            step_id=3,
            action=StepAction.TOOL_CALL,
            tool_calls=[_tc("deploy", {"env": "prod"}, ts=200.0)],
        )
        trace = _make_trace(
            steps=[step1, step2, step3],
            state_changes=[
                _sc("approval_granted", None, True, ts=100.0),
                _sc("current_phase", "planning", "executing", ts=150.0),
            ],
        )
        assert_approval_before_action(trace, "request_approval", "deploy")
        assert_state_changed(trace, "approval_granted")
        assert_state_consistent(trace, "current_phase", expected="executing")

    def test_governance_with_rejected_then_resent(self):
        """Agent is denied, resubmits, then approved."""
        trace = _make_trace(
            tool_calls=[
                _tc("request_approval", {"action": "deploy"}, ts=100.0),
                _tc("request_approval", {"action": "deploy"}, ts=200.0),
                _tc("deploy", {"env": "prod"}, ts=300.0),
            ],
            state_changes=[
                _sc("approval_status", None, "denied", ts=100.0),
                _sc("approval_status", "denied", "granted", ts=200.0),
            ],
        )
        assert_approval_before_action(trace, "request_approval", "deploy")
        assert_state_consistent(trace, "approval_status", expected="granted")

    def test_denylist_with_state_rollback(self):
        """Agent attempts forbidden action, state rolls back."""
        trace = _make_trace(
            tool_calls=[
                _tc("rm_rf", {"path": "/"}, error="Blocked by policy"),
            ],
            state_changes=[
                _sc("pending_action", None, "rm_rf"),
                _sc("pending_action", "rm_rf", None),  # rolled back
            ],
        )
        with pytest.raises(AssertionError, match="denied tool"):
            assert_tool_denylist(trace, ["rm_rf"])
        assert_state_consistent(trace, "pending_action", expected=None)
