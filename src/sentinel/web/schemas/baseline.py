"""Pydantic models for the Baseline API.

Covers listing, inspecting, and diffing recorded baselines.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BaselineResponse(BaseModel):
    """Summary of a single recorded baseline."""

    model_config = ConfigDict(from_attributes=True)

    label: str
    timestamp: datetime | None = None
    git_sha: str = ""
    git_branch: str = ""
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    scenario_count: int = 0
    pass_count: int = 0
    fail_count: int = 0


class BaselineListResponse(BaseModel):
    """List of baselines returned by the API."""

    baselines: list[BaselineResponse] = Field(default_factory=list)
    total: int = 0


class DiffDelta(BaseModel):
    """Per-scenario delta between two baselines."""

    scenario_id: str
    scenario_name: str
    delta: str  # ResultDelta enum value (new_pass, new_fail, still_pass, etc.)
    baseline_passed: bool | None = None
    current_passed: bool | None = None
    new_failures: list[str] = Field(default_factory=list)
    fixed_assertions: list[str] = Field(default_factory=list)


class DiffResponse(BaseModel):
    """Regression diff between two baselines."""

    verdict: str  # "PASS" | "FAIL" | "WARN"
    summary: str = ""
    baseline_label: str = ""
    current_label: str = ""
    deltas: list[DiffDelta] = Field(default_factory=list)
