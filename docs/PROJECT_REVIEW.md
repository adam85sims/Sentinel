# Sentinel — Project Review

> **Reviewer:** Hermes (GLM-5.2 via OpenCode Go)
> **Date:** 2026-07-07
> **Scope:** Full review of autonomous sprint output — code, tests,
> governance, framework robustness, and commercial viability.

---

## 1. What Was Built

The autonomous agent (Nexus-Strategist persona, Mimo V2.5) started with a
directive to research the AI/AGI landscape, identify a commercial gap, and
build a proof-of-concept. In a single day it went from blank folder to a
10-phase platform.

The application is **Sentinel** — an Agent Behavioral Testing Platform. The
thesis: 88% of AI agents fail in production, and the dominant failure modes
are operational (tool errors 28%, memory/state 22%, edge cases 18%), NOT
hallucination (12%). Yet the entire evaluation ecosystem (DeepEval, LangSmith,
MS AGT) focuses on output quality or observability — nobody tests agent
BEHAVIOR in production-like environments before deployment. Sentinel fills
that gap.

## 2. By the Numbers

| Metric | Value |
|--------|-------|
| Source code | 7,176 lines (14 Python files) |
| Test code | 6,949 lines (17 test files) |
| Governance code | 1,517 lines (6 Python files) |
| Tests passing | 561 (verified 2026-07-07, 0 failures) |
| Phases completed | 10 of 10 |
| TODO items | 13/13 done, queue empty, nothing blocked |

## 3. Module Breakdown

### 3.1 env.py (1,033 lines)

MockTool with latency simulation, error injection (one-shot and
probability-based), and call recording. MockAPI with REST + GraphQL route
matching (exact, regex `~^/pattern$`, wildcard `*`), per-route latency, error
injection, and sliding-window rate limiting. MockDatabase with CRUD
operations, WHERE filtering, auto-table-creation, query interception, and
error/latency simulation. EnvironmentBuilder fluent API composing all three
into a test environment.

### 3.2 chaos.py (1,318 lines) — the standout module

- **ToolFailureInjector** — timeout, error, rate_limit, malformed, partial
  failures with probability-based and timeline-based injection, deterministic
  seeding.
- **LLMFailureInjector** — rate_limit, timeout, partial_response,
  stream_interrupt at the step level.
- **ContextDegradation** — three strategies (TRUNCATION, NOISE, DRIFT) with a
  quadratic acceleration curve. The quadratic curve is elegant: it matches how
  context window pressure actually works (the last 20% is much worse than the
  first 20%).
- **CascadingFailures** — multi-agent error propagation with configurable
  cascade probability, max depth, propagation delay, and dependency-graph
  heuristic (database → api_server → ui).
- **SpecDrift** — agent improvisation under pressure. Three intensity levels
  (subtle/moderate/aggressive) with drift probability amplifying on recent
  errors and cumulative drift score tracking.
- **ChaosBudget** — hard cap on total failures per test run, fluent API.
- Every injector includes `make_validator()` that plugs into
  `assert_no_silent_failure()` — clean wiring between chaos and assertions
  without module coupling.

### 3.3 assertions.py (840 lines)

20+ assertions across 5 categories:

| Category | Assertions |
|----------|-----------|
| Tool Call | called, not_called, call_order, call_count, no_tool_errors |
| State | consistent, changed, not_stale, consistent_across_traces, collision detection |
| Governance | permission_respected, permission_violated, allowlist, denylist, at_most, approval_before_action |
| Resilience | graceful_degradation, no_silent_failure |
| Performance | latency, token_usage, step_count, tool_latency |

### 3.4 runner.py (433 lines)

`@sentinel_test` decorator for declarative test definition. ScenarioRunner
builds environment from config, runs agent, executes assertions, returns
structured results. Supports JSON/YAML scenario loading and pytest discovery.
AgentConfig dataclass for agent instantiation.

### 3.5 cli.py (717 lines)

Full Click CLI: `run`, `list`, `info`, `baseline record/list/show/delete`,
`diff`, `report`, `trace`. JSON and human-readable output modes.

