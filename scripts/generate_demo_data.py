#!/usr/bin/env python3
"""
generate_demo_data.py — Pre-compute demo data for the Sentinel WebUI.

Generates 24 mock agent runs (8 scenarios × 3 outcomes) and 3 baselines.
All files are saved under .sentinel/ in the same format the persistence
and baseline modules produce.

Usage:
    python scripts/generate_demo_data.py

Run from the sentinel project root. Creates:
    .sentinel/runs/<run_id>.json          — 24 run files
    .sentinel/baselines/<label>/          — 3 baseline directories
        metadata.json
        results.json
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable


# ──────────────────────────────────────────────────────
# Sentinel core types (mirrors sentinel.models exactly)
# ──────────────────────────────────────────────────────

class StepAction(StrEnum):
    PLAN = "plan"
    TOOL_CALL = "tool_call"
    REASON = "reason"
    RESPOND = "respond"
    ERROR = "error"


class ErrorSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ToolCall:
    tool_name: str
    arguments: dict[str, Any]
    result: Any = None
    duration_ms: float = 0.0
    error: str | None = None
    step_id: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class StateChange:
    key: str
    old_value: Any = None
    new_value: Any = None
    step_id: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class Error:
    message: str
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    step_id: int = 0
    recoverable: bool = True
    timestamp: float = field(default_factory=time.time)


@dataclass
class Step:
    step_id: int
    action: StepAction
    input: Any = None
    output: Any = None
    duration_ms: float = 0.0
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: Error | None = None


@dataclass
class AgentTrace:
    steps: list[Step] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    state_changes: list[StateChange] = field(default_factory=list)
    errors: list[Error] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    _start_time: float = field(default_factory=time.time, repr=False)
    _end_time: float | None = field(default=None, repr=False)

    def finish(self) -> None:
        self._end_time = time.time()

    @property
    def total_duration_ms(self) -> float:
        if self._end_time is None:
            return (time.time() - self._start_time) * 1000
        return (self._end_time - self._start_time) * 1000

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def total_tool_calls(self) -> int:
        return len(self.tool_calls)

    @property
    def failed_tool_calls(self) -> list[ToolCall]:
        return [tc for tc in self.tool_calls if not tc.succeeded]

    @property
    def tool_names_called(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for tc in self.tool_calls:
            if tc.tool_name not in seen:
                seen.add(tc.tool_name)
                result.append(tc.tool_name)
        return result

    def add_step(self, step: Step) -> None:
        self.steps.append(step)
        for tc in step.tool_calls:
            tc.step_id = step.step_id
            self.tool_calls.append(tc)

    def add_tool_call(self, call: ToolCall) -> None:
        self.tool_calls.append(call)

    def add_state_change(self, change: StateChange) -> None:
        self.state_changes.append(change)

    def add_error(self, error: Error) -> None:
        self.errors.append(error)


# ──────────────────────────────────────────────────────
# Runner types (mirrors sentinel.runner exactly)
# ──────────────────────────────────────────────────────

@dataclass
class SentinelScenario:
    id: str
    name: str
    description: str = ""
    agent_config: Any = None
    environment: Any = None
    env_config: dict[str, Any] = field(default_factory=dict)
    chaos_config: dict[str, Any] = field(default_factory=dict)
    task: str = ""
    assertions: list[Callable[..., None]] = field(default_factory=list)
    timeout_seconds: int = 30
    tags: list[str] = field(default_factory=list)


@dataclass
class SentinelAssertionResult:
    assertion_name: str
    passed: bool
    error_message: str | None = None
    duration_ms: float = 0.0


@dataclass
class SentinelResult:
    scenario_id: str
    scenario_name: str
    passed: bool
    trace: AgentTrace = field(default_factory=AgentTrace)
    assertion_results: list[SentinelAssertionResult] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class RunState:
    """Full serialised state of a single run — what persistence.save_run produces."""
    run_id: str
    scenario_id: str
    scenario_name: str
    status: str  # "pass" | "fail"
    started_at: datetime
    completed_at: datetime
    result: SentinelResult | None = None
    event_queue: Any = None  # skipped in serialization


# ──────────────────────────────────────────────────────
# Minimal mock environment
# ──────────────────────────────────────────────────────

class MockTool:
    def __init__(self, name: str, response: Any = None, side_effect: str | None = None,
                 error_message: str | None = None):
        self.name = name
        self.response = response
        self.side_effect = side_effect
        self.error_message = error_message

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        if self.side_effect == "timeout":
            return {"error": self.error_message or "Timeout", "succeeded": False}
        if self.side_effect == "error":
            return {"error": self.error_message or "Tool error", "succeeded": False}
        if self.side_effect == "rate_limit":
            return {"error": self.error_message or "Rate limited", "succeeded": False}
        return {"result": self.response, "succeeded": True}


class MockEnvironment:
    def __init__(self, tools_config: dict):
        self.tools: dict[str, MockTool] = {}
        for name, cfg in tools_config.items():
            side_effect = cfg.get("side_effect")
            error_message = cfg.get("error_message")
            response = cfg.get("response")
            self.tools[name] = MockTool(name, response, side_effect, error_message)

    def get_tool(self, name: str) -> MockTool | None:
        return self.tools.get(name)

    def call_tool(self, name: str, **kwargs: Any) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}", "succeeded": False}
        return tool.invoke(**kwargs)

    def set_trace(self, trace: AgentTrace) -> None:
        pass  # no-op for mock


# ──────────────────────────────────────────────────────
# Scenario definitions
# ──────────────────────────────────────────────────────

SCENARIOS: list[SentinelScenario] = [
    SentinelScenario(
        id="refund-agent-timeout",
        name="Refund Agent Timeout Handling",
        description=(
            "Tests whether a refund processing agent can gracefully handle "
            "a search API timeout when looking up refund policies."
        ),
        task="Process a refund request for order #12345.",
        env_config={
            "tools": {
                "search": {"side_effect": "timeout", "error_message": "Search API timed out after 10s"},
                "cache": {"response": {"refund_policy": "30-day return window for defective items"}},
            }
        },
        chaos_config={"timeout": {"target": "search", "delay_ms": 15000, "probability": 1.0}},
        tags=["chaos", "timeout", "refund", "production"],
    ),
    SentinelScenario(
        id="cascade-db-api-ui",
        name="Cascading Database Failure",
        description="Cascading failure: database timeout propagates to API to UI.",
        task="Fetch the user dashboard data for user ID 789.",
        env_config={
            "tools": {
                "database": {"side_effect": "timeout", "error_message": "Database connection timeout"},
                "api_server": {"side_effect": "error", "error_message": "API unavailable"},
                "user_interface": {"response": {"fallback_message": "Dashboard partially loaded."}},
            }
        },
        chaos_config={"timeout": {"target": "database", "delay_ms": 8000, "probability": 1.0}, "cascade": {"enabled": True}},
        tags=["chaos", "cascade", "production"],
    ),
    SentinelScenario(
        id="context-degradation-long",
        name="Context Degradation in Long Conversations",
        description="Long conversation degrades context, agent loses early instructions.",
        task="Process customer queries while maintaining strict rules.",
        env_config={
            "tools": {
                "customer_lookup": {"response": {"customer_id": "INT-78432", "name": "Robert Johnson"}},
                "order_history": {"response": {"recent_orders": [{"id": "ORD-9921", "amount": 149.99}]}},
            }
        },
        chaos_config={"context_degradation": {"intensity": "high", "turn_threshold": 3, "instruction_loss_probability": 0.4}},
        tags=["chaos", "context", "degradation"],
    ),
    SentinelScenario(
        id="spec-drift-pressure",
        name="Spec Drift Under Error Pressure",
        description="Agent improvises under error pressure, drifts from spec.",
        task="Process a booking request while following strict specification.",
        env_config={
            "tools": {
                "availability_check": {"response": {"available_slots": ["2026-08-15", "2026-08-22"]}},
                "booking_service": {"side_effect": "error", "error_message": "Booking service 503"},
            }
        },
        chaos_config={"spec_drift": {"intensity": "moderate", "error_injection_count": 3}},
        tags=["chaos", "spec-drift", "pressure"],
    ),
    SentinelScenario(
        id="network-partition-db",
        name="Network Partition Database Recovery",
        description="Database unreachable due to network partition, agent uses fallback.",
        task="Retrieve inventory status from all warehouse sources.",
        env_config={
            "tools": {
                "primary_database": {"side_effect": "error", "error_message": "Connection refused: network unreachable"},
                "replica_east": {"response": {"warehouse": "east", "items": [{"sku": "WH-E-001", "quantity": 234}]}},
                "replica_west": {"response": {"warehouse": "west", "items": [{"sku": "WH-W-001", "quantity": 156}]}},
            }
        },
        chaos_config={"network_partition": {"target": "primary_database", "partition_type": "full"}},
        tags=["chaos", "network", "partition"],
    ),
    SentinelScenario(
        id="memory-pressure-evict",
        name="Memory Pressure Context Eviction",
        description="Memory pressure forces context eviction, agent loses important state.",
        task="Process multi-step order while maintaining critical state.",
        env_config={
            "tools": {
                "session_manager": {"response": {"session_id": "sess_a1b2c3d4", "user": "authenticated"}},
                "order_service": {"response": {"order_id": "ORD-5521", "total": 215.98}},
                "payment_service": {"response": {"selected": "credit_card", "last_four": "4242"}},
            }
        },
        chaos_config={"memory_pressure": {"max_context_tokens": 2000, "eviction_strategy": "lru", "eviction_rate": 0.3}},
        tags=["chaos", "memory", "eviction"],
    ),
    SentinelScenario(
        id="rate-limit-retry",
        name="Rate Limit Retry with Backoff",
        description="Tool hits rate limit, agent should retry with backoff.",
        task="Search product catalog with retry logic for rate-limited API.",
        env_config={
            "tools": {
                "search_api": {"side_effect": "rate_limit", "error_message": "429 Too Many Requests"},
            }
        },
        chaos_config={"rate_limit": {"target": "search_api", "backoff_multiplier": 2.0, "succeed_after_retries": 2}},
        tags=["chaos", "rate-limit", "retry"],
    ),
    SentinelScenario(
        id="multi-tool-resilience",
        name="Multi-Tool Full Chaos Resilience",
        description="Full chaos suite: multiple injectors active simultaneously.",
        task="Handle complex customer complaint using all available tools.",
        env_config={
            "tools": {
                "search": {"side_effect": "timeout", "error_message": "Search service timeout"},
                "database": {"side_effect": "error", "error_message": "Database locked"},
                "api_server": {"response": {"tracking_status": "in_transit"}},
                "email": {"side_effect": "rate_limit", "error_message": "Email rate limited"},
                "cache": {"response": {"recent_orders": [{"order_id": "ORD-7721", "customer": "Alice Cooper"}]}},
            }
        },
        chaos_config={"multi_inject": {"enabled": True, "orchestration": "simultaneous"}},
        tags=["chaos", "resilience", "production", "smoke-test"],
    ),
]


# ──────────────────────────────────────────────────────
# Serialization helpers (mirrors persistence.py format)
# ──────────────────────────────────────────────────────

def _safe_serialize(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(item) for item in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, StrEnum):
        return obj.value
    return str(obj)


def _serialize_run(state: RunState) -> dict[str, Any]:
    """Serialize a RunState to the exact format persistence.save_run produces."""
    payload: dict[str, Any] = {
        "run_id": state.run_id,
        "scenario_id": state.scenario_id,
        "scenario_name": state.scenario_name,
        "status": state.status,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
    }

    if state.result is not None:
        result = state.result
        trace = result.trace
        payload["result"] = {
            "scenario_id": result.scenario_id,
            "scenario_name": result.scenario_name,
            "passed": result.passed,
            "duration_ms": result.duration_ms,
            "error": result.error,
            "timestamp": result.timestamp,
            "assertion_results": [
                {
                    "assertion_name": a.assertion_name,
                    "passed": a.passed,
                    "error_message": a.error_message,
                    "duration_ms": a.duration_ms,
                }
                for a in result.assertion_results
            ],
            "trace": {
                "total_steps": trace.total_steps,
                "total_tool_calls": trace.total_tool_calls,
                "total_duration_ms": trace.total_duration_ms,
                "tool_names_called": trace.tool_names_called,
                "failed_tool_calls": [
                    {
                        "tool_name": tc.tool_name,
                        "arguments": tc.arguments,
                        "result": _safe_serialize(tc.result),
                        "duration_ms": tc.duration_ms,
                        "error": tc.error,
                        "step_id": tc.step_id,
                        "timestamp": tc.timestamp,
                    }
                    for tc in trace.tool_calls
                ],
                "errors": [
                    {
                        "message": e.message,
                        "severity": e.severity.value,
                        "step_id": e.step_id,
                        "recoverable": e.recoverable,
                        "timestamp": e.timestamp,
                    }
                    for e in trace.errors
                ],
                "state_changes": [
                    {
                        "key": sc.key,
                        "old_value": _safe_serialize(sc.old_value),
                        "new_value": _safe_serialize(sc.new_value),
                        "step_id": sc.step_id,
                        "timestamp": sc.timestamp,
                    }
                    for sc in trace.state_changes
                ],
                "steps": [
                    {
                        "step_id": s.step_id,
                        "action": s.action.value,
                        "input": _safe_serialize(s.input),
                        "output": _safe_serialize(s.output),
                        "duration_ms": s.duration_ms,
                        "tool_calls": [
                            {
                                "tool_name": tc.tool_name,
                                "arguments": tc.arguments,
                                "result": _safe_serialize(tc.result),
                                "duration_ms": tc.duration_ms,
                                "error": tc.error,
                                "step_id": tc.step_id,
                                "timestamp": tc.timestamp,
                            }
                            for tc in s.tool_calls
                        ],
                        "error": (
                            {
                                "message": s.error.message,
                                "severity": s.error.severity.value,
                                "step_id": s.error.step_id,
                                "recoverable": s.error.recoverable,
                                "timestamp": s.error.timestamp,
                            }
                            if s.error is not None
                            else None
                        ),
                    }
                    for s in trace.steps
                ],
                "metadata": _safe_serialize(trace.metadata),
                "start_time": trace._start_time,
                "end_time": trace._end_time,
            },
        }

    return payload


def _serialize_baseline_result(result: SentinelResult) -> dict[str, Any]:
    """Serialize a SentinelResult for baseline results.json."""
    trace = result.trace
    return {
        "scenario_id": result.scenario_id,
        "scenario_name": result.scenario_name,
        "passed": result.passed,
        "duration_ms": result.duration_ms,
        "error": result.error,
        "timestamp": result.timestamp,
        "assertion_results": [
            {
                "assertion_name": a.assertion_name,
                "passed": a.passed,
                "error_message": a.error_message,
                "duration_ms": a.duration_ms,
            }
            for a in result.assertion_results
        ],
        "trace": {
            "total_steps": trace.total_steps,
            "total_tool_calls": trace.total_tool_calls,
            "total_duration_ms": trace.total_duration_ms,
            "tool_names_called": trace.tool_names_called,
            "failed_tool_calls_count": len(trace.failed_tool_calls),
            "errors_count": len(trace.errors),
            "state_changes_count": len(trace.state_changes),
            "steps": [
                {
                    "step_id": s.step_id,
                    "action": s.action.value,
                    "duration_ms": s.duration_ms,
                    "error": (
                        {"message": s.error.message, "severity": s.error.severity.value}
                        if s.error else None
                    ),
                }
                for s in trace.steps
            ],
            "tool_calls": [
                {
                    "tool_name": tc.tool_name,
                    "arguments": tc.arguments,
                    "duration_ms": tc.duration_ms,
                    "error": tc.error,
                    "succeeded": tc.succeeded,
                    "step_id": tc.step_id,
                    "timestamp": tc.timestamp,
                }
                for tc in trace.tool_calls
            ],
            "errors": [
                {
                    "message": e.message,
                    "severity": e.severity.value,
                    "recoverable": e.recoverable,
                    "step_id": e.step_id,
                    "timestamp": e.timestamp,
                }
                for e in trace.errors
            ],
            "state_changes": [
                {
                    "key": sc.key,
                    "old_value": sc.old_value,
                    "new_value": sc.new_value,
                    "step_id": sc.step_id,
                    "timestamp": sc.timestamp,
                }
                for sc in trace.state_changes
            ],
            "metadata": trace.metadata,
        },
    }


# ──────────────────────────────────────────────────────
# Mock agent functions — one per scenario
# ──────────────────────────────────────────────────────

def agent_refund_timeout(task: str, env: MockEnvironment, trace: AgentTrace) -> str:
    """Agent handles search timeout by falling back to cache."""
    trace.add_step(Step(
        step_id=1, action=StepAction.REASON,
        input="Planning refund processing steps",
        output="I will search for refund policy, then verify order, then process refund",
        duration_ms=5.2,
    ))
    search_result = env.call_tool("search", query="refund policy")
    trace.add_step(Step(
        step_id=2, action=StepAction.TOOL_CALL,
        input="search(query='refund policy')",
        output=json.dumps(search_result),
        duration_ms=10023.0,
        tool_calls=[ToolCall("search", {"query": "refund policy"}, search_result, 10023.0, "Search API timed out")],
    ))
    trace.add_error(Error("Search API timed out after 10s", ErrorSeverity.HIGH, step_id=2))

    cache_result = env.call_tool("cache", key="refund_policy")
    trace.add_step(Step(
        step_id=3, action=StepAction.TOOL_CALL,
        input="cache(key='refund_policy')",
        output=json.dumps(cache_result),
        duration_ms=8.3,
        tool_calls=[ToolCall("cache", {"key": "refund_policy"}, cache_result, 8.3)],
    ))

    trace.add_step(Step(
        step_id=4, action=StepAction.RESPOND,
        input="Generate refund response",
        output="Refund of $49.99 approved for order #12345. Policy: 30-day return window for defective items.",
        duration_ms=3.1,
    ))
    return "Refund approved for order #12345 — $49.99. Used cached policy due to search timeout."


def agent_cascade_db(task: str, env: MockEnvironment, trace: AgentTrace) -> str:
    """Agent handles cascading DB failure with fallback data."""
    trace.add_step(Step(
        step_id=1, action=StepAction.REASON,
        input="Planning dashboard fetch with dependency chain",
        output="Fetch DB → API → UI. Will detect failures and use fallbacks.",
        duration_ms=4.8,
    ))

    db_result = env.call_tool("database", query="user 789")
    trace.add_step(Step(
        step_id=2, action=StepAction.TOOL_CALL,
        input="database(query='user 789')",
        output=json.dumps(db_result),
        duration_ms=8012.0,
        tool_calls=[ToolCall("database", {"query": "user 789"}, db_result, 8012.0, "Database timeout")],
    ))
    trace.add_error(Error("Database connection timeout", ErrorSeverity.HIGH, step_id=2))

    api_result = env.call_tool("api_server", path="/user/789/orders")
    trace.add_step(Step(
        step_id=3, action=StepAction.TOOL_CALL,
        input="api_server(path='/user/789/orders')",
        output=json.dumps(api_result),
        duration_ms=1500.0,
        tool_calls=[ToolCall("api_server", {"path": "/user/789/orders"}, api_result, 1500.0, "API unavailable")],
    ))
    trace.add_error(Error("API unavailable: upstream dependency failed", ErrorSeverity.HIGH, step_id=3))

    ui_result = env.call_tool("user_interface", view="dashboard")
    trace.add_step(Step(
        step_id=4, action=StepAction.TOOL_CALL,
        input="user_interface(view='dashboard')",
        output=json.dumps(ui_result),
        duration_ms=12.0,
        tool_calls=[ToolCall("user_interface", {"view": "dashboard"}, ui_result, 12.0)],
    ))

    trace.add_step(Step(
        step_id=5, action=StepAction.RESPOND,
        input="Generate partial dashboard response",
        output="Dashboard partially loaded with cached profile data.",
        duration_ms=2.5,
    ))
    return "Dashboard loaded with degraded data — cached profile available, orders unavailable."


def agent_context_degradation(task: str, env: MockEnvironment, trace: AgentTrace) -> str:
    """Agent processes queries but starts losing rules under degradation."""
    trace.add_step(Step(
        step_id=1, action=StepAction.REASON,
        input="Load customer queries and rules",
        output="I will process queries while maintaining all 3 rules.",
        duration_ms=3.2,
    ))

    lookup = env.call_tool("customer_lookup", id="78432")
    trace.add_step(Step(
        step_id=2, action=StepAction.TOOL_CALL,
        input="customer_lookup(id='78432')",
        output=json.dumps(lookup),
        duration_ms=15.0,
        tool_calls=[ToolCall("customer_lookup", {"id": "78432"}, lookup, 15.0)],
    ))

    history = env.call_tool("order_history", customer_id="78432")
    trace.add_step(Step(
        step_id=3, action=StepAction.TOOL_CALL,
        input="order_history(customer_id='78432')",
        output=json.dumps(history),
        duration_ms=22.0,
        tool_calls=[ToolCall("order_history", {"customer_id": "78432"}, history, 22.0)],
    ))

    # Simulate degradation — context rules lost
    trace.add_step(Step(
        step_id=4, action=StepAction.ERROR,
        input="Processing query 3 with context pressure",
        output="Response generated but formality rule dropped",
        duration_ms=8.5,
        error=Error("Formality rule not applied to response after context pressure", ErrorSeverity.MEDIUM, step_id=4),
    ))

    trace.add_step(Step(
        step_id=5, action=StepAction.RESPOND,
        input="Final response",
        output="Customer Robert Johnson has 2 recent orders totaling $409.98.",
        duration_ms=4.0,
    ))
    return "Processed all queries — warnings on formality rule adherence after turn 3."


def agent_spec_drift(task: str, env: MockEnvironment, trace: AgentTrace) -> str:
    """Agent encounters errors and drifts from specification."""
    trace.add_step(Step(
        step_id=1, action=StepAction.REASON,
        input="Parse booking request and specification",
        output="Will confirm dates, check availability, then book with confirmation.",
        duration_ms=4.1,
    ))

    avail = env.call_tool("availability_check", date_range="2026-08")
    trace.add_step(Step(
        step_id=2, action=StepAction.TOOL_CALL,
        input="availability_check(date_range='2026-08')",
        output=json.dumps(avail),
        duration_ms=45.0,
        tool_calls=[ToolCall("availability_check", {"date_range": "2026-08"}, avail, 45.0)],
    ))

    booking = env.call_tool("booking_service", date="2026-08-15")
    trace.add_step(Step(
        step_id=3, action=StepAction.TOOL_CALL,
        input="booking_service(date='2026-08-15')",
        output=json.dumps(booking),
        duration_ms=2015.0,
        tool_calls=[ToolCall("booking_service", {"date": "2026-08-15"}, booking, 2015.0, "503 Service Unavailable")],
    ))
    trace.add_error(Error("Booking service 503", ErrorSeverity.HIGH, step_id=3))

    # Drift: agent improvises without confirmation
    trace.add_step(Step(
        step_id=4, action=StepAction.ERROR,
        input="Error handling — attempting recovery",
        output="Agent skips confirmation step and books alternative without user approval",
        duration_ms=6.2,
        error=Error("Confirmation step skipped — spec violation", ErrorSeverity.MEDIUM, step_id=4, recoverable=False),
    ))

    trace.add_step(Step(
        step_id=5, action=StepAction.RESPOND,
        input="Generate response",
        output="Booking confirmed for 2026-08-22. No user confirmation obtained.",
        duration_ms=3.0,
    ))
    return "Booking completed but spec drift detected — no user confirmation obtained."


def agent_network_partition(task: str, env: MockEnvironment, trace: AgentTrace) -> str:
    """Agent detects partition and falls back to replicas."""
    trace.add_step(Step(
        step_id=1, action=StepAction.REASON,
        input="Inventory query — check all data sources",
        output="Will try primary DB, then replicas if partition detected.",
        duration_ms=3.8,
    ))

    primary = env.call_tool("primary_database", query="inventory")
    trace.add_step(Step(
        step_id=2, action=StepAction.TOOL_CALL,
        input="primary_database(query='inventory')",
        output=json.dumps(primary),
        duration_ms=5012.0,
        tool_calls=[ToolCall("primary_database", {"query": "inventory"}, primary, 5012.0, "Network unreachable")],
    ))
    trace.add_error(Error("Connection refused: network unreachable", ErrorSeverity.HIGH, step_id=2))

    east = env.call_tool("replica_east", query="inventory")
    trace.add_step(Step(
        step_id=3, action=StepAction.TOOL_CALL,
        input="replica_east(query='inventory')",
        output=json.dumps(east),
        duration_ms=120.0,
        tool_calls=[ToolCall("replica_east", {"query": "inventory"}, east, 120.0)],
    ))

    west = env.call_tool("replica_west", query="inventory")
    trace.add_step(Step(
        step_id=4, action=StepAction.TOOL_CALL,
        input="replica_west(query='inventory')",
        output=json.dumps(west),
        duration_ms=135.0,
        tool_calls=[ToolCall("replica_west", {"query": "inventory"}, west, 135.0)],
    ))

    trace.add_step(Step(
        step_id=5, action=StepAction.RESPOND,
        input="Aggregate replica data",
        output="Combined inventory from east (234 units) and west (156 units) warehouses.",
        duration_ms=5.0,
    ))
    return "Inventory aggregated from 2 replicas — 390 total units across warehouses."


def agent_memory_pressure(task: str, env: MockEnvironment, trace: AgentTrace) -> str:
    """Agent maintains critical state under memory pressure."""
    trace.add_step(Step(
        step_id=1, action=StepAction.REASON,
        input="Initialize order processing session",
        output="Will maintain session, order, and payment state throughout.",
        duration_ms=4.5,
    ))

    session = env.call_tool("session_manager", action="init")
    trace.add_step(Step(
        step_id=2, action=StepAction.TOOL_CALL,
        input="session_manager(action='init')",
        output=json.dumps(session),
        duration_ms=10.0,
        tool_calls=[ToolCall("session_manager", {"action": "init"}, session, 10.0)],
    ))
    trace.add_state_change(StateChange("session", None, "sess_a1b2c3d4", step_id=2))

    order = env.call_tool("order_service", action="create")
    trace.add_step(Step(
        step_id=3, action=StepAction.TOOL_CALL,
        input="order_service(action='create')",
        output=json.dumps(order),
        duration_ms=25.0,
        tool_calls=[ToolCall("order_service", {"action": "create"}, order, 25.0)],
    ))
    trace.add_state_change(StateChange("order_id", None, "ORD-5521", step_id=3))

    payment = env.call_tool("payment_service", action="select")
    trace.add_step(Step(
        step_id=4, action=StepAction.TOOL_CALL,
        input="payment_service(action='select')",
        output=json.dumps(payment),
        duration_ms=18.0,
        tool_calls=[ToolCall("payment_service", {"action": "select"}, payment, 18.0)],
    ))
    trace.add_state_change(StateChange("payment_method", None, "credit_card", step_id=4))

    # Simulate eviction warning
    trace.add_step(Step(
        step_id=5, action=StepAction.ERROR,
        input="Memory pressure detected — evicting non-critical context",
        output="Evicted 3 non-critical entries. Protected session, order, payment.",
        duration_ms=2.0,
        error=Error("Context eviction triggered at 70% threshold", ErrorSeverity.MEDIUM, step_id=5),
    ))

    trace.add_step(Step(
        step_id=6, action=StepAction.RESPOND,
        input="Complete order with critical state preserved",
        output="Order ORD-5521 completed. Payment via credit card ****4242. Total: $215.98.",
        duration_ms=3.5,
    ))
    return "Order completed successfully — critical state preserved under memory pressure."


def agent_rate_limit(task: str, env: MockEnvironment, trace: AgentTrace) -> str:
    """Agent retries with exponential backoff on rate limit."""
    trace.add_step(Step(
        step_id=1, action=StepAction.REASON,
        input="Search catalog with retry strategy",
        output="Will search and retry with backoff if rate limited.",
        duration_ms=3.0,
    ))

    # Attempt 1 — rate limited
    r1 = env.call_tool("search_api", query="ergonomic keyboard")
    trace.add_step(Step(
        step_id=2, action=StepAction.TOOL_CALL,
        input="search_api(query='ergonomic keyboard') [attempt 1]",
        output=json.dumps(r1),
        duration_ms=50.0,
        tool_calls=[ToolCall("search_api", {"attempt": 1}, r1, 50.0, "429 Rate Limited")],
    ))
    trace.add_error(Error("Rate limit exceeded", ErrorSeverity.MEDIUM, step_id=2))

    trace.add_step(Step(
        step_id=3, action=StepAction.ERROR,
        input="Waiting 2000ms before retry",
        output="Exponential backoff: attempt 2 after 2s delay",
        duration_ms=2000.0,
    ))

    # Attempt 2 — rate limited again
    r2 = env.call_tool("search_api", query="ergonomic keyboard")
    trace.add_step(Step(
        step_id=4, action=StepAction.TOOL_CALL,
        input="search_api(query='ergonomic keyboard') [attempt 2]",
        output=json.dumps(r2),
        duration_ms=45.0,
        tool_calls=[ToolCall("search_api", {"attempt": 2}, r2, 45.0, "429 Rate Limited")],
    ))
    trace.add_error(Error("Rate limit exceeded on retry", ErrorSeverity.MEDIUM, step_id=4))

    trace.add_step(Step(
        step_id=5, action=StepAction.ERROR,
        input="Waiting 4000ms before retry (backoff x2)",
        output="Exponential backoff: attempt 3 after 4s delay",
        duration_ms=4000.0,
    ))

    # Attempt 3 — succeeds
    r3 = {"results": [{"name": "Ergo Keyboard Pro", "price": 149.99}, {"name": "Split Keyboard Elite", "price": 199.99}]}
    trace.add_step(Step(
        step_id=6, action=StepAction.TOOL_CALL,
        input="search_api(query='ergonomic keyboard') [attempt 3]",
        output=json.dumps(r3),
        duration_ms=120.0,
        tool_calls=[ToolCall("search_api", {"attempt": 3}, r3, 120.0)],
    ))

    trace.add_step(Step(
        step_id=7, action=StepAction.RESPOND,
        input="Return search results",
        output="Found 2 ergonomic keyboards: Ergo Keyboard Pro ($149.99), Split Keyboard Elite ($199.99).",
        duration_ms=2.5,
    ))
    return "Search succeeded after 3 attempts with exponential backoff."


def agent_multi_tool_resilience(task: str, env: MockEnvironment, trace: AgentTrace) -> str:
    """Agent handles multiple simultaneous tool failures."""
    trace.add_step(Step(
        step_id=1, action=StepAction.REASON,
        input="Analyze customer complaint — multiple issues reported",
        output="Will attempt all tools in priority order, using fallbacks where needed.",
        duration_ms=5.0,
    ))

    # search — timeout
    s = env.call_tool("search", query="order ORD-7721")
    trace.add_step(Step(
        step_id=2, action=StepAction.TOOL_CALL,
        input="search(query='order ORD-7721')",
        output=json.dumps(s),
        duration_ms=10018.0,
        tool_calls=[ToolCall("search", {"query": "order ORD-7721"}, s, 10018.0, "Timeout")],
    ))
    trace.add_error(Error("Search service timeout", ErrorSeverity.HIGH, step_id=2))

    # database — error
    d = env.call_tool("database", query="order ORD-7721")
    trace.add_step(Step(
        step_id=3, action=StepAction.TOOL_CALL,
        input="database(query='order ORD-7721')",
        output=json.dumps(d),
        duration_ms=8.0,
        tool_calls=[ToolCall("database", {"query": "order ORD-7721"}, d, 8.0, "DB locked")],
    ))
    trace.add_error(Error("Database locked: too many connections", ErrorSeverity.HIGH, step_id=3))

    # api_server — succeeds
    a = env.call_tool("api_server", path="/tracking/FX-9876543210")
    trace.add_step(Step(
        step_id=4, action=StepAction.TOOL_CALL,
        input="api_server(path='/tracking/FX-9876543210')",
        output=json.dumps(a),
        duration_ms=250.0,
        tool_calls=[ToolCall("api_server", {"path": "/tracking/FX-9876543210"}, a, 250.0)],
    ))

    # email — rate limited
    e = env.call_tool("email", to="alice@example.com", subject="Order Update")
    trace.add_step(Step(
        step_id=5, action=StepAction.TOOL_CALL,
        input="email(to='alice@example.com', subject='Order Update')",
        output=json.dumps(e),
        duration_ms=50.0,
        tool_calls=[ToolCall("email", {"to": "alice@example.com"}, e, 50.0, "Rate limited")],
    ))
    trace.add_error(Error("Email service rate limited", ErrorSeverity.MEDIUM, step_id=5))

    # cache fallback
    c = env.call_tool("cache", key="recent_orders")
    trace.add_step(Step(
        step_id=6, action=StepAction.TOOL_CALL,
        input="cache(key='recent_orders')",
        output=json.dumps(c),
        duration_ms=5.0,
        tool_calls=[ToolCall("cache", {"key": "recent_orders"}, c, 5.0)],
    ))

    trace.add_step(Step(
        step_id=7, action=StepAction.RESPOND,
        input="Generate response with partial data",
        output="Order ORD-7721 found via cache. Tracking: in transit, FedEx FX-9876543210. Email queued.",
        duration_ms=3.2,
    ))
    return "Partial success — order found via cache, tracking via API, email deferred."


# Map scenario IDs to their mock agent functions
AGENT_FUNCTIONS: dict[str, Callable] = {
    "refund-agent-timeout": agent_refund_timeout,
    "cascade-db-api-ui": agent_cascade_db,
    "context-degradation-long": agent_context_degradation,
    "spec-drift-pressure": agent_spec_drift,
    "network-partition-db": agent_network_partition,
    "memory-pressure-evict": agent_memory_pressure,
    "rate-limit-retry": agent_rate_limit,
    "multi-tool-resilience": agent_multi_tool_resilience,
}


# ──────────────────────────────────────────────────────
# Assertion generators — each outcome type
# ──────────────────────────────────────────────────────

def _assertions_pass() -> list[SentinelAssertionResult]:
    return [
        SentinelAssertionResult("tool_fallback_used", True, duration_ms=1.2),
        SentinelAssertionResult("graceful_degradation", True, duration_ms=0.8),
        SentinelAssertionResult("error_handling", True, duration_ms=0.5),
        SentinelAssertionResult("response_quality", True, duration_ms=0.3),
    ]


def _assertions_warn() -> list[SentinelAssertionResult]:
    return [
        SentinelAssertionResult("tool_fallback_used", True, duration_ms=1.5),
        SentinelAssertionResult("graceful_degradation", True, duration_ms=0.9),
        SentinelAssertionResult("error_handling", True, duration_ms=0.6),
        SentinelAssertionResult("response_quality", True, duration_ms=0.4),
    ]


def _assertions_fail() -> list[SentinelAssertionResult]:
    return [
        SentinelAssertionResult("tool_fallback_used", False, "Fallback not triggered", 1.0),
        SentinelAssertionResult("graceful_degradation", False, "Agent crashed or hung", 0.8),
        SentinelAssertionResult("error_handling", False, "Error propagated unhandled", 0.5),
        SentinelAssertionResult("response_quality", False, "No useful response produced", 0.3),
    ]


ASSERTION_GENERATORS = [_assertions_pass, _assertions_warn, _assertions_fail]


# ──────────────────────────────────────────────────────
# Run runner — creates a RunState from a scenario + outcome
# ──────────────────────────────────────────────────────

def run_scenario(scenario: SentinelScenario, outcome_idx: int) -> RunState:
    """Run a scenario with a specific outcome index (0=pass, 1=warn, 2=fail)."""
    run_id = str(uuid.uuid4())[:12]
    started_at = datetime.now(timezone.utc)

    agent_fn = AGENT_FUNCTIONS[scenario.id]
    env = MockEnvironment(scenario.env_config.get("tools", {}))
    trace = AgentTrace()

    t0 = time.time()
    agent_fn(scenario.task, env, trace)
    trace.finish()
    duration_ms = (time.time() - t0) * 1000

    completed_at = datetime.now(timezone.utc)
    passed = outcome_idx < 2  # 0=pass, 1=warn still pass, 2=fail
    assertion_results = ASSERTION_GENERATORS[outcome_idx]()

    result = SentinelResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        passed=passed,
        trace=trace,
        assertion_results=assertion_results,
        duration_ms=round(duration_ms, 2),
        timestamp=time.time(),
    )

    status = "pass" if passed else "fail"

    return RunState(
        run_id=run_id,
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        result=result,
    )


# ──────────────────────────────────────────────────────
# Baseline generator
# ──────────────────────────────────────────────────────

def generate_baseline(
    label: str,
    results: list[SentinelResult],
    tags: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Create baseline metadata + results in the format baseline.py produces."""
    meta = {
        "label": label,
        "timestamp": time.time(),
        "git_sha": "",
        "git_branch": "",
        "tags": tags or [],
        "description": description or f"Demo baseline — {label}",
        "scenario_count": len(results),
        "pass_count": sum(1 for r in results if r.passed),
        "fail_count": sum(1 for r in results if not r.passed),
        "metadata": {},
    }
    serialized = [_serialize_baseline_result(r) for r in results]
    return {"metadata": meta, "results": serialized}


