"""Pattern Memory — MCP Config Generator

Detects installed AI agent platforms and generates MCP server configuration
for pattern-memory integration.

Supported platforms:
  - Claude Desktop (macOS/Linux)
  - Hermes Agent
  - OpenCode
  - Cursor
  - Generic (prints config snippet for manual insertion)

Usage:
    from mcp_config import detect_platforms, generate_config, apply_config

    platforms = detect_platforms()
    for name, info in platforms.items():
        print(f"Found: {name} at {info['config_path']}")
        config = generate_config("pattern-memory", info)
        apply_config(name, info, config)
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Optional

from common.logging import get_logger

logger = get_logger("pattern-memory.mcp_config")

# The MCP server command for pattern-memory
_PATTERN_MEMORY_CMD = "pattern-memory-server"


def _get_config_path(platform: str) -> Optional[Path]:
    """Get the MCP config file path for a platform."""
    home = Path.home()

    paths = {
        "claude-desktop": {
            "darwin": home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            "linux": home / ".config" / "claude" / "claude_desktop_config.json",
        },
        "hermes": home / ".hermes" / "config.yaml",
        "opencode": home / ".config" / "opencode" / "opencode.jsonc",
        "cursor": home / ".cursor" / "mcp.json",
    }

    if platform not in paths:
        return None

    import platform as _platform
    system = _platform.system().lower()

    if isinstance(paths[platform], dict):
        return paths[platform].get(system)
    return paths[platform]


def detect_platforms() -> dict:
    """Detect which AI agent platforms are installed.

    Returns:
        Dict of platform_name -> {"config_path": Path, "exists": bool, "has_mcp": bool}
    """
    platforms = {}

    for name in ["claude-desktop", "hermes", "opencode", "cursor"]:
        config_path = _get_config_path(name)
        if config_path is None:
            continue

        exists = config_path.exists()
        has_mcp = False

        if exists:
            try:
                content = config_path.read_text()
                if name in ("claude-desktop", "cursor"):
                    data = json.loads(content)
                    has_mcp = "mcpServers" in data
                elif name == "hermes":
                    has_mcp = "mcpServers" in content
                elif name == "opencode":
                    has_mcp = "mcp" in content.lower()
            except Exception as e:
                logger.debug("Failed to read %s config: %s", name, e)

        platforms[name] = {
            "config_path": config_path,
            "exists": exists,
            "has_mcp": has_mcp,
        }

    return platforms


def generate_config(platform: str, server_script: str = None) -> dict:
    """Generate MCP server config for pattern-memory.

    Args:
        platform: Platform name (e.g., "claude-desktop", "cursor")
        server_script: Path to the server.py script.
                      If None, uses the installed entry point.

    Returns:
        Dict in the platform's expected format.
    """
    if server_script is None:
        server_script = str(Path(__file__).parent / "server.py")

    # Common MCP server entry
    server_entry = {
        "command": "python3",
        "args": [server_script],
    }

    if platform in ("claude-desktop", "cursor"):
        return {"mcpServers": {"pattern-memory": server_entry}}

    elif platform == "hermes":
        return {"mcpServers": {"pattern-memory": server_entry}}

    elif platform == "opencode":
        return {"mcp": {"servers": {"pattern-memory": server_entry}}}

    # Generic: just return the server entry
    return server_entry


def apply_config(platform: str, platform_info: dict, new_config: dict,
                 backup: bool = True) -> bool:
    """Apply MCP config to a platform's config file.

    Merges pattern-memory into existing mcpServers section.
    Creates backup before modifying.

    Args:
        platform: Platform name
        platform_info: Info dict from detect_platforms()
        new_config: Config to apply (from generate_config())
        backup: If True, create .bak before modifying

    Returns:
        True if applied successfully, False on error.
    """
    config_path = platform_info["config_path"]

    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        return False

    try:
        content = config_path.read_text()

        # Parse based on platform
        if platform in ("claude-desktop", "cursor"):
            existing = json.loads(content)
            mcp_key = "mcpServers"
        elif platform == "hermes":
            # YAML-based — for now, just print instructions
            logger.info("Hermes uses YAML config. Please add manually:")
            logger.info(json.dumps(new_config, indent=2))
            return True
        elif platform == "opencode":
            existing = json.loads(content)
            mcp_key = "mcp"
        else:
            logger.warning("Unknown platform: %s", platform)
            return False

        # Merge
        if mcp_key not in existing:
            existing[mcp_key] = {}
        if "servers" in new_config.get(mcp_key, {}):
            # OpenCode format
            if "servers" not in existing[mcp_key]:
                existing[mcp_key]["servers"] = {}
            existing[mcp_key]["servers"]["pattern-memory"] = new_config[mcp_key]["servers"]["pattern-memory"]
        else:
            existing[mcp_key]["pattern-memory"] = new_config[mcp_key]["pattern-memory"]

        # Backup
        if backup:
            backup_path = config_path.with_suffix(config_path.suffix + ".bak")
            shutil.copy2(config_path, backup_path)
            logger.info("Backup created: %s", backup_path)

        # Write
        if platform in ("claude-desktop", "cursor"):
            config_path.write_text(json.dumps(existing, indent=2))
        elif platform == "opencode":
            config_path.write_text(json.dumps(existing, indent=2))

        logger.info("Config applied to %s: %s", platform, config_path)
        return True

    except Exception as e:
        logger.error("Failed to apply config: %s", e)
        return False


def print_config_snippet():
    """Print a generic MCP config snippet for manual insertion."""
    config = generate_config("generic")
    print("\n=== Pattern Memory MCP Config ===\n")
    print("Add this to your MCP client configuration:\n")
    print(json.dumps({"pattern-memory": config}, indent=2))
    print()


if __name__ == "__main__":
    print("Detecting AI agent platforms...\n")
    platforms = detect_platforms()

    if not platforms:
        print("No supported platforms found.")
        print_config_snippet()
    else:
        for name, info in platforms.items():
            status = "✓ (has MCP)" if info["has_mcp"] else "✓ (no MCP)" if info["exists"] else "✗ not found"
            print(f"  {name}: {status}")
            print(f"    Config: {info['config_path']}")

    print()
    print_config_snippet()
