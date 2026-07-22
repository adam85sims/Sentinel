"""Run history persistence — saves completed runs to JSON on disk.

Provides save/load/delete for RunState objects so the web UI can
restore run history across server restarts. Each run is stored as
an individual JSON file in ``.sentinel/runs/`` under the project root.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Resolve project root: services/ -> web/ -> sentinel/ -> src/ -> project root
# (5 levels up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
RUNS_DIR = _PROJECT_ROOT / ".sentinel" / "runs"


def _json_default(obj: Any) -> Any:
    """Custom JSON serialiser fallback for non-JSON-native objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, set):
        return sorted(obj)
    # Last resort: str() so we never crash json.dumps
    return str(obj)


def save_run(state: Any) -> None:
    """Persist a RunState to ``{RUNS_DIR}/{run_id}.json``.

    Serialises the full RunState including its nested result, trace,
    and assertion_results.  The ``event_queue`` field is intentionally
    skipped (not JSON-serialisable).
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "run_id": state.run_id,
        "scenario_id": state.scenario_id,
        "scenario_name": state.scenario_name,
        "status": state.status,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
    }

    # Serialise the SentinelResult (including trace & assertions) if present
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
                        "severity": e.severity.value if isinstance(e.severity, Enum) else str(e.severity),
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
                        "action": s.action.value if isinstance(s.action, Enum) else str(s.action),
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
                                "severity": s.error.severity.value if isinstance(s.error.severity, Enum) else str(s.error.severity),
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

    out_path = RUNS_DIR / f"{state.run_id}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    logger.debug("Persisted run %s to %s", state.run_id, out_path)


def load_all_runs() -> list[dict[str, Any]]:
    """Scan ``RUNS_DIR`` for ``*.json`` files and return deserialised run dicts.

    Returns a list sorted by ``started_at`` descending (newest first).
    Each dict has the same keys as a RunState, plus an optional ``result``
    dict with the full trace/assertion data.
    """
    if not RUNS_DIR.exists():
        return []

    runs: list[dict[str, Any]] = []
    for path in RUNS_DIR.glob("*.json"):
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            runs.append(data)
        except Exception:
            logger.warning("Skipping corrupt run file %s", path, exc_info=True)

    # Sort by started_at descending
    def _sort_key(r: dict[str, Any]) -> str:
        return r.get("started_at") or ""

    runs.sort(key=_sort_key, reverse=True)
    return runs


def load_run_result(run_id: str) -> dict[str, Any] | None:
    """Read the full persisted JSON for a single run and return the result dict.

    Returns None if the file does not exist or cannot be read.
    """
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read run file %s", path, exc_info=True)
        return None


def delete_run(run_id: str) -> bool:
    """Remove the JSON file for the given run.

    Returns True if the file was deleted, False if it did not exist.
    """
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return False
    try:
        path.unlink()
        logger.debug("Deleted persisted run %s", run_id)
        return True
    except Exception:
        logger.warning("Failed to delete run file %s", path, exc_info=True)
        return False


def _safe_serialize(obj: Any) -> Any:
    """Best-effort conversion of arbitrary objects to JSON-safe values."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(item) for item in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _safe_serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, set):
        return [_safe_serialize(item) for item in sorted(obj)]
    return str(obj)
