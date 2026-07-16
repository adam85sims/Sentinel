"""Runner service — bridges the ScenarioRunner with the WebUI.

Manages scenario discovery from YAML/JSON files, run lifecycle,
and execution in a thread pool to keep the event loop responsive.

Key design decisions:
- Scenario files live under ``examples/`` by default; the path is
  configurable per-request via a ``scenario_dir`` query parameter.
- Each run is executed in a ``concurrent.futures.ThreadPoolExecutor``
  so the async FastAPI event loop stays free for SSE streaming and
  other requests.
- ``RunManager`` is a simple in-memory store; no persistence across
  server restarts. This matches the single-user development use case.
"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from sentinel.runner import ScenarioRunner, SentinelResult, SentinelScenario

# Default scenario directory relative to project root.
# Resolved once at import time by walking up from this file.
# Walk up: services/ -> web/ -> sentinel/ -> src/ -> project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_DEFAULT_SCENARIO_DIR = _PROJECT_ROOT / "examples"

# Thread pool for running scenarios without blocking the event loop.
# Max 4 concurrent scenario runs — keeps the server responsive while
# limiting resource usage for a dev tool.
_EXECUTOR = ThreadPoolExecutor(max_workers=4)


# ── Run state tracking ──


@dataclass
class RunState:
    """Mutable state for a single run in flight.

    The ``event_queue`` allows SSE streams to subscribe to real-time
    progress updates published by ``run_scenario``.
    """

    run_id: str
    scenario_id: str
    scenario_name: str = ""
    status: str = "queued"  # queued | running | completed | failed
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    result: SentinelResult | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RunManager:
    """In-memory registry of active and recent runs.

    Intentionally lightweight — no disk persistence. The dict keeps
    runs accessible for SSE streaming and the GET /api/runs endpoint.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def create_run(self, scenario_id: str, scenario_name: str = "") -> RunState:
        """Allocate a new run with a unique ID and 'queued' status."""
        run_id = str(uuid.uuid4())
        state = RunState(
            run_id=run_id,
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            status="queued",
            started_at=datetime.now(UTC),
        )
        self._runs[run_id] = state
        return state

    def get(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[RunState]:
        """Return all runs, newest started_at first."""
        return sorted(
            self._runs.values(),
            key=lambda r: r.started_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def update_status(self, run_id: str, status: str) -> None:
        state = self._runs.get(run_id)
        if state:
            state.status = status


# Module-level singleton so all routers share the same run store.
run_manager = RunManager()


# ── Scenario discovery ──


def _resolve_scenario_dir(scenario_dir: str | None = None) -> Path:
    """Resolve a scenario directory path.

    If ``scenario_dir`` is an absolute path, use it directly.
    Otherwise treat it as relative to the project root.
    Falls back to ``examples/`` under the project root.
    """
    if scenario_dir:
        p = Path(scenario_dir)
        if p.is_absolute():
            return p
        return _PROJECT_ROOT / p
    return _DEFAULT_SCENARIO_DIR


def discover_scenarios(scenario_dir: str | None = None) -> list[dict[str, Any]]:
    """Scan a directory for .yaml/.yml/.json scenario files.

    Returns a list of dicts with the scenario metadata extracted
    from each file, suitable for serialisation to ScenarioResponse.
    The ``id`` field falls back to the filename stem when not
    specified in the file itself.
    """
    base = _resolve_scenario_dir(scenario_dir)
    if not base.exists():
        return []

    scenarios: list[dict[str, Any]] = []
    for path in sorted(base.iterdir()):
        if path.suffix not in (".yaml", ".yml", ".json"):
            continue
        if path.is_dir():
            continue
        try:
            data = _load_scenario_file(path)
            # Use file stem as id if the YAML doesn't define one
            scenario_id = data.get("id", path.stem)
            scenarios.append(
                {
                    "id": scenario_id,
                    "name": data.get("name", path.stem),
                    "description": data.get("description", ""),
                    "task": data.get("task", ""),
                    "env_config": data.get("env_config", {}),
                    "tags": data.get("tags", []),
                    "timeout_seconds": data.get("timeout_seconds", 30),
                    "chaos_config": data.get("chaos_config", {}),
                    "file_path": str(path),
                }
            )
        except Exception:
            # Skip files that fail to parse — don't crash the list endpoint
            continue
    return scenarios


def get_scenario_detail(
    scenario_dir: str | None, scenario_id: str
) -> dict[str, Any] | None:
    """Load a single scenario by ID from the directory.

    Performs a full scan then filters; acceptable for small dirs.
    Returns None if not found.
    """
    for scenario in discover_scenarios(scenario_dir):
        if scenario["id"] == scenario_id:
            return scenario
    return None


def _load_scenario_file(path: Path) -> dict[str, Any]:
    """Load a YAML or JSON scenario file into a dict."""
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text) or {}
    else:
        import json
        return json.loads(text)


# ── Scenario execution ──


def _build_sentinel_scenario(data: dict[str, Any]) -> SentinelScenario:
    """Convert a raw dict (from YAML) into a SentinelScenario dataclass."""
    return SentinelScenario(
        id=data.get("id", "unknown"),
        name=data.get("name", "Unnamed scenario"),
        description=data.get("description", ""),
        task=data.get("task", ""),
        env_config=data.get("env_config", {}),
        chaos_config=data.get("chaos_config", {}),
        tags=data.get("tags", []),
        timeout_seconds=data.get("timeout_seconds", 30),
    )


async def run_scenario(
    scenario_id: str,
    manager: RunManager,
    scenario_dir: str | None = None,
) -> RunState:
    """Execute a scenario asynchronously via the thread pool.

    This function:
    1. Loads the scenario YAML by ID
    2. Creates a RunState entry
    3. Submits the actual ScenarioRunner.run() to a thread
    4. Updates the RunState on completion/failure

    The caller receives the RunState immediately (status=queued);
    progress updates are pushed to ``state.event_queue``.
    """
    # Look up the scenario file
    detail = get_scenario_detail(scenario_dir, scenario_id)
    if detail is None:
        raise ValueError(f"Scenario '{scenario_id}' not found in {scenario_dir or 'examples/'}")

    state = manager.create_run(
        scenario_id=scenario_id,
        scenario_name=detail.get("name", scenario_id),
    )

    # Build the SentinelScenario dataclass
    sentinel_scenario = _build_sentinel_scenario(detail)

    # Submit the blocking run to the thread pool
    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _EXECUTOR,
        _execute_in_thread,
        state,
        sentinel_scenario,
    )

    return state


def _execute_in_thread(state: RunState, scenario: SentinelScenario) -> None:
    """Blocking scenario execution — runs inside the thread pool.

    This function must NOT use ``await``; it operates synchronously
    inside the executor thread.
    """
    state.status = "running"
    runner = ScenarioRunner()

    try:
        # Run without an agent_fn — the runner handles None gracefully
        result = runner.run(scenario, agent_fn=None)
        state.result = result
        state.status = "completed" if result.passed else "failed"
    except Exception as exc:
        state.status = "failed"
        # Create a minimal result so the API still has something to return
        state.result = SentinelResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            passed=False,
            error=f"Run failed: {exc}",
        )
    finally:
        state.completed_at = datetime.now(UTC)
        # Push a completion event so any connected SSE stream knows
        try:
            state.event_queue.put_nowait(
                {"type": "completed", "status": state.status}
            )
        except asyncio.QueueFull:
            pass
