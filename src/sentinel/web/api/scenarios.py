"""Scenario API router.

Endpoints for listing and inspecting test scenario files.
Scenarios are loaded from YAML/JSON files on disk — the router
does NOT store them; it's a read-only view into the filesystem.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from sentinel.web.schemas.scenario import (
    ScenarioListResponse,
    ScenarioResponse,
)
from sentinel.web.services.runner_service import (
    discover_scenarios,
    get_scenario_detail,
)

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


@router.get("", response_model=ScenarioListResponse)
async def list_scenarios(
    scenario_dir: str | None = Query(
        default=None,
        description="Directory containing scenario YAML/JSON files. "
        "Relative paths resolve from project root; defaults to 'examples/'.",
    ),
) -> ScenarioListResponse:
    """List all scenarios discovered in the given directory.

    Scans for ``.yaml``, ``.yml``, and ``.json`` files, parses each,
    and returns their metadata.  Files that fail to parse are silently
    skipped so a single bad file doesn't break the list.
    """
    items = discover_scenarios(scenario_dir)
    return ScenarioListResponse(
        scenarios=[ScenarioResponse(**s) for s in items],
        total=len(items),
    )


@router.get("/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(
    scenario_id: str,
    scenario_dir: str | None = Query(
        default=None,
        description="Directory containing scenario files.",
    ),
) -> ScenarioResponse:
    """Get details for a single scenario by its ID.

    The ``id`` is the ``id`` field from the YAML file, or the
    filename stem when no ``id`` is defined.
    """
    detail = get_scenario_detail(scenario_dir, scenario_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"Scenario '{scenario_id}' not found",
        )
    return ScenarioResponse(**detail)
