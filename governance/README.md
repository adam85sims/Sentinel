# Reusable Governance Audit Framework

This directory contains the Governance Audit Framework extracted from the Hermes Project. It serves as an independent compliance gate that verifies an AI agent's claims against objective, collectable evidence.

## Architecture

- **`audit.py`**: Main orchestrator. Runs evidence collection, claims extraction, calls the LLM, and formats findings.
- **`evidence.py`**: Configurable agent-independent observer. Collects test results, file timestamps, MCP tool count, README state, and diary file timestamps.
- **`claims.py`**: Parses markdown diary entries to extract the agent's stated test counts, tool count, modified files, and features.
- **`auditor.py`**: Communicates with the local LLM running in LM Studio (or similar OpenAI-compatible API) to perform the semantic compare. Includes pre-flight checks, retry loops, and escalation support.
- **`extract.py`**: Parses the auditor's JSON output and runs a deterministic comparator as a safety net.
- **`governance.yaml`**: Configuration file specifying paths, test commands, and files to observe.
- **`auditor.yaml`**: Configuration file specifying models, temperatures, and parameters for the auditor LLM.

## Setup & Configuration

To use the governance harness in a new project, copy this `governance/` folder to the root of your project and customize `governance.yaml` and `auditor.yaml`.

### 1. Configure the Target Project (`governance.yaml`)

Specify how the audit should observe your codebase:

```yaml
# The directory containing your source code
src_dir: "src"

# Path to the README of your project
readme_path: "README.md"

# Path to the file containing MCP server tool definitions (optional)
mcp_server_file: "src/server.py"

# Directory where daily diaries/updates are stored
diary_dir: "updates"

# Directory containing the tests
test_dir: "tests"

# The command to execute to run the test suite
test_command:
  - "python3"
  - "-m"
  - "pytest"
  - "tests/"
  - "-v"
  - "--tb=short"

# The working directory from which to run the test command (relative to project root)
test_cwd: "src"

# File pattern to scan for source files
source_file_pattern: "**/*.py"
```

### 2. Configure the LLM Auditor (`auditor.yaml`)

Define which model from LM Studio (or your local server) will run the audit.

```yaml
primary:
  model: ibm/granite-4.1-3b
  context_length: 8192
  temperature: 0.0
  max_tokens: 1024
  gpu: max
  expect_on_disk: true

escalation:
  model: mistralai/ministral-3-8b
  context_length: 8192
  temperature: 0.0
  max_tokens: 1024
  gpu: max
  expect_on_disk: true
```

*Note: The auditor model must be downloaded in LM Studio (e.g. via `lms get ibm/granite-4.1-3b@q4_k_m`).*

## Running the Audit

Make sure your local LLM server is running (default port `1234`), and run:

```bash
# Run audit on the most recent diary entry
python3 governance/audit.py .

# Audit a specific date's diary entry
python3 governance/audit.py . --diary 2026-06-27

# Output a JSON report to standard output
python3 governance/audit.py . --json

# Save reports to a reports directory
python3 governance/audit.py . --output governance/reports/
```