### 3.6 reporting.py (541 lines)

RegressionReport with ResultDelta enum (NEW_PASS, NEW_FAIL, STILL_PASS,
STILL_FAIL, NEW_SCENARIO, REMOVED). Structural trace diffing (detects new
tools, removed tools, call count deltas, error count changes). Self-contained
HTML reports with dark-theme inline CSS (no external deps, works offline).
JUnit XML generation for CI consumption.

### 3.7 otel.py (368 lines)

Lightweight OTelSpan model (no SDK dependency for core functionality).
Hierarchical trace-to-spans conversion (root → steps → tool calls). Optional
live OTLP export (gRPC + HTTP) when opentelemetry-sdk is installed.

### 3.8 baseline.py (371 lines)

JSON-based baseline storage with git SHA/branch auto-detection. Full
serialization round-trip for traces, tool calls, errors, state changes.
Human-readable and git-trackable.

### 3.9 adapters/ (910 lines total)

Four framework adapters, all using optional imports — sentinel works
standalone without any agent framework installed:

- **LangChain** (281 lines) — SentinelToolAdapter wraps BaseTool, wrap_agent
  replaces all tools with mocks, AgentWrapper delegates invoke/call.
- **CrewAI** (252 lines) — crew and task-level interception.
- **OpenAI Agents SDK** (295 lines) — function tool interception.
- **Generic** (382 lines) — hook-based adapter for custom agents.

### 3.10 CI/CD

GitHub Actions workflow with lint gate (ruff), Python 3.11/3.12/3.13 test
matrix with concurrency cancellation, sentinel scenario runner job, and
governance audit job with artifact upload. GitLab CI template
(`.sentinel-ci.yml`). Composite GitHub Action for reusable workflows.

## 4. Framework Stress Test Results

This project was designed to stress-test the automation framework itself, not
just build a product. The framework was exercised across every subsystem:

### 4.1 Pattern Memory MCP

17 tools verified (13 pattern + 4 infrastructure). Full lifecycle tested:
record correction → retrieve via check_before_acting and get_session_context →
mark applied → rate/confirm → check conflicts → run decay. Four corrections
recorded during the session. No conflicts detected (different contexts).

### 4.2 Governance Audit

The audit harness works correctly. Evidence collection is solid (test counts,
file stats, source counts). The deterministic comparator catches quantitative
mismatches reliably.

Five bugs were found and fixed in the governance pipeline:

1. **Test function regex** (evidence.py) — `^def test_` only matched at column
   0, missing all indented class methods. Fixed to `^\s*def test_`.
2. **Claims extractor patterns** (claims.py) — only matched "N/N tests" and
   "N tests passing". Added patterns for "N tests passed", "N passed", and "N
   tests" standalone.
3. **Claims extractor ordering** (claims.py) — multiple regex patterns
   produced claims in pattern-match order, not document order. Fixed by
   collecting all matches with positions and sorting chronologically.
4. **Tool count config** (agent-frameworks.yaml) — `mcp_server_file` was
   commented out, and the config system reads `agent-frameworks.yaml` (not
   `governance.yaml`) which didn't exist. Created the proper config file.
5. **LLM finding deduplication** (extract.py) — granite-4.1-3b emitted
   duplicate findings; `_has_finding()` checked "description" but LLM findings
   use "summary". Added dedup + fixed key check.

False claim injection test: fabricated diary numbers were correctly flagged as
2 CRITICALs. This proves the harness works when the model cooperates.

### 4.3 Governance Model

The fine-tuned governance-granite-4.1-3b model over-triggers — it hallucinates
"actual: 0" for test counts and file existence despite evidence showing
otherwise. Reverted to base granite-4.1-3b. This is a real empirical finding
about the fine-tune quality: the model needs more training data or a different
training approach before it can be trusted as the primary auditor.

### 4.4 Model Routing

Subagent delegation used successfully for CLI scaffolding. The 2-layer nesting
protocol was designed but not fully exercised (orchestrator → subagent →
worker chain was not tested in production).

