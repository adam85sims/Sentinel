"""Pydantic models for the Run API.

Covers starting, listing, and inspecting scenario runs — including
streaming results via SSE and detailed assertion/trace breakdowns.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── Assertion-level detail ──


class AssertionResult(BaseModel):
    """Outcome of a single assertion within a run."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    passed: bool
    error_message: str | None = None
    duration_ms: float = 0.0


# ── Trace summary ──


class TraceSummary(BaseModel):
    """High-level summary of the agent execution trace.

    Provides aggregated metrics without the full step-by-step detail
    (which lives in the serialized trace stored alongside the result).
    """

    model_config = ConfigDict(from_attributes=True)

    total_steps: int = 0
    total_tool_calls: int = 0
    total_duration_ms: float = 0.0
    tool_names_called: list[str] = Field(default_factory=list)
    failed_tool_calls: int = 0
    errors: int = 0
    state_changes: int = 0


# ── Run result ──


class RunResult(BaseModel):
    """Outcome of a completed scenario run.

    Wraps assertion results and a trace summary into a flat,
    JSON-serialisable shape for the API.
    """

    model_config = ConfigDict(from_attributes=True)

    passed: bool = False
    duration_ms: float = 0.0
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    error: str | None = None
    trace_summary: TraceSummary | None = None


# ── Run request / response ──


class RunRequest(BaseModel):
    """POST body to start a new scenario run."""

    scenario_id: str
    model_endpoint: str | None = None


class RunResponse(BaseModel):
    """Returned immediately when a run is accepted (HTTP 202)."""

    run_id: str
    status: str  # "queued" | "running" | "completed" | "failed"
    scenario_id: str
    scenario_name: str
    started_at: datetime | None = None


class RunDetailResponse(BaseModel):
    """Full detail of a run, including its result when available."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str
    status: str
    scenario_id: str
    scenario_name: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: RunResult | None = None


class RunListResponse(BaseModel):
    """Paginated list of runs."""
    runs: list[RunDetailResponse] = Field(default_factory=list)
    total: int = 0


class BatchRunRequest(BaseModel):
    """Request body to start multiple scenario runs."""
    scenario_ids: list[str] = Field(default_factory=list)
    tag: str | None = None  # Filter scenarios by tag
    model_endpoint: str | None = None
    max_runs: int = 20  # Safety cap


class BatchRunResponse(BaseModel):
    """Response for batch run submission."""
    run_ids: list[str] = Field(default_factory=list)
    total_started: int = 0
    total_requested: int = 0