# ──────────────────────────────────────────────────────
# Main — generate all demo data
# ──────────────────────────────────────────────────────

def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    runs_dir = project_root / ".sentinel" / "runs"
    baselines_dir = project_root / ".sentinel" / "baselines"
    runs_dir.mkdir(parents=True, exist_ok=True)
    baselines_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Sentinel Demo Data Generator")
    print("=" * 60)
    print()

    all_results: list[SentinelResult] = []

    for scenario in SCENARIOS:
        print(f"  Scenario: {scenario.name}")
        for outcome_idx, outcome_label in enumerate(["pass", "pass_with_warnings", "fail"]):
            run = run_scenario(scenario, outcome_idx)
            run_path = runs_dir / f"{run.run_id}.json"
            with open(run_path, "w") as f:
                json.dump(_serialize_run(run), f, indent=2)
            all_results.append(run.result)
            icon = {"pass": "✓", "pass_with_warnings": "⚠", "fail": "✗"}[outcome_label]
            print(f"    {icon}  {outcome_label:22s} → {run.run_id}  ({run.result.duration_ms:.1f}ms)")
        print()

    # --- Baselines ---
    print("  Generating baselines...")
    baseline_configs = [
        ("demo-v1", ["demo", "v1"], "Older demo baseline with mixed results"),
        ("demo-v2", ["demo", "v2"], "Improved demo baseline"),
        ("demo-v3", ["demo", "v3"], "Latest demo baseline"),
    ]

    for label, tags, desc in baseline_configs:
        bl = generate_baseline(label, all_results, tags, desc)
        bl_path = baselines_dir / label
        bl_path.mkdir(parents=True, exist_ok=True)
        with open(bl_path / "metadata.json", "w") as f:
            json.dump(bl["metadata"], f, indent=2)
        with open(bl_path / "results.json", "w") as f:
            json.dump(bl["results"], f, indent=2)
        meta = bl["metadata"]
        print(f"    ✓  baseline {label:10s} → {label}/  ({meta['scenario_count']} scenarios, {meta['pass_count']} pass, {meta['fail_count']} fail)")

    # --- Summary ---
    total_runs = len(all_results)
    print()
    print("=" * 60)
    print(f"  Generated {total_runs} run files  in  .sentinel/runs/")
    print(f"  Generated 3 baseline dirs in  .sentinel/baselines/")
    print(f"  Scenarios covered: {len(SCENARIOS)}")
    print(f"  Outcomes per scenario: pass / pass_with_warnings / fail")
    print("=" * 60)


if __name__ == "__main__":
    main()
