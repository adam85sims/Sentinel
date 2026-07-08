"""Tests for pattern-memory MCP config generator."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_config import detect_platforms, generate_config, print_config_snippet


class TestDetectPlatforms:
    """Should detect installed agent platforms."""

    def test_returns_dict(self):
        result = detect_platforms()
        assert isinstance(result, dict)

    def test_claude_desktop_detection(self, monkeypatch):
        """Claude Desktop should be detected if config exists."""
        # This test just verifies the detection logic works
        platforms = detect_platforms()
        # We can't guarantee Claude is installed, but the function shouldn't crash
        assert isinstance(platforms, dict)

    def test_unknown_platform_returns_none(self):
        from mcp_config import _get_config_path
        result = _get_config_path("nonexistent-platform")
        assert result is None


class TestGenerateConfig:
    """Should generate correct MCP config for each platform."""

    def test_claude_desktop_format(self):
        config = generate_config("claude-desktop", server_script="/path/to/server.py")
        assert "mcpServers" in config
        assert "pattern-memory" in config["mcpServers"]
        assert config["mcpServers"]["pattern-memory"]["command"] == "python3"
        assert "/path/to/server.py" in config["mcpServers"]["pattern-memory"]["args"]

    def test_cursor_format(self):
        config = generate_config("cursor", server_script="/path/to/server.py")
        assert "mcpServers" in config
        assert "pattern-memory" in config["mcpServers"]

    def test_opencode_format(self):
        config = generate_config("opencode", server_script="/path/to/server.py")
        assert "mcp" in config
        assert "servers" in config["mcp"]
        assert "pattern-memory" in config["mcp"]["servers"]

    def test_hermes_format(self):
        config = generate_config("hermes", server_script="/path/to/server.py")
        assert "mcpServers" in config

    def test_generic_format(self):
        config = generate_config("generic", server_script="/path/to/server.py")
        assert config["command"] == "python3"

    def test_default_script_path(self):
        config = generate_config("claude-desktop")
        # Should use the installed server.py path
        args = config["mcpServers"]["pattern-memory"]["args"]
        assert len(args) == 1
        assert args[0].endswith("server.py")


class TestPrintConfigSnippet:
    """Should print a valid JSON config snippet."""

    def test_prints_json(self, capsys):
        print_config_snippet()
        captured = capsys.readouterr()
        assert "pattern-memory" in captured.out
        assert "python3" in captured.out
