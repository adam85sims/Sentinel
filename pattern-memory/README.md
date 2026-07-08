# Pattern Memory

An MCP server that learns behavioral patterns from user corrections and injects them into agent context.

## The Problem

AI agents forget everything between sessions and fail to learn from user corrections. When you correct an agent's behavior (e.g., "use 80% not 85%"), that correction is lost. The agent starts from scratch every time.

## The Solution

Pattern Memory watches for user corrections, extracts reusable patterns, stores them with confidence scores, and injects learned patterns into agent context at session start.

## How It Works

1. **Record** — When you correct an agent, `record_correction` stores the correction
2. **Learn** — The engine extracts a pattern and calculates confidence
3. **Recall** — At session start, `get_patterns` retrieves relevant learned patterns
4. **Rate** — You can confirm or reject patterns via `rate_pattern` to refine confidence
5. **Self-Correct** — Before acting, `check_before_acting` checks for relevant patterns

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

### As an MCP Server

Add to your MCP client config (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "pattern-memory": {
      "command": "python3",
      "args": ["/path/to/pattern-memory/server.py"]
    }
  }
}
```

### MCP Tools (13 consolidated tools)

| Tool | Category | Description |
|------|----------|-------------|
| `record_correction` | INPUT | Record when user corrects agent behavior |
| `classify_correction` | INPUT | Classify messages as corrections (regex/hybrid/batch) |
| `get_patterns` | RETRIEVE | Get patterns relevant to current context |
| `search_patterns` | RETRIEVE | Semantic search for patterns |
| `list_patterns` | RETRIEVE | List all learned patterns |
| `get_session_context` | RETRIEVE | Get high-confidence behavioral patterns for session |
| `rate_pattern` | RATE | Confirm or reject a pattern (action="confirm"/"reject") |
| `get_stats` | MAINTAIN | Get engine statistics and auto-confirm candidates |
| `run_decay` | MAINTAIN | Run confidence decay (dry_run=True to preview) |
| `check_before_acting` | PRE-CHECK | Check for learned patterns before taking an action |
| `check_conflicts` | PRE-CHECK | Find conflicts between patterns (type="true"/"context_scoped"/"all") |
| `resolve_conflict` | PRE-CHECK | Resolve a conflict between two patterns (confidence/recency/suppress) |
| `mark_pattern_applied` | TRACK | Mark pattern as applied (tracks for auto-confirmation) |

### CLI

```bash
# Record a correction
pattern-memory record "used 85%" "use 80%" --context "image processing"

# Get patterns for context
pattern-memory get "image processing threshold"

# See all patterns
pattern-memory list

# Check stats
pattern-memory stats
```

## Architecture

- **SQLite** — Stores pattern metadata, correction history, confidence scores
- **ChromaDB** — Stores pattern embeddings for semantic search
- **MCP Protocol** — Standard interface for any MCP-compatible agent

## Tech Stack

- Python 3.11+
- MCP SDK (FastMCP)
- ChromaDB (vector search)
- SQLite (metadata)

## Tests

```bash
cd pattern-memory
python3 -m pytest tests/ -v
```

All 68 tests pass:
- 6 core logic tests (detection, scoring, classification, confidence, v2 structural)
- 5 storage/engine tests (roundtrip, corrections, record/retrieve, reject, duplicate matching)
- 1 MCP integration test (full protocol flow with real server, 13-tool surface)
- 4 self-correction tests (check_before_acting, get_session_context, with patterns)
- 4 decay tests (stale removal, dry run, recent skip, preview)
- 6 auto-confirmation tests (mark applied, auto-confirm, already confirmed, corrected after, get candidates, check correction)
- 8 LLM-based detection tests (no client fallback, hybrid weighting, ambiguous cases, batch detection)
- 13 conflict detection tests (opposition pairs, thresholds, conflict detection, resolution strategies, engine integration)
- 7 context-scoped conflict tests (context extraction, overlap detection, context-scoped vs true conflicts, classified conflicts, engine integration)
- 5 auto-apply tests (empty, confidence filter, dry run, marks applied, skips conflicts)
- 1 confidence ceiling test (auto-confirm caps at 0.7)
- 2 opposition-aware duplicate detection tests (skips opposing patterns, opposing corrections create separate conflict-detectable patterns)
- 1 Phase 2 action-text fallback merge test (same corrected action merges despite different original text)
- 4 singleton guard tests (first startup, rejects duplicate, cleans stale PID, shutdown cleanup)
- 1 self-healing storage test (stale ChromaDB handle recovery)

## Status

- [x] Core pattern engine (detection, classification, confidence)
- [x] SQLite + ChromaDB dual storage
- [x] MCP server with 13 consolidated tools
- [x] 68/68 tests passing
- [x] MCP protocol integration verified
- [x] CLI with entry points
- [x] pyproject.toml packaging
- [x] Confidence trap fix (auto-confirm ceiling at 0.7)
- [x] datetime.utcnow() deprecation fix
- [x] Tool consolidation (24 → 13)
- [x] Conflict resolution via MCP
- [x] Phase 2 duplicate detection (action-text fallback merge)
- [x] Singleton guard (PID file, duplicate instance prevention)
- [x] Self-healing storage layer (stale ChromaDB handle recovery)
- [ ] Cross-tool portability
- [ ] Team sharing
- [ ] Web UI

## Version History

- **v0.13.0** (2026-06-25) — Phase 2 duplicate detection (action-text fallback merge), singleton PID guard, self-healing ChromaDB storage, 68/68 tests
- **v0.12.0** (2026-06-25) — Opposition-aware duplicate detection: opposing corrections no longer merge, 62/62 tests
- **v0.11.0** (2026-06-25) — Added `resolve_conflict` MCP tool (12→13 tools), 60/60 tests
- **v0.10.0** (2026-06-24) — Tool consolidation (24→12), 60/60 tests
- **v0.9.0** (2026-06-24) — Confidence trap fix, datetime deprecation fix, MCP deployment, 60/60 tests
- **v0.8.0** (2026-06-24) — Context-scoped conflicts: `get_context_scoped_conflicts`, `get_all_conflicts_classified`, 53/53 tests
- **v0.7.0** (2026-06-24) — Pattern conflict detection & resolution: `get_conflicts`, `resolve_conflict`, 47/47 tests
- **v0.6.0** (2026-06-24) — LLM-based correction detection: hybrid approach, 18 tools, 34/34 tests
- **v0.5.0** (2026-06-24) — Auto-confirmation: `mark_pattern_applied`, `auto_confirm_pattern`, 25/25 tests
- **v0.4.0** (2026-06-24) — Confidence decay: `run_decay`, `preview_decay`, 20/20 tests
- **v0.3.0** (2026-06-24) — Self-correction tools: `check_before_acting`, `get_session_context`
- **v0.2.0** (2026-06-24) — MCP integration test, packaging fixes
- **v0.1.0** (2026-06-24) — Initial build
