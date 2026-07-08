"""Core data models for Sentinel.

Defines the trace structures that capture agent execution for behavioral analysis.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class StepAction(str, Enum):
    """Types of actions an agent can take during execution."""

    PLAN = "plan"
    TOOL_CALL = "tool_call"
    REASON = "reason"
    RESPOND = "respond"
    ERROR = "error"


class ErrorSeverity(str, Enum):
    """Severity of errors encountered during execution."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ToolCall:
    """Records a single tool invocation by the agent.

    Captures the tool name, arguments, result, and timing
    to enable behavioral assertions on tool usage patterns.
    """

    tool_name: str
    arguments: Dict[str, Any]
    result: Any = None
    duration_ms: float = 0.0
    error: Optional[str] = None
    step_id: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class StateChange:
    """Records a mutation to agent memory or state.

    Tracks key-value changes to detect state inconsistency,
    staleness, and cross-session divergence.
    """

    key: str
    old_value: Any = None
    new_value: Any = None
    step_id: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class Error:
    """Records an error encountered during agent execution."""

    message: str
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    step_id: int = 0
    recoverable: bool = True
    timestamp: float = field(default_factory=time.time)


@dataclass
class Step:
    """A single execution step in the agent's trace.

    Each step represents one atomic action: planning, calling a tool,
    reasoning, or producing output. Steps are ordered by step_id.
    """

    step_id: int
    action: StepAction
    input: Any = None
    output: Any = None
    duration_ms: float = 0.0
    tool_calls: List[ToolCall] = field(default_factory=list)
    error: Optional[Error] = None


@dataclass
class AgentTrace:
    """Full execution trace of an agent run.

    This is the primary data structure for behavioral analysis.
    It captures everything the agent did, in order, with timing
    and error information.
    """

    steps: List[Step] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    state_changes: List[StateChange] = field(default_factory=list)
    errors: List[Error] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Execution tracking
    _start_time: float = field(default_factory=time.time, repr=False)
    _end_time: Optional[float] = field(default=None, repr=False)

    def finish(self) -> None:
        """Mark the trace as complete."""
        self._end_time = time.time()

    @property
    def total_duration_ms(self) -> float:
        """Total execution time in milliseconds."""
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
    def failed_tool_calls(self) -> List[ToolCall]:
        return [tc for tc in self.tool_calls if not tc.succeeded]

    @property
    def tool_names_called(self) -> List[str]:
        """Unique tool names in order of first call."""
        seen = set()
        result = []
        for tc in self.tool_calls:
            if tc.tool_name not in seen:
                seen.add(tc.tool_name)
                result.append(tc.tool_name)
        return result

    def tool_calls_by_name(self, name: str) -> List[ToolCall]:
        """Get all calls to a specific tool, in order."""
        return [tc for tc in self.tool_calls if tc.tool_name == name]

    def add_step(self, step: Step) -> None:
        """Append a step and index its tool calls."""
        self.steps.append(step)
        for tc in step.tool_calls:
            tc.step_id = step.step_id
            self.tool_calls.append(tc)

    def add_tool_call(self, call: ToolCall) -> None:
        """Record a tool call at the trace level."""
        self.tool_calls.append(call)

    def add_state_change(self, change: StateChange) -> None:
        self.state_changes.append(change)

    def add_error(self, error: Error) -> None:
        self.errors.append(error)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize trace to a dictionary for reporting."""
        return {
            "total_steps": self.total_steps,
            "total_tool_calls": self.total_tool_calls,
            "total_duration_ms": self.total_duration_ms,
            "tool_names_called": self.tool_names_called,
            "failed_tool_calls": len(self.failed_tool_calls),
            "errors": len(self.errors),
            "state_changes": len(self.state_changes),
            "metadata": self.metadata,
        }
