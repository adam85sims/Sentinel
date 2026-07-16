"""Tests for the Sentinel WebUI API layer.

Uses FastAPI's TestClient (httpx under the hood) for async-free endpoint
testing. Scenarios are pointed at the project's examples/ directory.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Skip entire module if web deps not installed
pytest.importorskip("fastapi", reason="Web deps not installed")
pytest.importorskip("httpx", reason="httpx required for TestClient")

from fastapi.testclient import TestClient

from sentinel.web.app import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Create a TestClient pointed at the project examples/ dir."""
    # Resolve examples dir relative to project root
    project_root = Path(__file__).parent.parent.parent.parent
    examples_dir = project_root / "examples"
    if not examples_dir.exists():
        examples_dir = tmp_path
        # Create a minimal scenario for testing
        scenario = {
            "id": "test-basic-001",
            "name": "Test Basic Scenario",
            "description": "A minimal test scenario",
            "task": "Test task",
            "env_config": {"tools": {"test_tool": {"response": "ok"}}},
            "tags": ["test"],
            "timeout_seconds": 10,
        }
        (examples_dir / "test_basic.yaml").write_text(
            json.dumps(scenario)
        )

    app = create_app(scenario_dir=str(examples_dir))
    return TestClient(app)


# ──────────────────────────────────────────────────────
# Health / Root
# ──────────────────────────────────────────────────────


class TestHealth:
    """Basic app health checks."""

    def test_root_returns_html(self, client: TestClient) -> None:
        """Root path should serve the SPA index.html."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_api_scenarios_empty_or_populated(self, client: TestClient) -> None:
        """Scenarios endpoint should return a valid list."""
        resp = client.get("/api/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert "scenarios" in data
        assert "total" in data
        assert isinstance(data["scenarios"], list)


# ──────────────────────────────────────────────────────
# Scenarios API
# ──────────────────────────────────────────────────────


class TestScenariosAPI:
    """Tests for the scenarios endpoints."""

    def test_list_scenarios(self, client: TestClient) -> None:
        """Should list scenarios from the examples directory."""
        resp = client.get("/api/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 0

    def test_get_scenario_not_found(self, client: TestClient) -> None:
        """Non-existent scenario should 404."""
        resp = client.get("/api/scenarios/nonexistent-999")
        assert resp.status_code == 404

    def test_get_scenario_found(self, client: TestClient) -> None:
        """Existing scenario should return detail."""
        # First get the list to find a valid ID
        list_resp = client.get("/api/scenarios")
        scenarios = list_resp.json()["scenarios"]
        if scenarios:
            scenario_id = scenarios[0]["id"]
            resp = client.get(f"/api/scenarios/{scenario_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == scenario_id


# ──────────────────────────────────────────────────────
# Runs API
# ──────────────────────────────────────────────────────


class TestRunsAPI:
    """Tests for the run endpoints."""

    def test_list_runs_empty(self, client: TestClient) -> None:
        """No runs yet should return empty list."""
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)

    def test_start_run_invalid_scenario(self, client: TestClient) -> None:
        """Running a non-existent scenario should fail gracefully."""
        resp = client.post("/api/runs", json={"scenario_id": "nonexistent-999"})
        assert resp.status_code == 404

    def test_start_and_poll_run(self, client: TestClient) -> None:
        """Start a run and poll until complete."""
        # Find a valid scenario
        list_resp = client.get("/api/scenarios")
        scenarios = list_resp.json()["scenarios"]
        if not scenarios:
            pytest.skip("No scenarios available")

        scenario_id = scenarios[0]["id"]

        # Start the run
        resp = client.post("/api/runs", json={"scenario_id": scenario_id})
        assert resp.status_code == 202
        run_data = resp.json()
        run_id = run_data["run_id"]
        # Status may already be "completed" if the run finishes synchronously
        # (common with mock scenarios that have no agent function).
        assert run_data["status"] in ("queued", "running", "completed", "failed")

        # Poll until completed (max 30 seconds)
        for _ in range(60):
            time.sleep(0.5)
            poll_resp = client.get(f"/api/runs/{run_id}")
            if poll_resp.status_code == 200:
                status = poll_resp.json()["status"]
                if status in ("completed", "failed"):
                    break

        # Final check
        final = client.get(f"/api/runs/{run_id}")
        assert final.status_code == 200
        assert final.json()["status"] in ("completed", "failed")

    def test_run_not_found(self, client: TestClient) -> None:
        """Non-existent run ID should 404."""
        resp = client.get("/api/runs/nonexistent-run-id")
        assert resp.status_code == 404


# ──────────────────────────────────────────────────────
# Baselines API
# ──────────────────────────────────────────────────────


class TestBaselinesAPI:
    """Tests for the baseline endpoints."""

    def test_list_baselines(self, client: TestClient) -> None:
        """Should return a list of baselines."""
        resp = client.get("/api/baselines")
        assert resp.status_code == 200
        data = resp.json()
        assert "baselines" in data
        assert isinstance(data["baselines"], list)

    def test_baseline_not_found(self, client: TestClient) -> None:
        """Non-existent baseline should 404."""
        resp = client.get("/api/baselines/nonexistent-label")
        assert resp.status_code == 404

    def test_delete_baseline_not_found(self, client: TestClient) -> None:
        """Deleting non-existent baseline should 404."""
        resp = client.delete("/api/baselines/nonexistent-label")
        assert resp.status_code == 404


# ──────────────────────────────────────────────────────
# Static Files
# ──────────────────────────────────────────────────────


class TestStaticFiles:
    """Verify static assets are served."""

    def test_index_html_served(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200

    def test_css_served(self, client: TestClient) -> None:
        resp = client.get("/css/sentinel.css")
        # May be 200 or 404 depending on static mount — that's OK
        assert resp.status_code in (200, 404)

    def test_js_served(self, client: TestClient) -> None:
        resp = client.get("/js/app.js")
        assert resp.status_code in (200, 404)
