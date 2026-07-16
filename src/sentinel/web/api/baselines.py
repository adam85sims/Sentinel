"""Baseline API router.

Endpoints for listing, inspecting, deleting, and diffing recorded baselines.
Baselines are stored on disk by the sentinel.baseline module; this router
is a thin API layer over those operations.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from sentinel.web.schemas.baseline import (
    BaselineListResponse,
    BaselineResponse,
    DiffResponse,
)
from sentinel.web.services.baseline_service import (
    compute_diff,
    delete_baseline,
    get_baseline,
    list_all_baselines,
)

router = APIRouter(prefix="/api/baselines", tags=["baselines"])


@router.get("", response_model=BaselineListResponse)
async def list_baselines() -> BaselineListResponse:
    """List all recorded baselines, newest first."""
    return list_all_baselines()


@router.get("/{label}", response_model=BaselineResponse)
async def get_baseline_detail(label: str) -> BaselineResponse:
    """Get details for a single baseline by label.

    The ``label`` is the name under ``.sentinel/baselines/``
    (e.g. ``v1.2.3``, ``main-abc1234``).
    """
    try:
        return get_baseline(label)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{label}", status_code=204)
async def delete_baseline_endpoint(label: str) -> None:
    """Delete a baseline by label.

    Returns HTTP 204 No Content on success, 404 if not found.
    """
    deleted = delete_baseline(label)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Baseline '{label}' not found",
        )


@router.get("/{label1}/diff/{label2}", response_model=DiffResponse)
async def diff_baselines(label1: str, label2: str) -> DiffResponse:
    """Compute a regression diff between two baselines.

    ``label1`` is the baseline (older/reference) and ``label2`` is
    the current (newer/test) run.  Returns per-scenario deltas and
    an overall verdict.
    """
    try:
        return compute_diff(label1, label2)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
