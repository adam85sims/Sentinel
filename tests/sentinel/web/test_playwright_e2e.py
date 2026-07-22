"""E2E browser tests for the Sentinel WebUI.

Requires pytest-playwright and playwright to be installed.
"""

from __future__ import annotations

import socket
import threading
import time
from unittest.mock import patch

import pytest

# Skip this module if playwright is not installed
pytest.importorskip("playwright", reason="playwright library not installed")

import uvicorn
from playwright.sync_api import Page

from common.models import AuditResult, Verdict
from sentinel.web.app import create_app


def get_free_port() -> int:
    """Find a free TCP port."""
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server_url(tmp_path_factory):
    """Fixture to run uvicorn server in a background thread."""
    examples_dir = tmp_path_factory.mktemp("examples")

    # Pre-populate examples directory with E2E scenarios
    scenario_1 = """id: test-scenario-1
name: E2E Scenario One
description: A basic scenario for Playwright testing
task: Do task one
tags:
  - basic
  - e2e
timeout_seconds: 10
"""
    scenario_2 = """id: test-scenario-2
name: E2E Scenario Two
description: A chaos scenario for Playwright testing
task: Do task two
tags:
  - chaos
  - e2e
timeout_seconds: 15
"""
    (examples_dir / "test_scenario_1.yaml").write_text(scenario_1, encoding="utf-8")
    (examples_dir / "test_scenario_2.yaml").write_text(scenario_2, encoding="utf-8")

    app = create_app(scenario_dir=str(examples_dir))
    port = get_free_port()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)

    temp_config = tmp_path_factory.mktemp("config") / "sentinel-web.yaml"

    thread = threading.Thread(target=server.run, daemon=True)

    # Mock governance run_audit to avoid running pytest recursively during E2E tests
    mock_audit_result = AuditResult(
        verdict=Verdict.PASS,
        summary="E2E Mock Audit Passed",
        discrepancies=[]
    )

    # Patch configuration file and run_audit during testing
    with patch("sentinel.web.api.models._CONFIG_FILE", temp_config), \
         patch("sentinel.web.api.governance.run_audit", return_value=mock_audit_result):
        thread.start()
        time.sleep(1.0)  # wait for uvicorn to bind
        yield f"http://127.0.0.1:{port}"
        server.should_exit = True
        thread.join(timeout=2.0)


def test_add_and_test_lm_studio_endpoint(server_url: str, page: Page) -> None:
    """E2E test: navigates to settings, adds LM Studio, and verifies it."""
    # Navigate to Settings page
    page.goto(f"{server_url}/#/settings")
    page.wait_for_selector("#add-endpoint-btn")

    # Click + Add Endpoint
    page.click("#add-endpoint-btn")
    page.wait_for_selector("#endpoint-modal:not(.hidden)")

    # Fill in the form
    page.select_option("#ep-provider", "lm_studio")
    page.fill("#ep-model", "google/gemma-4-12b")
    page.fill("#ep-base-url", "http://192.168.1.107:1234")

    # Click Save
    page.click("#save-endpoint-btn")

    # Verify listing in settings page
    page.wait_for_selector(".endpoint-card")
    card = page.locator(".endpoint-card").first
    assert "LM STUDIO" in card.locator(".endpoint-provider").text_content()
    assert "google/gemma-4-12b" in card.locator(".endpoint-model").text_content()
    assert "http://192.168.1.107:1234" in card.locator(".text-muted").text_content()

    # Click Test
    test_btn = card.locator(".test-endpoint-btn")
    assert test_btn.is_visible()
    test_btn.click()

    # Wait for the toast container to show toast notifications
    page.wait_for_selector("#toast-container")


def test_dashboard_loads_and_shows_trend_chart(server_url: str, page: Page) -> None:
    """Verify the dashboard page loads and displays the SVG trend chart."""
    page.goto(f"{server_url}/#/")
    page.wait_for_selector(".stat-card")

    # Assert that some stat card exists (e.g. Total Runs, Pass Rate)
    assert page.locator(".stat-card").count() > 0

    # Assert trend chart SVG exists or svg tag is present
    chart = page.locator(".trend-chart-container svg")
    assert chart.is_visible() or page.locator("svg").count() > 0


def test_scenario_list_with_tag_filtering(server_url: str, page: Page) -> None:
    """Verify that scenarios page lists items and filtering by tag chip works."""
    page.goto(f"{server_url}/#/scenarios")
    page.wait_for_selector(".card-clickable")

    # Both test scenarios should be displayed
    assert page.locator(".card-clickable").count() >= 2

    # Click on the "chaos" tag filter chip
    page.click(".tag-filter[data-tag='chaos']")

    # Should only show scenario two
    assert page.locator(".card-clickable").count() == 1
    assert "E2E Scenario Two" in page.locator(".card-clickable").first.locator(".card-title").text_content()