### 4.5 Web Stack

crawl4ai + ChromaDB used for autonomous research. 30+ sources extracted and
synthesized into a 12k-word research document.

## 5. Strengths

1. **The chaos module is genuinely innovative.** ContextDegradation's quadratic
   curve, CascadingFailures' dependency graph, SpecDrift's intensity model —
   these simulate real production failure modes that no other tool tests. This
   is the commercial differentiator.

2. **The `make_validator()` pattern is clean architecture.** Chaos injectors
   produce validators that plug into assertions without coupling the modules.
   Good separation of concerns.

3. **The `__call__` descriptor bug discovery and fix.** Python resolves
   `__call__` on the TYPE, not the instance — monkey-patching
   `tool.__call__ = fn` on a dataclass instance is invisible. The
   `call_handler` field pattern is the correct fix. This is a real Python
   gotcha recorded in pattern memory.

4. **Rigorous TDD.** 561 tests, 0 failures. Test coverage includes edge cases
   (empty traces, errored calls, mixed allowed/forbidden scenarios, state
   collision detection).

5. **Optional-dependency design.** langchain-core, opentelemetry-sdk, and
   other heavy deps are optional. Sentinel is importable in minimal
   environments. Smart for adoption.

6. **Production-grade CI/CD.** Test matrix across Python 3.11/3.12/3.13,
   concurrency cancellation, artifact retention, governance as a CI gate.
   This is ready for a real GitHub repo.

## 6. Concerns and Gaps

### 6.1 No Real Agent Integration Test (HIGH PRIORITY)

Everything is tested with mock agents and mock tools. The adapters exist but
haven't been exercised against a real LangChain agent, a real CrewAI crew, or
a real OpenAI SDK agent. The unit tests prove the plumbing works, but the
thesis ("test agent behavior in production-like environments") hasn't been
demonstrated with an actual production agent. This is the gap between "proof
of concept" and "proof of value."

### 6.2 Tool Count Discrepancy

README says 13 MCP tools, .brain/memory.md says 17 tools (13 pattern + 4
infrastructure). The diary mentions both numbers. The governance audit flagged
this as a WARNING, which proves the audit works, but the discrepancy was never
resolved in the source files.

### 6.3 No Published Package

pyproject.toml exists with proper config, but sentinel isn't installable from
PyPI or a public git repo. For the OSS + Pro revenue model to work, this needs
to be publishable.

### 6.4 Incomplete Diary

The last diary entry (Phase 7+8) is truncated — it ends mid-sentence at "An
agent can now: 1. Run tests (Phase 1-3) → record results (Phase 7)". Phases 9
and 10 (adapters and CI/CD) have no diary entries at all. The governance audit
flags this as a WARNING (diary claims 295 tests, actual is 561).

### 6.5 Governance Model Unresolved

The fine-tuned governance-granite model was reverted to base, but the base
model also produced false positives before the 5 plumbing bugs were fixed. The
governance story needs a decision: improve the fine-tune with more training
data, commit to base granite + deterministic comparator as the primary
mechanism, or try a different model entirely.

### 6.6 No Examples Directory

The architecture doc shows clean usage examples, but there's no examples/
folder with runnable demos. For developer adoption, a quickstart script is
essential.

## 7. Verdict

For a single-day autonomous sprint, this is impressive output. The
research-to-product pipeline worked end-to-end: 30+ sources researched, gap
identified, architecture designed, 10 phases built and tested, CI/CD wired up,
governance framework exercised and debugged.

The framework itself passed its stress test. Pattern memory works, governance
catches real issues, model routing delegation functions, the web stack enabled
real research. The 5 governance bugs and the `__call__` descriptor bug are
exactly the kind of findings this project was designed to surface.

The commercial thesis is strong. The chaos module is the differentiator —
nobody else is doing context degradation simulation with quadratic curves and
cascading failure propagation graphs. If a real LangChain agent is put through
Sentinel and it catches a behavioral regression that DeepEval/LangSmith would
miss, that's the demo that sells it.
