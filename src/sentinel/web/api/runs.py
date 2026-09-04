"""Run API router.

Endpoints for starting, listing, inspecting, and streaming scenario runs.
POST /api/runs starts a new run (returns 202 Accepted) and the SSE
endpoint streams real-time progress to connected clients.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from sentinel.web.schemas.run import (
    BatchRunRequest,
    BatchRunResponse,
    RunDetailResponse,
    RunListResponse,
    RunRequest,
    RunResponse,
    RunResult,
)
from sentinel.web.services.runner_service import run_manager, run_scenario
from sentinel.web.services.stream_service import (
    get_events,
    publish_run_event,
    register_run,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", response_model=RunResponse, status_code=202)
async def start_run(request: RunRequest, api_request: Request) -> RunResponse:
    """Start a new scenario run.

    Accepts a ``scenario_id`` and optional ``model_endpoint``.
    Returns HTTP 202 with a ``RunResponse`` containing the run ID.
    The actual execution happens in the background via a thread pool.
    """
    # Register an SSE event queue for this run
    # (we don't know the run_id yet — run_scenario creates it,
    #  so we pre-create with a placeholder and let the service fill it)
    dir_to_use = getattr(api_request.app.state, "scenario_dir", None)
    try:
        state = await run_scenario(
            scenario_id=request.scenario_id,
            manager=run_manager,
            scenario_dir=dir_to_use,
            model_endpoint_id=request.model_endpoint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Now register the SSE queue with the real run_id
    register_run(state.run_id)

    # Publish an initial "started" event
    publish_run_event(
        state.run_id,
        "started",
        {
            "run_id": state.run_id,
            "scenario_id": state.scenario_id,
            "scenario_name": state.scenario_name,
        },
    )

    return RunResponse(
        run_id=state.run_id,
        status=state.status,
        scenario_id=state.scenario_id,
        scenario_name=state.scenario_name,
        started_at=state.started_at,
    )


@router.post("/batch", response_model=BatchRunResponse, status_code=202)
async def start_batch_runs(request: BatchRunRequest, api_request: Request) -> BatchRunResponse:
    """Start multiple scenario runs in sequence.

    Accepts a list of scenario IDs and runs them one after another.
    Returns the list of run IDs created.
    """
    from sentinel.web.services.runner_service import discover_scenarios

    dir_to_use = getattr(api_request.app.state, "scenario_dir", None)

    # If a tag is provided, filter scenarios by tag
    scenario_ids = request.scenario_ids or []
    if request.tag:
        all_scenarios = discover_scenarios(dir_to_use)
        tagged = [s["id"] for s in all_scenarios if request.tag in s.get("tags", [])]
        scenario_ids = tagged

    if not scenario_ids:
        raise HTTPException(status_code=400, detail="No scenarios specified or found for the given tag")

    run_ids = []
    for sid in scenario_ids[:request.max_runs]:  # Cap at max_runs
        try:
            state = await run_scenario(
                scenario_id=sid,
                manager=run_manager,
                scenario_dir=dir_to_use,
                model_endpoint_id=request.model_endpoint,
            )
            register_run(state.run_id)
            publish_run_event(state.run_id, "started", {
                "run_id": state.run_id,
                "scenario_id": sid,
                "scenario_name": state.scenario_name,
            })
            run_ids.append(state.run_id)
        except (ValueError, Exception):
            continue  # Skip scenarios that fail to start

    return BatchRunResponse(
        run_ids=run_ids,
        total_started=len(run_ids),
        total_requested=len(scenario_ids),
    )


@router.get("", response_model=RunListResponse)
async def list_runs() -> RunListResponse:
    """List all runs, most recent first.

    Includes both in-progress and completed runs.
    """
    runs = run_manager.list_runs()
    items = [_state_to_detail(r) for r in runs]
    return RunListResponse(runs=items, total=len(items))


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(run_id: str) -> RunDetailResponse:
    """Get detailed information about a specific run.

    Returns the full run state including the result (if completed).
    """
    state = run_manager.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return _state_to_detail(state)


@router.get("/{run_id}/trace")
async def get_run_trace(run_id: str):
    """Get the trace for a specific run.

    Returns the full AgentTrace as a dictionary, including tool calls,
    state changes, errors, and timing information.
    """
    state = run_manager.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if state.result is None or state.result.trace is None:
        raise HTTPException(status_code=404, detail=f"Trace not available for run '{run_id}'")
    trace_dict = state.result.trace.to_dict()
    # Include step details (input/output) for the frontend timeline
    trace_dict["steps"] = [
        {
            "step_id": s.step_id,
            "action": s.action.value if hasattr(s.action, "value") else str(s.action),
            "input": s.input,
            "output": s.output,
            "duration_ms": s.duration_ms,
            "error": str(s.error) if s.error else None,
        }
        for s in state.result.trace.steps
    ]
    return trace_dict


@router.get("/{run_id}/stream")
async def stream_run(run_id: str):
    """SSE endpoint streaming real-time events for a run.

    Clients connect to this endpoint and receive server-sent events
    as the scenario executes.  Events include:
    - ``started``: run has been accepted
    - ``progress``: intermediate status updates
    - ``completed``: run finished (includes final result)

    The stream ends when the run completes or the client disconnects.
    """
    state = run_manager.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    # Ensure the SSE queue exists for this run
    register_run(run_id)

    async def event_generator():
        """Yields SSE events from the run's event queue."""
        try:
            async for event_str in get_events(run_id):
                yield event_str
        finally:
            # Don't unregister here — the run might reconnect.
            # Cleanup happens when the run entry is garbage-collected.
            pass

    return EventSourceResponse(event_generator())


# ── Helpers ──


def _state_to_detail(state) -> RunDetailResponse:
    """Convert a RunState dataclass to the API response model."""
    result = None
    if state.result is not None:
        r = state.result
        # Build trace summary from the SentinelResult's trace
        trace_summary = None
        if r.trace:
            trace_summary = {
                "total_steps": r.trace.total_steps,
                "total_tool_calls": r.trace.total_tool_calls,
                "total_duration_ms": r.trace.total_duration_ms,
                "tool_names_called": r.trace.tool_names_called,
                "failed_tool_calls": len(r.trace.failed_tool_calls),
                "errors": len(r.trace.errors),
                "state_changes": len(r.trace.state_changes),
            }
        # Map assertion results to API schema
        assertion_results = [
            {
                "name": a.assertion_name,
                "passed": a.passed,
                "error_message": a.error_message,
                "duration_ms": a.duration_ms,
            }
            for a in r.assertion_results
        ]
        result = RunResult(
            passed=r.passed,
            duration_ms=r.duration_ms,
            assertion_results=assertion_results,
            error=r.error,
            trace_summary=trace_summary,
        )

    return RunDetailResponse(
        run_id=state.run_id,
        status=state.status,
        scenario_id=state.scenario_id,
        scenario_name=state.scenario_name,
        started_at=state.started_at,
        completed_at=state.completed_at,
        result=result,
    )
