#!/usr/bin/env python3
"""Collect independent evidence about a project's state.

This runs BEFORE any claims are read — pure observation.
Configurable via common.config (agent-frameworks.yaml).
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common.config import load_config
from common.logging import get_logger

logger = get_logger("governance.evidence")


def _get_gov_config(project_root: Path) -> dict:
    """Load governance section from the common config.

    Returns the governance section of agent-frameworks.yaml,
    falling back to safe generic defaults if not configured.
    """
    config = load_config(root=project_root)
    return config.get("governance", {})


def collect_evidence(project_root: str) -> dict:
    """Gather all verifiable facts about the project state.

    Args:
        project_root: Path to the project root directory.

    Returns:
        Dictionary with test results, file timestamps, tool counts, etc.

    Raises:
        FileNotFoundError: If project_root doesn't exist.
    """
    root = Path(project_root)
    if not root.exists():
        raise FileNotFoundError(f"Project root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Project root is not a directory: {root}")
    config = _get_gov_config(root)

    logger.info("Collecting evidence for %s", root)

    evidence = {
        "collected_at": datetime.now().isoformat(),
        "project_root": str(root),
        "tests": run_tests(root, config),
        "file_timestamps": get_file_timestamps(root, config),
        "actual_tool_count": count_mcp_tools(root, config),
        "readme_state": analyze_readme(root, config),
        "diary_timestamps": get_diary_timestamps(root, config),
        "source_files": list_source_files(root, config),
    }

    logger.info(
        "Evidence collected: %d tests passed, %d failed, %d source files",
        evidence["tests"]["passed"],
        evidence["tests"]["failed"],
        len(evidence["source_files"]),
    )
    return evidence


def run_tests(root: Path, config: dict) -> dict:
    """Run the full test suite and capture results."""
    test_dir = root / config.get("test_dir", "tests")
    if not test_dir.exists():
        logger.warning("Test directory not found: %s", test_dir)
        return {"status": "no_test_dir", "passed": 0, "failed": 0, "errors": []}

    test_cmd = config.get(
        "test_command",
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    )
    cwd_path = root / config.get("test_cwd", ".")

    logger.info("Running tests: %s (cwd: %s)", " ".join(test_cmd), cwd_path)

    try:
        result = subprocess.run(
            test_cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(cwd_path),
        )
        passed = 0
        failed = 0
        errors = []

        for line in result.stdout.split("\n"):
            if " PASSED" in line:
                passed += 1
            elif " FAILED" in line:
                failed += 1
                # Extract test name
                m = re.search(r"(.+?)::(\S+)\s+FAILED", line)
                if m:
                    errors.append(f"{m.group(1)}::{m.group(2)}")

        return {
            "exit_code": result.returncode,
            "passed": passed,
            "failed": failed,
            "total": passed + failed,
            "errors": errors,
            "output": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
        }
    except Exception as e:
        logger.error("Failed to run tests: %s", e)
        return {
            "exit_code": -999,
            "passed": 0,
            "failed": 0,
            "total": 0,
            "errors": [str(e)],
            "output": f"Error running tests: {e}",
        }


def get_file_timestamps(root: Path, config: dict) -> dict:
    """Get modification times for all source files."""
    timestamps = {}
    src_dir = root / config.get("src_dir", "src")
    pattern = config.get("source_file_pattern", "**/*.py")

    if not src_dir.exists():
        logger.warning("Source directory not found: %s", src_dir)
        return timestamps

    # Handle recursive glob patterns
    glob_iter = (
        src_dir.rglob(pattern.replace("**/", ""))
        if pattern.startswith("**/")
        else src_dir.glob(pattern)
    )

    for f in sorted(glob_iter):
        if "__pycache__" in str(f) or ".git" in str(f):
            continue
        if f.is_dir():
            continue
        stat = f.stat()
        timestamps[str(f.relative_to(root))] = {
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "ctime": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "size": stat.st_size,
        }
    return timestamps


def count_mcp_tools(root: Path, config: dict) -> int:
    """Count actual MCP tool definitions in the server file.

    Returns 0 if mcp_server_file is not configured or doesn't exist.
    """
    server_file = config.get("mcp_server_file")
    if not server_file:
        return 0

    server_py = root / server_file
    if not server_py.exists():
        return 0

    content = server_py.read_text()
    return len(re.findall(r"@mcp\.tool\(\)", content))


def count_test_functions(root: Path, config: dict) -> int:
    """Count actual test functions in test files.

    Matches both top-level functions (def test_xxx) and methods inside
    classes (    def test_xxx) — test classes are the standard pytest
    pattern, so ^def_ misses everything.
    """
    test_dir = root / config.get("test_dir", "tests")
    if not test_dir.exists():
        return 0

    count = 0
    for f in test_dir.rglob("test_*.py"):
        if f.is_dir():
            continue
        content = f.read_text()
        count += len(re.findall(r"^\s*def test_", content, re.MULTILINE))
    return count


def analyze_readme(root: Path, config: dict) -> dict:
    """Check what the README claims vs reality."""
    readme_path = root / config.get("readme_path", "README.md")
    if not readme_path.exists():
        return {"exists": False}

    content = readme_path.read_text()
    # Extract claimed test count
    test_claim = re.search(r"(\d+)/\d+\s*(?:tests?|passing)", content)
    # Extract claimed tool count (first match in main content)
    tool_claim = re.search(r"(\d+)\s*\w*\s*(?:MCP\s*)?tools?", content)

    return {
        "exists": True,
        "claimed_tests": int(test_claim.group(1)) if test_claim else None,
        "claimed_tools": int(tool_claim.group(1)) if tool_claim else None,
        "size": len(content),
    }


def get_diary_timestamps(root: Path, config: dict) -> dict:
    """Get file system timestamps for all diary entries."""
    diary_dir = root / config.get("diary_dir", "updates")
    if not diary_dir.exists():
        return {}

    timestamps = {}
    for f in sorted(diary_dir.glob("*.md")):
        stat = f.stat()
        timestamps[f.name] = {
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "ctime": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "size": stat.st_size,
        }
    return timestamps


def list_source_files(root: Path, config: dict) -> list:
    """List all source files."""
    src_dir = root / config.get("src_dir", "src")
    pattern = config.get("source_file_pattern", "**/*.py")

    if not src_dir.exists():
        return []

    files = []
    glob_iter = (
        src_dir.rglob(pattern.replace("**/", ""))
        if pattern.startswith("**/")
        else src_dir.glob(pattern)
    )

    for f in sorted(glob_iter):
        if "__pycache__" in str(f) or ".git" in str(f):
            continue
        if f.is_dir():
            continue
        files.append({
            "path": str(f.relative_to(root)),
            "size": f.stat().st_size,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return files


if __name__ == "__main__":
    project_root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    evidence = collect_evidence(project_root)
    print(json.dumps(evidence, indent=2))
