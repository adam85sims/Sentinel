# API Reference

Complete reference for every public class and function in agent-frameworks.

---

## common — Shared Infrastructure

### common.config

#### `Config`

```python
from common import Config

config = Config(root=".")          # Load from project root
config = Config(root="/my/project")
```

Layered config loader. Merges built-in defaults, `agent-frameworks.yaml`,
and environment variables (highest priority).

**Methods:**

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `get_section` | `(section: str)` | `dict` | Get an entire config section |
| `get` | `(section: str, key: str, default=None)` | `Any` | Get a single value |
| `set` | `(section: str, key: str, value: Any)` | `None` | Set a value (in-memory only) |
| `raw` | `()` | `dict` | Get the full merged config dict |
| `__repr__` | `()` | `str` | String representation |

**Environment variable convention:** `AGENT_FW_<SECTION>_<KEY>`

```python
# agent-frameworks.yaml:
#   governance:
#     src_dir: "src"
#
# Environment override:
#   AGENT_FW_GOVERNANCE_SRC_DIR=lib

config.get("governance", "src_dir")  # -> "lib" (from env) or "src" (from yaml)
```

#### `load_config`

```python
from common import load_config

config_dict = load_config(root=".")  # Returns raw dict, not Config wrapper
```

Returns the merged config as a plain dict. Useful when you need the raw data
without the `Config` wrapper methods.

---

### common.logging

#### `setup_logging`

```python
from common import setup_logging

logger = setup_logging(level="DEBUG")
```

Configure structured logging with module prefixes. Call once at startup.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level` | `str` | `"INFO"` | Log level: DEBUG, INFO, WARNING, ERROR |

**Env override:** `AGENT_FW_LOG_LEVEL=DEBUG`

#### `get_logger`

```python
from common import get_logger

logger = get_logger("governance")   # -> logger with [governance] prefix
logger = get_logger("pattern-memory")
logger.info("Started audit")         # -> "12:34:56 [INFO] [governance] Started audit"
```

Returns a logger with the module name as prefix. Call `setup_logging` first
for consistent formatting, but works standalone with root logger defaults.

---

### common.models

#### `Severity`

```python
from common import Severity

Severity.CRITICAL    # "critical"
Severity.WARNING     # "warning"
Severity.INFO        # "info"
```

Enum (str) for audit discrepancy severity.

#### `Verdict`

```python
from common import Verdict

Verdict.PASS         # "pass"
Verdict.FAIL         # "fail"
VerdictWARN         # "warn"
```

Enum (str) for overall audit verdict.

#### `Discrepancy`

```python
from common import Discrepancy

d = Discrepancy(
    severity=Severity.WARNING,
    type="count_mismatch",
    description="Claimed 5 files, found 3",
    claimed="5",
    actual="3",
)

d.to_dict()          # Serialize to dict
Discrepancy.from_dict(data)  # Deserialize from dict
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `severity` | `Severity` | yes | CRITICAL / WARNING / INFO |
| `type` | `str` | yes | Category of discrepancy |
| `description` | `str` | yes | Human-readable explanation |
| `claimed` | `str` | no | What the agent claimed |
| `actual` | `str` | no | What was actually found |

#### `Evidence`

```python
from common import Evidence

e = Evidence(
    tests={"passed": 45, "failed": 0},
    test_timestamp="2026-06-27T12:00:00",
    tool_count=13,
    source_files=["src/server.py", "src/storage.py"],
)
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `tests` | `dict` | Test results: `{"passed": N, "failed": N, "command": str}` |
| `test_timestamp` | `str` | ISO timestamp of test run |
| `tool_count` | `int` | MCP tool count if applicable |
| `source_files` | `list[str]` | List of source files with mtimes |
| `diary_dates` | `list[str]` | Diary entry dates found |
| `readme_features` | `list[str]` | Features listed in README |

#### `Claim`

```python
from common import Claim

c = Claim(
    date="2026-06-27",
    tests_passed="45",
    tool_count="13",
    features=["MCP server", "pattern storage"],
    files_modified=["src/server.py"],
)
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `date` | `str` | Date from diary entry |
| `tests_passed` | `str` | Claimed test count |
| `tool_count` | `str` | Claimed MCP tool count |
| `features` | `list[str]` | Claimed features |
| `files_modified` | `list[str]` | Claimed file modifications |

#### `AuditResult`

