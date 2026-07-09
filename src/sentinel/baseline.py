"""Baseline storage for Sentinel test traces.

Provides persistence for recording, loading, and comparing agent
execution baselines. Baselines are stored as JSON files in a
configurable directory (default: .sentinel/baselines/).

Each baseline is a directory containing:
  - metadata.json: label, timestamp, git info, tags
  - results.json: serialized SentinelResult list
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sentinel.models import (
    AgentTrace,
    Error,
    ErrorSeverity,
    StateChange,
    Step,
    StepAction,
    ToolCall,
)
from sentinel.runner import SentinelAssertionResult, SentinelResult


# Default baseline directory relative to project root
_DEFAULT_BASELINE_DIR = ".sentinel/baselines"


__all__ = [
    "BaselineMetadata",
    "record_baseline",
    "load_baseline",
    "compare_baselines",
]


@dataclass
class BaselineMetadata:
    """Metadata for a recorded baseline."""

    label: str
    timestamp: float = field(default_factory=time.time)
    git_sha: str = ""
    git_branch: str = ""
    tags: List[str] = field(default_factory=list)
    description: str = ""
    scenario_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────
# Serialization helpers
# ──────────────────────────────────────────────────────


def _serialize_result(result: SentinelResult) -> Dict[str, Any]:
    """Serialize a SentinelResult to a JSON-compatible dict.

    Handles dataclass nested structures and enums.
    """
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
        "trace": _serialize_trace(result.trace),
    }


def _serialize_trace(trace: AgentTrace) -> Dict[str, Any]:
    """Serialize an AgentTrace to a JSON-compatible dict."""
    return {
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
                "error": {"message": s.error.message, "severity": s.error.severity.value}
                         if s.error else None,
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
    }


def _deserialize_trace(data: Dict[str, Any]) -> AgentTrace:
    """Deserialize a dict back into an AgentTrace."""
    trace = AgentTrace()
    trace.metadata = data.get("metadata", {})

    for s in data.get("steps", []):
        error = None
        if s.get("error"):
            error = Error(
                message=s["error"]["message"],
                severity=ErrorSeverity(s["error"]["severity"]),
                step_id=s.get("step_id", 0),
            )
        step = Step(
            step_id=s["step_id"],
            action=StepAction(s["action"]),
            duration_ms=s.get("duration_ms", 0.0),
            error=error,
        )
        trace.steps.append(step)

    for tc in data.get("tool_calls", []):
        trace.tool_calls.append(
            ToolCall(
                tool_name=tc["tool_name"],
                arguments=tc.get("arguments", {}),
                duration_ms=tc.get("duration_ms", 0.0),
                error=tc.get("error"),
                step_id=tc.get("step_id", 0),
                timestamp=tc.get("timestamp", 0.0),
            )
        )

    for e in data.get("errors", []):
        trace.errors.append(
            Error(
                message=e["message"],
                severity=ErrorSeverity(e["severity"]),
                recoverable=e.get("recoverable", True),
                step_id=e.get("step_id", 0),
                timestamp=e.get("timestamp", 0.0),
            )
        )

    for sc in data.get("state_changes", []):
        trace.state_changes.append(
            StateChange(
                key=sc["key"],
                old_value=sc.get("old_value"),
                new_value=sc.get("new_value"),
                step_id=sc.get("step_id", 0),
                timestamp=sc.get("timestamp", 0.0),
            )
        )

    return trace


def _deserialize_result(data: Dict[str, Any]) -> SentinelResult:
    """Deserialize a dict back into a SentinelResult."""
    trace = _deserialize_trace(data.get("trace", {}))
    assertion_results = [
        SentinelAssertionResult(
            assertion_name=a["assertion_name"],
            passed=a["passed"],
            error_message=a.get("error_message"),
            duration_ms=a.get("duration_ms", 0.0),
        )
        for a in data.get("assertion_results", [])
    ]
    return SentinelResult(
        scenario_id=data["scenario_id"],
        scenario_name=data["scenario_name"],
        passed=data["passed"],
        trace=trace,
        assertion_results=assertion_results,
        duration_ms=data.get("duration_ms", 0.0),
        error=data.get("error"),
        timestamp=data.get("timestamp", 0.0),
    )


# ──────────────────────────────────────────────────────
# Baseline operations
# ──────────────────────────────────────────────────────


def get_baseline_dir(project_root: Optional[str] = None) -> Path:
    """Get the baseline directory, creating it if needed."""
    if project_root is None:
        # Walk up from this file to find project root (sentinel/src → project)
        project_root = str(Path(__file__).parent.parent.parent)
    baseline_dir = Path(project_root) / _DEFAULT_BASELINE_DIR
    baseline_dir.mkdir(parents=True, exist_ok=True)
    return baseline_dir


def record_baseline(
    results: List[SentinelResult],
    label: str,
    tags: Optional[List[str]] = None,
    description: str = "",
    git_sha: str = "",
    git_branch: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    project_root: Optional[str] = None,
) -> Path:
    """Record a set of results as a baseline.

    Creates a new baseline directory with metadata and serialized results.
    If a baseline with the same label exists, it's overwritten (explicit
    baseline update — no silent history loss, the directory just replaces).

    Args:
        results: List of SentinelResults to store.
        label: Human-readable label (e.g., "v1.2.3", "main-abc1234").
        tags: Classification tags (e.g., ["ci", "nightly"]).
        description: What this baseline represents.
        git_sha: Git commit SHA if available.
        git_branch: Git branch if available.
        metadata: Extra info to store.
        project_root: Override project root path.

    Returns:
        Path to the baseline directory.
    """
    baseline_dir = get_baseline_dir(project_root)
    baseline_path = baseline_dir / label
    baseline_path.mkdir(parents=True, exist_ok=True)

    # Metadata
    meta = BaselineMetadata(
        label=label,
        timestamp=time.time(),
        git_sha=git_sha,
        git_branch=git_branch,
        tags=tags or [],
        description=description,
        scenario_count=len(results),
        pass_count=sum(1 for r in results if r.passed),
        fail_count=sum(1 for r in results if not r.passed),
        metadata=metadata or {},
    )

    with open(baseline_path / "metadata.json", "w") as f:
        json.dump(asdict(meta), f, indent=2)

    # Results
    serialized = [_serialize_result(r) for r in results]
    with open(baseline_path / "results.json", "w") as f:
        json.dump(serialized, f, indent=2)

    return baseline_path


def load_baseline(
    label: str,
    project_root: Optional[str] = None,
) -> Tuple[BaselineMetadata, List[SentinelResult]]:
    """Load a previously recorded baseline.

    Args:
        label: The baseline label to load.
        project_root: Override project root path.

    Returns:
        Tuple of (BaselineMetadata, List[SentinelResult]).

    Raises:
        FileNotFoundError: If the baseline doesn't exist.
    """
    baseline_dir = get_baseline_dir(project_root)
    baseline_path = baseline_dir / label

    if not baseline_path.exists():
        raise FileNotFoundError(
            f"Baseline '{label}' not found. "
            f"Available: {', '.join(list_baselines(project_root))}"
        )

    with open(baseline_path / "metadata.json") as f:
        meta_data = json.load(f)
    meta = BaselineMetadata(**meta_data)

    with open(baseline_path / "results.json") as f:
        results_data = json.load(f)
    results = [_deserialize_result(r) for r in results_data]

    return meta, results


def list_baselines(project_root: Optional[str] = None) -> List[str]:
    """List all baseline labels, newest first."""
    baseline_dir = get_baseline_dir(project_root)
    if not baseline_dir.exists():
        return []

    labels = []
    for d in baseline_dir.iterdir():
        if d.is_dir() and (d / "metadata.json").exists():
            labels.append(d.name)

    # Sort by timestamp (newest first) — read metadata for each
    def _ts(label: str) -> float:
        try:
            meta_path = baseline_dir / label / "metadata.json"
            with open(meta_path) as f:
                return json.load(f).get("timestamp", 0)
        except Exception:
            return 0

    labels.sort(key=_ts, reverse=True)
    return labels


def delete_baseline(label: str, project_root: Optional[str] = None) -> bool:
    """Delete a baseline by label.

    Returns True if deleted, False if not found.
    """
    import shutil

    baseline_dir = get_baseline_dir(project_root)
    baseline_path = baseline_dir / label

    if baseline_path.exists() and baseline_path.is_dir():
        shutil.rmtree(baseline_path)
        return True
    return False

