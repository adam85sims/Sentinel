#!/usr/bin/env python3
"""Agent Frameworks — Setup & Diagnostics CLI

Detects your environment, configures agent-frameworks, and sets up
MCP integration for detected AI agent platforms.

Usage:
    agent-fw-setup init          # Interactive setup for new projects
    agent-fw-setup check         # Verify everything is configured
    agent-fw-setup doctor        # Diagnose and fix common problems
    agent-fw-setup uninstall     # Clean removal of configs and data
    agent-fw-setup detect        # Show what was detected in your environment
"""

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent-fw.setup")

# ─── Version ──────────────────────────────────────────────────────

__version__ = "0.1.0"


# ─── Detection ────────────────────────────────────────────────────

class EnvDetector:
    """Detect the current environment: Python, agents, LLMs, containers."""

    def __init__(self, root: Path = None):
        self.root = root or Path.cwd()
        self.python_version = platform.python_version()
        self.system = platform.system().lower()

    def detect_all(self) -> dict:
        """Run all detection checks and return a summary."""
        return {
            "python": self.detect_python(),
            "agents": self.detect_agents(),
            "llm_backends": self.detect_llm_backends(),
            "containers": self.detect_containers(),
            "existing_config": self.detect_existing_config(),
        }

    def detect_python(self) -> dict:
        """Check Python version and available tools."""
        return {
            "version": self.python_version,
            "ok": sys.version_info >= (3, 11),
            "pip": shutil.which("pip") or shutil.which("pip3"),
            "uv": shutil.which("uv"),
        }

    def detect_agents(self) -> dict:
        """Detect installed AI agent platforms."""
        home = Path.home()
        agents = {}

        # Claude Desktop
        claude_paths = {
            "darwin": home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            "linux": home / ".config" / "claude" / "claude_desktop_config.json",
        }
        claude_path = claude_paths.get(self.system)
        if claude_path and claude_path.exists():
            agents["claude-desktop"] = {"config": str(claude_path), "status": "found"}
        else:
            agents["claude-desktop"] = {"status": "not found"}

        # Hermes Agent
        hermes_config = home / ".hermes" / "config.yaml"
        if hermes_config.exists():
            agents["hermes"] = {"config": str(hermes_config), "status": "found"}
        else:
            agents["hermes"] = {"status": "not found"}

        # OpenCode
        opencode_config = home / ".config" / "opencode" / "opencode.jsonc"
        if opencode_config.exists():
            agents["opencode"] = {"config": str(opencode_config), "status": "found"}
        else:
            agents["opencode"] = {"status": "not found"}

        # Cursor
        cursor_config = home / ".cursor" / "mcp.json"
        if cursor_config.exists():
            agents["cursor"] = {"config": str(cursor_config), "status": "found"}
        else:
            agents["cursor"] = {"status": "not found"}

        return agents

    def detect_llm_backends(self) -> dict:
        """Detect available LLM backends."""
        backends = {}

        # LM Studio
        lms_binary = Path.home() / ".lmstudio" / "bin" / "lms"
        if lms_binary.exists():
            backends["lm-studio"] = {"binary": str(lms_binary), "status": "found"}
            # Try to get loaded models
            try:
                result = subprocess.run(
                    [str(lms_binary), "ps"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.stdout.strip():
                    backends["lm-studio"]["models"] = result.stdout.strip()
            except Exception as e:
                logger.debug("LM Studio model query failed: %s", e)
        else:
            backends["lm-studio"] = {"status": "not found"}

        # Ollama
        ollama_binary = shutil.which("ollama")
        if ollama_binary:
            backends["ollama"] = {"binary": ollama_binary, "status": "found"}
        else:
            backends["ollama"] = {"status": "not found"}

        # Check if any LLM server is running on common ports
        for name, port in [("lm-studio-1234", 1234), ("ollama-11434", 11434), ("vllm-8000", 8000)]:
            try:
                import urllib.request
                urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=2)
                backends[name.rsplit("-", 1)[0]] = backends.get(name.rsplit("-", 1)[0], {})
                backends[name.rsplit("-", 1)[0]]["running"] = True
                backends[name.rsplit("-", 1)[0]]["port"] = port
            except Exception as e:
                logger.debug("Port %d probe failed: %s", port, e)

        return backends

    def detect_containers(self) -> dict:
        """Detect container runtimes and running services."""
        containers = {}

        # Podman
        podman = shutil.which("podman")
        if podman:
            containers["podman"] = {"binary": podman, "status": "found"}
            # Check for running ChromaDB
            try:
                result = subprocess.run(
                    [podman, "ps", "--format", "{{.Names}} {{.Ports}}"],
                    capture_output=True, text=True, timeout=5,
                )
                if "chroma" in result.stdout.lower():
                    containers["chromadb"] = {"status": "running", "runtime": "podman"}
            except Exception as e:
                logger.debug("Podman query failed: %s", e)
        else:
            containers["podman"] = {"status": "not found"}

        # Docker
        docker = shutil.which("docker")
        if docker:
            containers["docker"] = {"binary": docker, "status": "found"}
        else:
            containers["docker"] = {"status": "not found"}

        return containers

    def detect_existing_config(self) -> dict:
        """Check for existing agent-frameworks config."""
        config_file = self.root / "agent-frameworks.yaml"
        governance_dir = self.root / "governance"
        brain_dir = self.root / ".brain"

        return {
            "config_file": {
                "exists": config_file.exists(),
                "path": str(config_file),
            },
            "governance_dir": {
                "exists": governance_dir.exists(),
                "path": str(governance_dir),
            },
            "brain_dir": {
                "exists": brain_dir.exists(),
                "path": str(brain_dir),
            },
        }


# ─── Setup Actions ────────────────────────────────────────────────

def action_detect(args):
    """Show what was detected in the environment."""
    detector = EnvDetector(root=Path(args.root))
    results = detector.detect_all()

    print("\n=== Agent Frameworks Environment Detection ===\n")

    # Python
    py = results["python"]
    status = "✓" if py["ok"] else "✗"
    print(f"  {status} Python {py['version']}" + (" (need 3.11+)" if not py["ok"] else ""))

    # Agents
    print("\n  AI Agent Platforms:")
    for name, info in results["agents"].items():
        status = "✓" if info["status"] == "found" else "·"
        print(f"    {status} {name}")

    # LLM Backends
    print("\n  LLM Backends:")
    for name, info in results["llm_backends"].items():
        status = "✓" if info.get("running") or info["status"] == "found" else "·"
        extra = f" (port {info['port']})" if info.get("running") else ""
        print(f"    {status} {name}{extra}")

    # Containers
    print("\n  Container Runtimes:")
    for name, info in results["containers"].items():
        status = "✓" if info["status"] == "found" else "·"
        print(f"    {status} {name}")

    # Existing config
    print("\n  Existing Config:")
    for name, info in results["existing_config"].items():
        status = "✓" if info["exists"] else "·"
        print(f"    {status} {name}: {info['path']}")

    print()


def action_init(args):
    """Interactive setup for a new project."""
    root = Path(args.root)
    print(f"\n=== Agent Frameworks Init: {root} ===\n")

    detector = EnvDetector(root=root)
    env = detector.detect_all()

    # Step 1: Create agent-frameworks.yaml
    config_file = root / "agent-frameworks.yaml"
    if config_file.exists() and not args.force:
        print(f"  · {config_file} already exists (use --force to overwrite)")
    else:
        _create_config(root, env)
        print(f"  ✓ Created {config_file}")

    # Step 2: Create governance directory
    gov_dir = root / "governance"
    if not gov_dir.exists():
        gov_dir.mkdir(parents=True, exist_ok=True)
        _create_governance_configs(gov_dir)
        print(f"  ✓ Created {gov_dir}/")

    # Step 3: Create .brain directory from templates
    brain_dir = root / ".brain"
    if not brain_dir.exists():
        brain_dir.mkdir(parents=True, exist_ok=True)
        _create_brain_files(brain_dir)
        print(f"  ✓ Created {brain_dir}/")

    # Step 4: Create TODO.md if not exists
    todo_file = root / "TODO.md"
    if not todo_file.exists():
        todo_file.write_text(_TODO_TEMPLATE)
        print(f"  ✓ Created {todo_file}")

    # Step 5: Create updates/ directory
    updates_dir = root / "updates"
    if not updates_dir.exists():
        updates_dir.mkdir(exist_ok=True)
        print(f"  ✓ Created {updates_dir}/")

    # Step 6: Configure MCP for detected agents
    agents_with_config = {k: v for k, v in env["agents"].items() if v["status"] == "found"}
    if agents_with_config:
        print(f"\n  Detected {len(agents_with_config)} agent platform(s). Configure MCP? [Y/n] ", end="")
        if args.yes or input().strip().lower() != "n":
            for name, info in agents_with_config.items():
                _configure_mcp(root, name, info)
    else:
        print("\n  No agent platforms detected. MCP config skipped.")

    print("\n✓ Setup complete!\n")
    print("  Next steps:")
    print("    1. Review agent-frameworks.yaml")
    print("    2. Add tasks to TODO.md")
    print("    3. Run: agent-fw-setup check")


def action_check(args):
    """Verify everything is configured and working."""
    root = Path(args.root)
    print(f"\n=== Agent Frameworks Check: {root} ===\n")

    issues = []

    # Check config file
    config_file = root / "agent-frameworks.yaml"
    if config_file.exists():
        print("  ✓ agent-frameworks.yaml exists")
    else:
        print("  ✗ agent-frameworks.yaml missing")
        issues.append("config_missing")

    # Check governance
    gov_dir = root / "governance"
    if gov_dir.exists():
        print("  ✓ governance/ directory exists")
        gov_yaml = gov_dir / "governance.yaml"
        if gov_yaml.exists():
            print("    ✓ governance.yaml present")
        else:
            print("    ✗ governance.yaml missing")
            issues.append("governance_incomplete")
    else:
        print("  ✗ governance/ directory missing")
        issues.append("governance_missing")

    # Check .brain
    brain_dir = root / ".brain"
    if brain_dir.exists():
        print("  ✓ .brain/ directory exists")
        for f in ["session.md", "memory.md", "map.json"]:
            if (brain_dir / f).exists():
                print(f"    ✓ {f}")
            else:
                print(f"    · {f} (will be created on first save)")
    else:
        print("  · .brain/ directory missing (will be created on first session)")

    # Check TODO.md
    todo_file = root / "TODO.md"
    if todo_file.exists():
        print("  ✓ TODO.md exists")
    else:
        print("  · TODO.md missing (run: agent-fw-setup init)")

    # Check Python deps
    print("\n  Dependencies:")
    try:
        import yaml
        print("    ✓ PyYAML installed")
    except ImportError:
        print("    · PyYAML not installed (optional, for config files)")
        issues.append("pyyaml_missing")

    try:
        import chromadb
        print("    ✓ ChromaDB installed")
    except ImportError:
        print("    · ChromaDB not installed (optional, for pattern-memory)")

    # Summary
    if issues:
        print(f"\n  ⚠ {len(issues)} issue(s) found. Run: agent-fw-setup doctor")
    else:
        print("\n  ✓ All checks passed!")

    print()


def action_doctor(args):
    """Diagnose and fix common problems."""
    root = Path(args.root)
    print(f"\n=== Agent Frameworks Doctor: {root} ===\n")

    fixed = 0

    # Fix 1: Create missing directories
    for dirname in ["governance", ".brain", "updates"]:
        dirpath = root / dirname
        if not dirpath.exists():
            dirpath.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ Created {dirname}/")
            fixed += 1

    # Fix 2: Create config if missing
    config_file = root / "agent-frameworks.yaml"
    if not config_file.exists():
        _create_config(root, {})
        print(f"  ✓ Created agent-frameworks.yaml")
        fixed += 1

    # Fix 3: Create governance configs if missing
    gov_dir = root / "governance"
    if gov_dir.exists():
        for fname in ["governance.yaml", "auditor.yaml"]:
            if not (gov_dir / fname).exists():
                _create_governance_configs(gov_dir)
                print(f"  ✓ Created governance configs")
                fixed += 1
                break

    # Fix 4: Create .brain files if missing
    brain_dir = root / ".brain"
    if brain_dir.exists():
        missing = any(not (brain_dir / f).exists() for f in ["session.md", "memory.md", "map.json"])
        if missing:
            _create_brain_files(brain_dir)
            print(f"  ✓ Created missing .brain/ files")
            fixed += 1

    if fixed == 0:
        print("  ✓ No issues found — everything looks good!")
    else:
        print(f"\n  Fixed {fixed} issue(s). Run: agent-fw-setup check")

    print()


def action_uninstall(args):
    """Clean removal of configs and data."""
    root = Path(args.root)
    print(f"\n=== Agent Frameworks Uninstall: {root} ===\n")

    targets = [
        root / "agent-frameworks.yaml",
        root / ".brain",
        root / "governance",
    ]

    for target in targets:
        if target.exists():
            print(f"  Will remove: {target}")
            if not args.yes:
                print(f"    Remove? [y/N] ", end="")
                if input().strip().lower() != "y":
                    print("    Skipped")
                    continue
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            print(f"    ✓ Removed")

    print("\n✓ Uninstall complete.\n")


# ─── Helpers ──────────────────────────────────────────────────────

def _create_config(root: Path, env: dict):
    """Generate agent-frameworks.yaml for the project."""
    content = """# Agent Frameworks Configuration
# See: https://hermes-agent.nousresearch.com/docs

governance:
  src_dir: "src"
  readme_path: "README.md"
  # mcp_server_file: "src/server.py"  # optional
  diary_dir: "updates"
  test_dir: "tests"
  test_command: ["python3", "-m", "pytest", "tests/", "-v", "--tb=short"]
  test_cwd: "."
  source_file_pattern: "**/*.py"

pattern_memory:
  sqlite_path: "~/.agent-frameworks/pattern-memory.db"
  chroma_path: "http://127.0.0.1:8000"

automation:
  model_routing:
    reasoning:
      models:
        - provider: "opencode-go"
          model: "mimo-v2.5"
      use_for: ["research", "architecture", "code_review", "debugging"]
    speed:
      models:
        - provider: "opencode-go"
          model: "deepseek-v4-flash"
      use_for: ["scaffolding", "crud", "boilerplate"]
  exit_conditions:
    max_items_per_session: 3
    context_usage_limit: 0.6
    require_governance_pass: true
"""
    (root / "agent-frameworks.yaml").write_text(content)


def _create_governance_configs(gov_dir: Path):
    """Create governance config files."""
    gov_yaml = """# Project Governance Config
src_dir: "src"
readme_path: "README.md"
diary_dir: "updates"
test_dir: "tests"
test_command: ["python3", "-m", "pytest", "tests/", "-v", "--tb=short"]
test_cwd: "."
source_file_pattern: "**/*.py"
"""
    (gov_dir / "governance.yaml").write_text(gov_yaml)

    auditor_yaml = """# Auditor Configuration
backend:
  type: "openai-compatible"
  url: "http://localhost:1234/v1/chat/completions"
  lms_binary: "~/.lmstudio/bin/lms"

primary:
  model: "ibm/granite-4.1-3b"
  context_length: 8192
  temperature: 0.0
  max_tokens: 1024
  gpu: "max"
  expect_on_disk: true

escalation:
  model: "mistralai/ministral-3-8b"
  context_length: 8192
  temperature: 0.0
  max_tokens: 1024
  gpu: "max"
  expect_on_disk: true

keep_resident: true
retry:
  max_attempts: 3
  backoff_seconds: 5
"""
    (gov_dir / "auditor.yaml").write_text(auditor_yaml)


def _create_brain_files(brain_dir: Path):
    """Create .brain files from templates if they don't exist."""
    brain_dir.mkdir(parents=True, exist_ok=True)

    session_md = brain_dir / "session.md"
    if not session_md.exists():
        session_md.write_text("""# Session State

- **Started:** (not started)
- **Current Goal:** (not set)
- **Status:** pending
- **Context Used:** 0%

## Active Tasks
(no tasks)

## Blockers
(none)

## Recent Decisions
(none)
""")

    memory_md = brain_dir / "memory.md"
    if not memory_md.exists():
        memory_md.write_text("""# Memory Log (Lessons Learned)

## Architecture Decisions
| Date | Decision | Reasoning | Revisit? |
|------|----------|-----------|----------|

## Gotchas & Pitfalls
| Date | Issue | Root Cause | Fix |
|------|-------|------------|-----|

## Performance Notes
| Date | Observation | Metric | Action Taken |
|------|-------------|--------|--------------|

## User Preferences
| Preference | Context | First Noted |
|------------|---------|-------------|
""")

    map_json = brain_dir / "map.json"
    if not map_json.exists():
        map_json.write_text(json.dumps({
            "entry_points": [],
            "key_components": {},
            "test_commands": [],
            "config_files": [],
        }, indent=2))


def _configure_mcp(root: Path, agent_name: str, agent_info: dict):
    """Generate MCP config snippet for a detected agent."""
    server_script = str(Path(__file__).parent.parent / "pattern-memory" / "server.py")

    config = {
        "command": "python3",
        "args": [server_script],
    }

    print(f"\n    {agent_name}:")
    print(f"    Add to {agent_info.get('config', 'your MCP config')}:")
    print(json.dumps({"pattern-memory": config}, indent=6))
    print()


_TODO_TEMPLATE = """# Work Queue

> The agent works through this list top-to-bottom during each session.
> Pick the first unchecked item. Mark done when complete.

## Rules
1. Pick the first `[ ]` item under "Pending" — do it, mark `[x]`, move to "Done"
2. Max 2 new items per session
3. Exit when queue is empty, or audit shows CRITICAL

## Pending
- [ ] Initialize the project and setup codebase structure
- [ ] Write initial tests to verify the setup
- [ ] Implement the core application logic

## Done
(empty)

## Blocked
(empty)
"""


# ─── CLI Entry Point ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="agent-fw-setup",
        description="Agent Frameworks — Setup & Diagnostics",
    )
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmations")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Interactive setup for new projects")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing config")
    p_init.set_defaults(func=action_init)

    # check
    p_check = sub.add_parser("check", help="Verify everything is configured")
    p_check.set_defaults(func=action_check)

    # doctor
    p_doctor = sub.add_parser("doctor", help="Diagnose and fix common problems")
    p_doctor.set_defaults(func=action_doctor)

    # detect
    p_detect = sub.add_parser("detect", help="Show detected environment")
    p_detect.set_defaults(func=action_detect)

    # uninstall
    p_uninstall = sub.add_parser("uninstall", help="Clean removal of configs")
    p_uninstall.set_defaults(func=action_uninstall)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