```python
from common import AuditResult

result = AuditResult(
    verdict=Verdict.PASS,
    discrepancies=[],
    evidence=evidence,
    claims=claim,
    auditor_report="All checks passed",
)

result.critical_count    # int — number of CRITICAL discrepancies
result.warning_count     # int — number of WARNING discrepancies
result.to_dict()         # dict — full serialization
AuditResult.from_dict(data)  # AuditResult — deserialize
```

---

## governance — Audit Framework

### `run_audit`

```python
from governance import run_audit

result = run_audit(
    project_root=".",
    diary_date=None,          # Optional: audit specific diary entry
    output_dir="governance/reports/",  # Optional: where to save reports
)

if result.verdict == Verdict.FAIL:
    for d in result.discrepancies:
        if d.severity == Severity.CRITICAL:
            print(f"BLOCKED: {d.description}")
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_root` | `str` | required | Project root directory |
| `diary_date` | `str \| None` | `None` | Audit specific diary date (YYYY-MM-DD) |
| `output_dir` | `str \| None` | `None` | Save JSON + text reports here |

**Returns:** `AuditResult`

### `extract_claims`

```python
from governance import extract_claims

claims = extract_claims(
    diary_path="updates/2026-06-27.md",
    custom_patterns={          # Optional: extend built-in patterns
        "custom_field": r"Custom:\s*(.+)",
    },
)
```

Parses a diary entry file for structured claims. Supports `custom_patterns`
to extend or override the built-in regex patterns.

**Returns:** `dict` with keys: `date`, `tests_passed`, `tool_count`, `features`, `files_modified`, etc.

### `collect_evidence`

```python
from governance import collect_evidence

evidence = collect_evidence(project_root=".")
# -> {"tests": {...}, "test_timestamp": ..., "tool_count": N, ...}
```

Independently collects evidence by running tests, stat-ing files, counting tools.

**Returns:** `dict`

### `load_auditor_config`

```python
from governance import load_auditor_config

config = load_auditor_config(project_root=".")
# -> {"backend": {"type": "openai-compatible", ...}, ...}
```

Loads auditor config from `governance/auditor.yaml`, merged with defaults.

### `audit`

```python
from governance import audit

report = audit(
    claims=claims_dict,
    evidence=evidence_dict,
    config=auditor_config,    # Optional: uses load_auditor_config() if None
    project_root=".",         # Optional: for file existence checks
)
# -> str: Raw auditor report text
```

Calls the configured LLM backend to verify claims against evidence.

### `extract_findings` / `format_report`

```python
from governance import extract_findings, format_report

findings = extract_findings(
    report=auditor_report_text,
    claims=claims_dict,
    evidence=evidence_dict,
    project_root=".",
)
# -> dict with verdict, discrepancies, etc.

text_report = format_report(findings)
# -> str: Human-readable audit report
```

---

## pattern-memory — MCP Server

### CLI Usage

```bash
# Record a correction
python3 pattern-memory/cli.py record \\
  --session "2026-06-27" \\
  --category "testing" \\
  --correction "Use caplog not capsys for log assertions" \\
  --context "capsys captures stdout, not logging"

# Find patterns
python3 pattern-memory/cli.py find --query "log assertions"

# List all patterns
python3 pattern-memory/cli.py list

# Clear all patterns (dangerous!)
python3 pattern-memory/cli.py clear
```

### MCP Server

```bash
# Start the MCP server (used by agent platforms)
python3 pattern-memory/server.py
```

**13 MCP tools provided:**

- `record_correction` — Record a user correction with context
- `find_patterns` — Search for relevant patterns by query
- `get_pattern` — Retrieve a specific pattern by ID
- `list_patterns` — List all stored patterns
- `clear_patterns` — Clear all patterns (with confirmation)
- `get_stats` — Get pattern storage statistics
- `find_by_category` — Filter patterns by category
- `find_by_severity` — Filter by severity level
- `get_recent_patterns` — Get N most recent patterns
- `resolve_pattern` — Mark a pattern as resolved
- `delete_pattern` — Delete a single pattern
- `export_patterns` — Export all patterns as JSON
- `import_patterns` — Import patterns from JSON

### MCP Config Generation

```python
from pattern_memory.mcp_config import detect_platforms, generate_config

platforms = detect_platforms()
# -> {"hermes": {"config": ..., "status": "found"}, ...}

config = generate_config("hermes", server_path="/path/to/server.py")
# -> {"command": "python3", "args": [...]}
```

### Session Wrapper

