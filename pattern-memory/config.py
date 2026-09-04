"""Pattern Memory — Configuration

Loads settings from (highest priority first):
  1. Environment variables (PATTERN_MEMORY_DB, PATTERN_MEMORY_CHROMA, etc.)
  2. agent-frameworks.yaml via common.config (if installed)
  3. Safe defaults (~/.pattern-memory/)

Works standalone without common.config — it's an optional dependency.
"""

import os
from pathlib import Path

# Try to import common.config — optional dependency
try:
    from common.config import load_config as _load_common_config
    HAS_COMMON_CONFIG = True
except ImportError:
    HAS_COMMON_CONFIG = False


# ─── Default paths ────────────────────────────────────────────────

_DEFAULT_DB_DIR = Path.home() / ".pattern-memory"
_DEFAULT_DB_PATH = str(_DEFAULT_DB_DIR / "patterns.db")
_DEFAULT_CHROMA_URL = "http://127.0.0.1:8000"
_DEFAULT_PID_FILE = str(_DEFAULT_DB_DIR / "server.pid")
_DEFAULT_SESSION_FILE = str(_DEFAULT_DB_DIR / "current_session.json")


def get_config() -> dict:
    """Load pattern-memory configuration.

    Priority: env vars > common.config > defaults.

    Returns:
        Dict with keys: db_path, chroma_url, pid_file, session_file,
        collection_name.
    """
    config = {
        "db_path": _DEFAULT_DB_PATH,
        "chroma_url": _DEFAULT_CHROMA_URL,
        "pid_file": _DEFAULT_PID_FILE,
        "session_file": _DEFAULT_SESSION_FILE,
        "collection_name": "pattern_memory",
    }

    # Layer 2: common.config (if available)
    if HAS_COMMON_CONFIG:
        try:
            common_cfg = _load_common_config()
            pm_section = common_cfg.get("pattern_memory", {})
            if "sqlite_path" in pm_section:
                config["db_path"] = str(Path(pm_section["sqlite_path"]).expanduser())
            if "chroma_path" in pm_section:
                # chroma_path in config is a local dir; we use chroma_url for HTTP
                # If it looks like a URL, use it directly
                val = pm_section["chroma_path"]
                if val.startswith("http"):
                    config["chroma_url"] = val
            if "singleton_pid" in pm_section:
                config["pid_file"] = str(Path(pm_section["singleton_pid"]).expanduser())
        except Exception:
            pass  # Graceful degradation — use defaults

    # Layer 3: Environment variables (highest priority)
    config["db_path"] = os.environ.get("PATTERN_MEMORY_DB", config["db_path"])
    config["chroma_url"] = os.environ.get("PATTERN_MEMORY_CHROMA", config["chroma_url"])
    config["pid_file"] = os.environ.get("PATTERN_MEMORY_PID", config["pid_file"])
    config["collection_name"] = os.environ.get(
        "PATTERN_MEMORY_COLLECTION", config["collection_name"]
    )

    return config
