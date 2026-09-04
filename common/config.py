"""Layered configuration loading for agent-frameworks.

Priority order (highest wins):
  1. Environment variables (AGENT_FW_<SECTION>_<KEY>)
  2. Project-level agent-frameworks.yaml
  3. Built-in safe defaults

Usage:
    from common.config import load_config, Config

    # Simple: get a dict
    config = load_config(root=Path("."))
    gov_src = config["governance"]["src_dir"]

    # Object-oriented: get a Config instance
    cfg = Config(root=Path("."))
    gov_src = cfg.get("governance", "src_dir")
"""

import copy
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Graceful YAML import — config works without it, just can't read .yaml files
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ─── Default configuration ────────────────────────────────────────
# These are the safe, generic defaults. Projects override via yaml or env.

DEFAULTS = {
    "governance": {
        "src_dir": "src",
        "readme_path": "README.md",
        "mcp_server_file": None,
        "diary_dir": "updates",
        "test_dir": "tests",
        "test_command": [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        "test_cwd": ".",
        "source_file_pattern": "**/*.py",
    },
    "pattern_memory": {
        "sqlite_path": "~/.agent-frameworks/pattern-memory.db",
        "chroma_path": "~/.agent-frameworks/chromadb",
        "singleton_pid": "~/.agent-frameworks/pattern-memory.pid",
    },
    "automation": {
        "exit_conditions": {
            "max_items_per_session": 3,
            "context_usage_limit": 0.6,
            "max_consecutive_failures": 3,
            "require_governance_pass": True,
        },
        "work_queue": {
            "max_new_items_per_session": 2,
            "self_seed_when_near_empty": True,
        },
    },
}

CONFIG_FILENAME = "agent-frameworks.yaml"


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins on conflicts.

    Nested dicts are merged recursively; all other values are replaced.
    Useful for layering config: defaults -> yaml -> env overrides.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# Backward-compatible alias (private name used internally)
_deep_merge = deep_merge


def _apply_env_overrides(config: dict) -> dict:
    """Apply environment variable overrides.

    Convention: AGENT_FW_<SECTION>_<KEY> maps to config[section][key].
    Example: AGENT_FW_GOVERNANCE_SRC_DIR -> config["governance"]["src_dir"]

    Only applies to leaf values (strings, ints, floats, bools).
    Nested dicts are not overridden via env vars (too error-prone).
    """
    prefix = "AGENT_FW_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].lower().split("_", 1)
        if len(parts) != 2:
            continue
        section, field = parts
        if section not in config:
            continue
        # Only override leaf values, not nested dicts
        if isinstance(config[section].get(field), dict):
            continue
        # Type coercion: try int, then float, then bool, then string
        config[section][field] = _coerce_env_value(value)
    return config


def _coerce_env_value(value: str) -> Any:
    """Coerce an environment variable string to the most appropriate Python type."""
    # Boolean
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    # Integer
    try:
        return int(value)
    except ValueError:
        pass
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    # String
    return value


def _load_yaml_config(root: Path) -> dict:
    """Load agent-frameworks.yaml from the project root. Returns empty dict on failure."""
    config_path = root / CONFIG_FILENAME
    if not config_path.exists():
        return {}

    if not HAS_YAML:
        print(
            f"  WARNING: PyYAML not installed; cannot load {CONFIG_FILENAME}. "
            "Install with: pip install pyyaml",
            file=sys.stderr,
        )
        return {}

    try:
        with config_path.open() as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(
            f"  WARNING: Failed to parse {CONFIG_FILENAME}: {e}. Using defaults.",
            file=sys.stderr,
        )
        return {}


def load_config(root: Path = None) -> dict:
    """Load configuration with layered priority.

    Priority: env vars > yaml file > built-in defaults.

    Args:
        root: Project root directory. Defaults to current working directory.

    Returns:
        Complete configuration dictionary with all sections populated.
    """
    if root is None:
        root = Path.cwd()
    root = Path(root)

    # Start with deep copy of defaults
    config = copy.deepcopy(DEFAULTS)

    # Layer 2: YAML override
    yaml_config = _load_yaml_config(root)
    config = _deep_merge(config, yaml_config)

    # Layer 3: Environment variable overrides (highest priority)
    config = _apply_env_overrides(config)

    return config


class Config:
    """Object-oriented wrapper around load_config().

    Provides dot-access and section-level retrieval for cleaner usage.
    """

    def __init__(self, root: Path = None):
        self._root = Path(root) if root else Path.cwd()
        self._data = load_config(self._root)

    def get_section(self, section: str) -> dict:
        """Get a full configuration section."""
        return self._data.get(section, {})

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a specific config value. Returns default if not found."""
        return self._data.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any) -> None:
        """Set a config value in memory (does not persist to file)."""
        if section not in self._data:
            self._data[section] = {}
        self._data[section][key] = value

    @property
    def raw(self) -> dict:
        """Access the raw config dictionary."""
        return self._data

    def __repr__(self) -> str:
        return f"Config(root={self._root})"
