"""Tests for pattern-memory config module."""

import os
from pathlib import Path

import pytest

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_config, HAS_COMMON_CONFIG


class TestPatternMemoryConfig:
    """Config should load from env vars, common.config, or defaults."""

    def test_returns_dict_with_required_keys(self):
        config = get_config()
        assert "db_path" in config
        assert "chroma_url" in config
        assert "pid_file" in config
        assert "collection_name" in config

    def test_default_paths_use_home(self):
        config = get_config()
        assert ".pattern-memory" in config["db_path"] or "agent-frameworks" in config["db_path"]

    def test_default_chroma_url(self):
        config = get_config()
        assert config["chroma_url"] == "http://127.0.0.1:8000"

    def test_env_override_db(self, monkeypatch):
        monkeypatch.setenv("PATTERN_MEMORY_DB", "/tmp/test.db")
        config = get_config()
        assert config["db_path"] == "/tmp/test.db"

    def test_env_override_chroma(self, monkeypatch):
        monkeypatch.setenv("PATTERN_MEMORY_CHROMA", "http://remote:9000")
        config = get_config()
        assert config["chroma_url"] == "http://remote:9000"

    def test_env_override_pid(self, monkeypatch):
        monkeypatch.setenv("PATTERN_MEMORY_PID", "/tmp/test.pid")
        config = get_config()
        assert config["pid_file"] == "/tmp/test.pid"

    def test_env_override_collection(self, monkeypatch):
        monkeypatch.setenv("PATTERN_MEMORY_COLLECTION", "my_patterns")
        config = get_config()
        assert config["collection_name"] == "my_patterns"

    def test_common_config_import_status(self):
        # Just verify the flag is a bool
        assert isinstance(HAS_COMMON_CONFIG, bool)