```bash
# Wrap any session — auto-records corrections
python3 pattern-memory/wrapper.py --command "your-agent-session-command"
```

---

## automation — Model Routing & Session Management

### `ModelRouter`

```python
from automation import ModelRouter

router = ModelRouter(root=".")          # Load config from project root

# Route a task to the best model
model = router.route("research")
# -> {"provider": "openai-compatible", "model": "claude-sonnet-4"}

# Get all models for a task type (fallback chain)
models = router.route_all("research")
# -> [{"provider": ..., "model": ...}, ...]

# Get metadata about a task type
info = router.describe("research")
# -> {"task_type": "research", "tier": "reasoning", "models": [...]}

# List all configured task types
tasks = router.list_tasks()
# -> {"research": "reasoning", "scaffolding": "speed", ...}

# List all configured tiers
tiers = router.list_tiers()
# -> {"reasoning": {...}, "speed": {...}}
```

### `route_task` (convenience function)

```python
from automation import route_task

model = route_task("debugging", root=".")
# -> {"provider": ..., "model": ...}
```

### `SessionState`

```python
from automation import SessionState

session = SessionState(root=".")

session.start("Build authentication system")

session.update_status("in-progress")     # or "blocked", "done"
session.add_next_step("Create models")
session.add_decision("Used JWT over sessions", "Stateless, scales better")
session.add_gotcha("Token expiry not tested", "Add test for refresh flow")

session.update_map(
    entry_points=["src/main.py"],
    key_components={"auth": "src/auth/"},
    test_commands=["pytest tests/test_auth.py"],
)

session.save()
# Writes:
#   .brain/session.md  — Active session state
#   .brain/memory.md   — Decision log + gotchas
#   .brain/map.json    — Project structural map

# Load in a new session
session2 = SessionState(root=".")
session2.load()
print(session2.goal)       # "Build authentication system"
```

### `WorkQueue`

```python
from automation import WorkQueue

queue = WorkQueue(root=".")
queue.load()                 # Read TODO.md

# Get the next pending item (top-to-bottom order)
item = queue.next_item()
if item:
    print(item.description)  # "Implement user model"
    # ... do the work ...
    queue.complete(item.id)
    queue.save()             # Write back to TODO.md

# Block an item that needs user input
queue.block(item.id, reason="Needs user input on API design")

# Add new work discovered during session
queue.add_item("Add input validation to user model")

# Check if the session should exit
reason = queue.should_exit(context_usage=0.65)
if reason:
    print(f"Stop: {reason}")
    # Returns one of:
    #   "queue_empty"             — all items done
    #   "max_items_completed"    — hit max_items_per_session limit
    #   "context_usage_high"     — context_usage exceeds limit
    #   "has_blocked_items"      — items waiting for user input
    #   None                     — keep going
```

**WorkItem fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier |
| `description` | `str` | Task description |
| `status` | `str` | `"pending"`, `"done"`, or `"blocked"` |
| `blocked_reason` | `str \| None` | Why it's blocked (if applicable) |

---

## Setup CLI

### `EnvDetector`

```python
from common.setup_cli import EnvDetector

detector = EnvDetector(root=".")

# Detect everything
env = detector.detect_all()
# -> {
#   "python": {"version": "3.14.6", "ok": True, ...},
#   "agents": {"hermes": {"status": "found", ...}, ...},
#   "llm_backends": {"lm-studio": {"running": True, "port": 1234}, ...},
#   "containers": {"podman": {"status": "found", ...}, ...},
#   "existing_config": {"config_file": {"exists": False, ...}, ...},
# }

# Individual detection methods
detector.detect_python()
detector.detect_agents()       # Claude Desktop, Hermes, OpenCode, Cursor
detector.detect_llm_backends()  # LM Studio, Ollama, vLLM (port probing)
detector.detect_containers()    # Podman, Docker, ChromaDB
detector.detect_existing_config()
```

### CLI Commands

```
agent-fw-setup init        Create agent-frameworks.yaml, governance/, .brain/, TODO.md
agent-fw-setup check       Verify config, directories, and dependencies
agent-fw-setup doctor      Auto-create missing directories and configs
agent-fw-setup detect      Show detected agents, LLMs, and containers
agent-fw-setup uninstall   Remove agent-frameworks config and data
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--root DIR` | Project root directory (default: current directory) |
| `--yes, -y` | Skip confirmation prompts |
| `--force` | Overwrite existing config (init only) |
| `--version` | Show version |