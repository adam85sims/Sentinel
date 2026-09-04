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
    assert_state_changed,
    assert_state_consistent,
    assert_tool_allowlist,
    assert_tool_called_at_most,
    assert_tool_denylist,
)
from sentinel.models import (
    StateChange,
    Step,
    StepAction,
    ToolCall,
)

# ──────────────────────────────────────────────────────
# Local helpers
# ──────────────────────────────────────────────────────

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

    def test_read_only_boundary_respected(self, make_trace):
        """Agent calls only read tools — no write tools invoked."""
        trace = make_trace(
            tool_calls=[
                _tc("read_file", {"path": "/tmp/data.txt"}),
                _tc("search", {"q": "hello"}),
                _tc("list_dir", {"path": "/"}),
            ]
        )
        # These assertions should all pass — no forbidden tools called
        assert_tool_denylist(trace, ["write_file", "delete_file", "drop_table"])

    def test_approval_flow_for_dangerous_operation(self, make_trace):
        """Agent requests approval before performing a dangerous op."""
        trace = make_trace(
            tool_calls=[
                _tc("request_approval", {"action": "deploy"}, ts=100.0),
                _tc("deploy", {"env": "prod"}, ts=200.0),
            ]
        )
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_violation_detected_when_forbidden_tool_called(self, make_trace):
        """Guard catches forbidden tool calls."""
        trace = make_trace(
            tool_calls=[_tc("drop_table", {"table": "users"})]
        )
        with pytest.raises(AssertionError, match="denied tool"):
            assert_tool_denylist(trace, ["drop_table", "truncate_db"])

    def test_multi_tool_boundary_mixed(self, make_trace):
        """Agent calls allowed tools and avoids restricted ones."""
        trace = make_trace(
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

    def test_permission_respected_when_tool_skipped(self, make_trace):
        """Agent avoids calling an approval-requiring tool entirely."""
        trace = make_trace(
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

    def test_allowlist_passes_when_all_tools_permitted(self, make_trace):
        trace = make_trace(
            tool_calls=[
                _tc("read_file", {}),
                _tc("search", {}),
            ]
        )
        assert_tool_allowlist(trace, ["read_file", "search", "list_dir"])

    def test_allowlist_fails_on_single_violation(self, make_trace):
        trace = make_trace(
            tool_calls=[
                _tc("read_file", {}),
                _tc("rm_rf", {}),  # not in allowlist
            ]
        )
        with pytest.raises(AssertionError, match="outside the allowlist"):
            assert_tool_allowlist(trace, ["read_file", "search"])

    def test_allowlist_empty_trace_passes(self, make_trace):
        """An empty trace has no tool calls, so it trivially satisfies any allowlist."""
        trace = make_trace()
        assert_tool_allowlist(trace, ["read_file", "write_file"])

    def test_allowlist_fails_on_empty_list(self, make_trace):
        """Allowlist is empty but agent called a tool."""
        trace = make_trace(
            tool_calls=[_tc("search", {})]
        )
        with pytest.raises(AssertionError, match="outside the allowlist"):
            assert_tool_allowlist(trace, [])

    def test_allowlist_passes_on_empty_list_no_calls(self, make_trace):
        """Allowlist is empty AND no calls made — clean."""
        trace = make_trace()
        assert_tool_allowlist(trace, [])


class TestToolDenylist:
    """Tool denylist governance: certain tools must never be called."""

    def test_denylist_passes_when_no_denied_called(self, make_trace):
        trace = make_trace(
            tool_calls=[
                _tc("read_file", {}),
                _tc("search", {}),
            ]
        )
        assert_tool_denylist(trace, ["drop_table", "rm_rf"])

    def test_denylist_fails_on_denied_call(self, make_trace):
        trace = make_trace(
            tool_calls=[_tc("rm_rf", {"path": "/etc"})]
        )
        with pytest.raises(AssertionError, match="1 denied tool"):
            assert_tool_denylist(trace, ["rm_rf", "format_disk"])

    def test_denylist_fails_on_multiple_violations(self, make_trace):
        trace = make_trace(
            tool_calls=[
                _tc("rm_rf", {}),
                _tc("drop_table", {}),
                _tc("rm_rf", {}),  # duplicate
            ]
        )
        with pytest.raises(AssertionError, match="3 denied tool"):
            assert_tool_denylist(trace, ["rm_rf", "drop_table"])

    def test_denylist_empty_trace_passes(self, make_trace):
        trace = make_trace()
        assert_tool_denylist(trace, ["rm_rf", "sudo"])

    def test_denylist_passes_on_empty_denied_list(self, make_trace):
        """No tools are denied — everything is allowed."""
        trace = make_trace(
            tool_calls=[_tc("rm_rf", {})]
        )
        assert_tool_denylist(trace, [])

    def test_denylist_error_message_includes_arguments(self, make_trace):
        """Violation message should help debugging by including args."""
        trace = make_trace(
            tool_calls=[_tc("rm_rf", {"path": "/important"}, ts=1.0)]
        )
        with pytest.raises(AssertionError, match="rm_rf.*path"):
            assert_tool_denylist(trace, ["rm_rf"])


class TestSequentialGovernance:
    """Sequential governance: tool B requires tool A first."""

    def test_approval_before_action_passes(self, make_trace):
        trace = make_trace(
            tool_calls=[
                _tc("request_approval", {}, ts=100.0),
                _tc("deploy", {}, ts=200.0),
            ]
        )
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_approval_before_action_fails_no_approval(self, make_trace):
        trace = make_trace(
            tool_calls=[_tc("deploy", {}, ts=100.0)]
        )
        with pytest.raises(AssertionError, match="Governance bypassed"):
            assert_approval_before_action(trace, "request_approval", "deploy")

    def test_approval_before_action_fails_action_first(self, make_trace):
        """Action happened before approval — wrong order."""
        trace = make_trace(
            tool_calls=[
                _tc("deploy", {}, ts=100.0),
                _tc("request_approval", {}, ts=200.0),
            ]
        )
        with pytest.raises(AssertionError, match="before approval"):
            assert_approval_before_action(trace, "request_approval", "deploy")

    def test_approval_before_action_passes_when_action_never_called(self, make_trace):
        """Action tool was never called — nothing to check."""
        trace = make_trace(
            tool_calls=[_tc("request_approval", {})]
        )
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_approval_before_action_passes_empty_trace(self, make_trace):
        """No tool calls at all — no governance violation."""
        trace = make_trace()
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_multiple_actions_single_approval(self, make_trace):
        """One approval covers multiple subsequent actions."""
        trace = make_trace(
            tool_calls=[
                _tc("request_approval", {}, ts=100.0),
                _tc("deploy", {}, ts=200.0),
                _tc("deploy", {}, ts=300.0),
                _tc("deploy", {}, ts=400.0),
            ]
        )
        assert_approval_before_action(trace, "request_approval", "deploy")

    def test_interleaved_approval_and_action(self, make_trace):
        """Each action has its own preceding approval."""
        trace = make_trace(
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

    def test_rate_limit_passes_within_bounds(self, make_trace):
        trace = make_trace(
            tool_calls=[
                _tc("send_email", {}),
                _tc("send_email", {}),
                _tc("send_email", {}),
            ]
        )
        assert_tool_called_at_most(trace, "send_email", 5)

    def test_rate_limit_passes_at_exact_limit(self, make_trace):
        trace = make_trace(
            tool_calls=[
                _tc("send_email", {}),
                _tc("send_email", {}),
            ]
        )
        assert_tool_called_at_most(trace, "send_email", 2)

    def test_rate_limit_fails_when_exceeded(self, make_trace):
        trace = make_trace(
            tool_calls=[
                _tc("send_email", {}),
                _tc("send_email", {}),
                _tc("send_email", {}),
            ]
        )
        with pytest.raises(AssertionError, match="exceeds the governance limit"):
            assert_tool_called_at_most(trace, "send_email", 2)

    def test_rate_limit_passes_when_tool_never_called(self, make_trace):
        trace = make_trace()
        assert_tool_called_at_most(trace, "send_email", 3)

    def test_rate_limit_with_zero_allowed(self, make_trace):
        """Max count of 0 means the tool must never be called."""
        trace = make_trace(
            tool_calls=[_tc("send_email", {})]
        )
        with pytest.raises(AssertionError, match="exceeds the governance limit"):
            assert_tool_called_at_most(trace, "send_email", 0)

    def test_rate_limit_zero_tool_not_called(self, make_trace):
        """Max count of 0 and tool not called — passes."""
        trace = make_trace()
        assert_tool_called_at_most(trace, "send_email", 0)


# ──────────────────────────────────────────────────────
# 3. Edge Cases
# ──────────────────────────────────────────────────────

class TestGovernanceEdgeCases:
    """Edge cases in governance validation."""

    def test_empty_trace_passes_all_governance(self, make_trace):
        """An empty trace should pass all governance checks."""
        trace = make_trace()
        assert_tool_allowlist(trace, ["search", "read_file"])
        assert_tool_denylist(trace, ["rm_rf", "sudo"])
        assert_tool_called_at_most(trace, "rm_rf", 0)
        assert_approval_before_action(trace, "approve", "deploy")

    def test_trace_with_only_forbidden_tool_calls(self, make_trace):
        """Trace has exclusively forbidden tools — denylist should catch all."""
        trace = make_trace(
            tool_calls=[
                _tc("rm_rf", {"path": "/"}),
                _tc("sudo", {"cmd": "shutdown"}),
            ]
        )
        with pytest.raises(AssertionError, match="2 denied tool"):
            assert_tool_denylist(trace, ["rm_rf", "sudo"])

    def test_trace_with_mixed_allowed_and_forbidden_calls(self, make_trace):
        """Mix of clean and forbidden calls — denylist catches violations."""
        trace = make_trace(
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

    def test_governance_on_errored_tool_calls(self, make_trace):
        """Tool was attempted but errored — still counts for governance."""
        trace = make_trace(
            tool_calls=[
                _tc("rm_rf", {"path": "/"}, error="Permission denied"),
                _tc("search", {"q": "hello"}),
            ]
        )
        # The errored rm_rf still counts as a denied tool call
        with pytest.raises(AssertionError, match="denied tool"):
            assert_tool_denylist(trace, ["rm_rf"])

    def test_rate_limit_counts_errored_calls(self, make_trace):
        """Errored calls still count toward rate limits."""
        trace = make_trace(
            tool_calls=[
                _tc("send_email", {}, error="SMTP error"),
                _tc("send_email", {}),
                _tc("send_email", {}),
            ]
        )
        with pytest.raises(AssertionError, match="exceeds the governance limit"):
            assert_tool_called_at_most(trace, "send_email", 2)

    def test_denylist_multiple_different_violations(self, make_trace):
        """Multiple different denied tools called — error lists them all."""
        trace = make_trace(
            tool_calls=[
                _tc("rm_rf", {}),
                _tc("sudo", {}),
                _tc("format_disk", {}),
            ]
        )
        with pytest.raises(AssertionError, match="3 denied tool"):
            assert_tool_denylist(trace, ["rm_rf", "sudo", "format_disk"])

    def test_approval_needs_only_first_occurrence(self, make_trace):
        """Approval before action only checks first occurrence timestamps."""
        trace = make_trace(
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

    def test_approval_granted_state_tracking(self, make_trace):
        """Approval state change recorded when approval is granted."""
        trace = make_trace(
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

    def test_approval_denied_state_tracking(self, make_trace):
        """Agent records denial and does not take the action."""
        trace = make_trace(
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

    def test_cross_step_governance(self, make_trace):
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
        trace = make_trace(
            steps=[step1, step2, step3],
            state_changes=[
                _sc("approval_granted", None, True, ts=100.0),
                _sc("current_phase", "planning", "executing", ts=150.0),
            ],
        )
        assert_approval_before_action(trace, "request_approval", "deploy")
        assert_state_changed(trace, "approval_granted")
        assert_state_consistent(trace, "current_phase", expected="executing")

    def test_governance_with_rejected_then_resent(self, make_trace):
        """Agent is denied, resubmits, then approved."""
        trace = make_trace(
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

    def test_denylist_with_state_rollback(self, make_trace):
        """Agent attempts forbidden action, state rolls back."""
        trace = make_trace(
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
