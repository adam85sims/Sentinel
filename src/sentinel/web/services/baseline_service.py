"""Baseline service — thin wrapper around sentinel.baseline.

Provides async-friendly helpers that the API routers call.
All heavy lifting is done by the sentinel.baseline module; this
service just handles path resolution and data translation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sentinel.baseline import (
    delete_baseline as _delete_baseline,
)
from sentinel.baseline import (
    list_baselines as _list_baselines,
)
from sentinel.baseline import (
    load_baseline as _load_baseline,
)
from sentinel.reporting import build_regression_report
from sentinel.web.schemas.baseline import (
    BaselineListResponse,
    BaselineResponse,
    DiffDelta,
    DiffResponse,
)

# Resolve project root for baseline storage.
# Walk up: services/ -> web/ -> sentinel/ -> src/ -> project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


def list_all_baselines() -> BaselineListResponse:
    """Return all recorded baselines as BaselineResponse objects."""
    labels = _list_baselines(str(_PROJECT_ROOT))
    baselines: list[BaselineResponse] = []

    for label in labels:
        try:
            meta, results = _load_baseline(label, str(_PROJECT_ROOT))
            baselines.append(
                BaselineResponse(
                    label=meta.label,
                    timestamp=datetime.fromtimestamp(meta.timestamp, tz=UTC)
                    if meta.timestamp
                    else None,
                    git_sha=meta.git_sha,
                    git_branch=meta.git_branch,
                    tags=meta.tags,
                    description=meta.description,
                    scenario_count=meta.scenario_count,
                    pass_count=meta.pass_count,
                    fail_count=meta.fail_count,
                )
            )
        except Exception:
            # If a baseline is corrupted, include it with minimal info
            baselines.append(BaselineResponse(label=label))

    return BaselineListResponse(baselines=baselines, total=len(baselines))


def get_baseline(label: str) -> BaselineResponse:
    """Load and return a single baseline by label.

    Raises FileNotFoundError if the baseline doesn't exist.
    """
    meta, _results = _load_baseline(label, str(_PROJECT_ROOT))
    return BaselineResponse(
        label=meta.label,
        timestamp=datetime.fromtimestamp(meta.timestamp, tz=UTC)
        if meta.timestamp
        else None,
        git_sha=meta.git_sha,
        git_branch=meta.git_branch,
        tags=meta.tags,
        description=meta.description,
        scenario_count=meta.scenario_count,
        pass_count=meta.pass_count,
        fail_count=meta.fail_count,
    )


def delete_baseline(label: str) -> bool:
    """Delete a baseline by label. Returns True if deleted."""
    return _delete_baseline(label, str(_PROJECT_ROOT))


def compute_diff(label1: str, label2: str) -> DiffResponse:
    """Compute a regression diff between two baselines.

    ``label1`` is treated as the baseline (older/reference),
    ``label2`` as the current (newer/test) run.

    Returns a DiffResponse with per-scenario deltas and an
    overall verdict (PASS/FAIL/WARN).
    """
    meta1, results1 = _load_baseline(label1, str(_PROJECT_ROOT))
    meta2, results2 = _load_baseline(label2, str(_PROJECT_ROOT))

    report = build_regression_report(
        baseline_results=results1,
        current_results=results2,
        baseline_label=label1,
        current_label=label2,
    )

    # Translate ScenarioDelta objects to our API schema
    deltas = [
        DiffDelta(
            scenario_id=d.scenario_id,
            scenario_name=d.scenario_name,
            delta=d.delta.value,
            baseline_passed=d.baseline_passed,
            current_passed=d.current_passed,
            new_failures=d.new_failures,
            fixed_assertions=d.fixed_assertions,
        )
        for d in report.deltas
    ]

    return DiffResponse(
        verdict=report.verdict,
        summary=report.summary,
        baseline_label=report.baseline_label,
        current_label=report.current_label,
        deltas=deltas,
    )
