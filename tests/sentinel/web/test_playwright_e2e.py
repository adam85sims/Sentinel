"""E2E browser tests for the Sentinel WebUI.

Requires pytest-playwright and playwright to be installed.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip this module if playwright is not installed
pytest.importorskip("playwright", reason="playwright library not installed")

import uvicorn
from playwright.sync_api import Page

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
    app = create_app(scenario_dir=str(examples_dir))
    port = get_free_port()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    temp_config = tmp_path_factory.mktemp("config") / "sentinel-web.yaml"

    thread = threading.Thread(target=server.run, daemon=True)

    # Patch configuration file to use an isolated location during testing
    with patch("sentinel.web.api.models._CONFIG_FILE", temp_config):
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