def test_scenario_editor_saves_yaml(server_url: str, page: Page) -> None:
    """Verify that scenario editor loads, allows typing, validates, and saves."""
    page.goto(f"{server_url}/#/scenarios/__new__")
    page.wait_for_selector("#editor-yaml")

    new_yaml = """id: e2e-scenario-saved
name: Saved E2E Scenario
description: Created during playwright tests
task: Do something cool
tags:
  - test-saved
timeout_seconds: 22
"""
    # Fill in the textarea
    page.fill("#editor-yaml", "")
    page.fill("#editor-yaml", new_yaml)

    # Click Validate
    page.click("#editor-validate-btn")
    page.wait_for_selector("#toast-container")

    # Click Save
    page.click("#editor-save-btn")

    # Should redirect to details page of the saved scenario
    page.wait_for_url("**/#/scenarios/e2e-scenario-saved")
    page.wait_for_selector("#scenario-detail-content")

    assert "Saved E2E Scenario" in page.locator(".page-title").text_content()


def test_chaos_builder_renders_injectors_and_previews_yaml(server_url: str, page: Page) -> None:
    """Verify that the chaos builder form renders properly and updates the YAML preview."""
    page.goto(f"{server_url}/#/chaos")

    # Wait until preset select has options loaded (using state="attached" because options may be hidden)
    page.wait_for_selector("#chaos-preset-select option:has-text('Traffic Spike')", state="attached")

    # Change preset selection
    page.select_option("#chaos-preset-select", label="Traffic Spike")

    # Wait for the async YAML preview to be generated and rendered
    page.wait_for_selector("#chaos-yaml-preview code")

    # Check that preview YAML contains the selected presets or fields
    preview = page.locator("#chaos-yaml-preview").text_content()
    assert "tool_failure" in preview or "probability" in preview or "failures" in preview



def test_baseline_comparison_works(server_url: str, page: Page) -> None:
    """Verify baselines page lists baselines if present."""
    page.goto(f"{server_url}/#/baselines")
    page.wait_for_selector(".page-title")

    # Even if empty, it should render either empty state or list
    assert page.locator(".page-title").text_content().strip() == "Baselines"


def test_theme_toggle(server_url: str, page: Page) -> None:
    """Verify clicking theme toggle switches data-theme attribute on root."""
    page.goto(f"{server_url}/#/")
    page.wait_for_selector("#theme-toggle")

    # Initial state should be dark (no data-theme="light")
    is_light_initial = page.evaluate("document.documentElement.getAttribute('data-theme') === 'light'")

    # Click theme toggle
    page.click("#theme-toggle")

    # Should toggle to light mode
    is_light_after = page.evaluate("document.documentElement.getAttribute('data-theme') === 'light'")
    assert is_light_after != is_light_initial

    # Click again to revert
    page.click("#theme-toggle")
    is_light_revert = page.evaluate("document.documentElement.getAttribute('data-theme') === 'light'")
    assert is_light_revert == is_light_initial


def test_keyboard_shortcuts(server_url: str, page: Page) -> None:
    """Verify keyboard shortcuts (? to open help, ESC to close, g+s to navigate)."""
    page.goto(f"{server_url}/#/")
    page.wait_for_selector("#theme-toggle")

    # Press '?' to trigger help modal
    page.keyboard.press("?")
    page.wait_for_selector("#shortcut-help-overlay")
    assert page.locator("#shortcut-help-overlay").is_visible()

    # Press 'Escape' to close it
    page.keyboard.press("Escape")
    page.wait_for_selector("#shortcut-help-overlay", state="hidden")

    # Press 'g' then 's' to navigate to scenarios page
    page.keyboard.press("g")
    page.keyboard.press("s")

    page.wait_for_url("**/#/scenarios")
    page.wait_for_selector(".card-clickable")
    assert page.locator(".card-clickable").count() > 0


def test_governance_page(server_url: str, page: Page) -> None:
    """Verify that governance page loads compliance scorecard and allows triggering audit."""
    page.goto(f"{server_url}/#/governance")
    page.wait_for_selector("#gov-run-audit-btn")

    # Title check
    assert "Governance" in page.locator(".page-title").text_content()

    # Scorecard widgets should be visible
    assert page.locator(".gov-scorecard").is_visible()

    # Click run audit
    page.click("#gov-run-audit-btn")
    page.wait_for_selector("#toast-container")
