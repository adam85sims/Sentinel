"""Scenario Editor API — read-write access to scenario YAML files.

Provides endpoints for creating, updating, and deleting scenario YAML files.
This enables the WebUI to edit scenarios directly in the browser.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/scenarios", tags=["scenarios-editor"])

# Resolve project root — same logic as runner_service.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_DEFAULT_SCENARIO_DIR = _PROJECT_ROOT / "examples"


def _resolve_scenario_dir(scenario_dir: str | None = None) -> Path:
    """Resolve scenario directory path."""
    if scenario_dir:
        p = Path(scenario_dir)
        if p.is_absolute():
            return p
        return _PROJECT_ROOT / p
    return _DEFAULT_SCENARIO_DIR


class ScenarioSaveRequest(BaseModel):
    """Request body for saving a scenario."""
    content: str  # Raw YAML content
    filename: str | None = None  # Optional filename override


class ScenarioSaveResponse(BaseModel):
    """Response after saving a scenario."""
    id: str
    filename: str
    message: str


class ScenarioValidateRequest(BaseModel):
    """Request body for validating YAML content."""
    content: str


class ScenarioValidateResponse(BaseModel):
    """Response for YAML validation."""
    valid: bool
    errors: list[str] = []
    parsed: dict | None = None


@router.put("/{scenario_id}", response_model=ScenarioSaveResponse)
async def save_scenario(
    scenario_id: str,
    request: ScenarioSaveRequest,
    api_request: Request = None,
    scenario_dir: str | None = None,
) -> ScenarioSaveResponse:
    """Save (update or create) a scenario YAML file.

    If the scenario file exists, it is overwritten.
    If it doesn't exist, a new file is created.
    """
    resolved_dir = scenario_dir or (getattr(api_request.app.state, "scenario_dir", None) if api_request else None)
    base = _resolve_scenario_dir(resolved_dir)

    # Validate the YAML content first
    try:
        data = yaml.safe_load(request.content)
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="YAML must be a mapping")
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    # Ensure the ID in the YAML matches the URL parameter
    data["id"] = scenario_id

    # Determine filename
    if request.filename:
        filename = request.filename
        if not filename.endswith((".yaml", ".yml")):
            filename += ".yaml"
    else:
        # Find existing file or create new one
        existing = _find_scenario_file(base, scenario_id)
        if existing:
            filename = existing.name
        else:
            filename = f"{scenario_id}.yaml"

    # Serialize back to YAML (with ID enforced)
    content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Write the file
    base.mkdir(parents=True, exist_ok=True)
    filepath = base / filename
    filepath.write_text(content, encoding="utf-8")

    return ScenarioSaveResponse(
        id=scenario_id,
        filename=filename,
        message=f"Scenario '{scenario_id}' saved to {filename}",
    )


@router.post("/validate", response_model=ScenarioValidateResponse)
async def validate_scenario(request: ScenarioValidateRequest) -> ScenarioValidateResponse:
    """Validate YAML content without saving.

    Returns whether the YAML is valid and what it parsed to.
    """
    try:
        data = yaml.safe_load(request.content)
        if data is None:
            return ScenarioValidateResponse(valid=False, errors=["Empty YAML document"])
        if not isinstance(data, dict):
            return ScenarioValidateResponse(
                valid=False,
                errors=[f"Expected a YAML mapping, got {type(data).__name__}"],
            )

        # Check required-ish fields
        errors = []
        if "task" not in data and "description" not in data:
            errors.append("Warning: No 'task' or 'description' field found")

        return ScenarioValidateResponse(
            valid=True,
            errors=errors,
            parsed=data,
        )
    except yaml.YAMLError as e:
        return ScenarioValidateResponse(
            valid=False,
            errors=[str(e)],
        )


@router.delete("/{scenario_id}", status_code=204)
async def delete_scenario(
    scenario_id: str,
    api_request: Request = None,
    scenario_dir: str | None = None,
) -> None:
    """Delete a scenario YAML file."""
    resolved_dir = scenario_dir or (getattr(api_request.app.state, "scenario_dir", None) if api_request else None)
    base = _resolve_scenario_dir(resolved_dir)
    filepath = _find_scenario_file(base, scenario_id)
    if filepath is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")
    filepath.unlink()


def _find_scenario_file(base: Path, scenario_id: str) -> Path | None:
    """Find a scenario file by ID in the given directory."""
    if not base.exists():
        return None
    for ext in (".yaml", ".yml", ".json"):
        candidate = base / f"{scenario_id}{ext}"
        if candidate.exists():
            return candidate
    # Also check if any file has this ID inside it
    for path in base.iterdir():
        if path.suffix in (".yaml", ".yml", ".json") and path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
                if path.suffix == ".json":
                    data = json.loads(text)
                else:
                    data = yaml.safe_load(text) or {}
                if data.get("id") == scenario_id:
                    return path
            except Exception:
                continue
    return None
