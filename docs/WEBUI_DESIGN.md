# Sentinel WebUI — Architecture & Implementation Design

> **Author:** Hermes  
> **Date:** 2026-07-16  
> **Status:** Design Phase (OpenCode is auditing main code — no changes there)  
> **Phase:** 7.1 of TODO.md

---

## 1. What We're Building

A web-based dashboard for Sentinel that turns the CLI-only experience into an
interactive, visual platform. The WebUI wraps the existing Python core — it does
NOT rewrite or replace any of it. Every operation the WebUI performs maps to an
existing Sentinel API call.

### 1.1 Why a WebUI Matters (Commercial Angle)

The current CLI is powerful but invisible. For a SaaS play (Tier 2-3 of the
adamsims.dev plan), the WebUI is the product surface:

- **Audit-in-a-Box (Tier 2):** Client uploads agent config → WebUI runs
  Sentinel scenarios → generates branded HTML report → downloadable PDF.
- **Web Service (Tier 3):** Continuous monitoring dashboard. Agent tests run
  on schedule, WebUI shows trend lines, regression alerts, chaos impact scores.
- **Demo:** A live dashboard is 10x more compelling in a sales call than
  `sentinel run --verbose` output.

### 1.2 Design Principles

1. **Thin wrapper, thick core.** The WebUI adds ZERO new logic. It calls
   `ScenarioRunner`, `build_regression_report`, `generate_html_report`, etc.
2. **Resolution-independent.** All layouts use CSS Grid + relative units.
   Matches Adam's preference for screen-ratio-based placement.
3. **Dark theme default.** Matches the existing HTML report aesthetic
   (`#0d1117` background, `#58a6ff` accent). Light mode as optional toggle.
4. **Progressive enhancement.** Core views work without JS (SSR). Live
   streaming and interactive chaos builder add JS on top.
5. **No external CDN deps.** Self-contained. Works offline, behind firewalls,
   in air-gapped environments. All CSS/JS bundled.

---

## 2. Technology Stack

### 2.1 Backend: FastAPI

**Why FastAPI:**
- Native async → perfect for SSE streaming and long-running test scenarios
- Pydantic models integrate directly with Sentinel's dataclasses (auto-convert)
- Built-in OpenAPI/Swagger → auto-docs for the API
- Python ecosystem → no context-switching from Sentinel core
- Uvicorn is battle-tested for production

**Structure:**
```
src/sentinel/web/
├── __init__.py
├── app.py              # FastAPI app factory
├── server.py           # Uvicorn entry point (sentinel serve)
├── api/
│   ├── __init__.py
│   ├── scenarios.py    # CRUD + run scenarios
│   ├── runs.py         # Test run history, results, streaming
│   ├── baselines.py    # Baseline management
│   ├── reports.py      # Report generation & download
│   ├── chaos.py        # Chaos config builder API
│   ├── models.py       # Model endpoint management
│   └── ws.py           # WebSocket/SSE endpoints
├── schemas/
│   ├── __init__.py
│   ├── scenario.py     # Pydantic models for API request/response
│   ├── run.py
│   ├── baseline.py
│   └── report.py
├── services/
│   ├── __init__.py
│   ├── runner_service.py   # Wraps ScenarioRunner
│   ├── baseline_service.py # Wraps baseline module
│   ├── report_service.py   # Wraps reporting module
│   └── stream_service.py   # SSE event broadcasting
└── static/             # Frontend assets (built or hand-written)
    ├── index.html
    ├── css/
    │   └── sentinel.css
    ├── js/
    │   ├── app.js       # Main SPA router
    │   ├── dashboard.js
│   │   ├── scenarios.js
│   │   ├── runs.js
│   │   ├── traces.js
│   │   ├── baselines.js
│   │   ├── chaos-builder.js
│   │   └── streaming.js
    └── img/
        └── sentinel-logo.svg
```

### 2.2 Frontend: Vanilla JS + CSS Grid (No Framework)

**Why not React/Vue/Svelte:**
- Sentinel is a Python project. Adding a JS build step (npm, webpack, vite)
  creates a dependency wall that slows iteration.
- The UI is data-dense but not interactions-heavy. It's dashboards, tables,
  and config forms — not a rich interactive app.
- Vanilla JS with a thin router is ~500 lines. A React app would be 3000+.
- Zero build step = `sentinel serve` works from a fresh clone with no npm.

**If we outgrow vanilla:** Migrate to htmx + Hyperscript (server-rendered
partials, no build step, progressive enhancement). This is the escape hatch.

**CSS approach:**
- CSS Custom Properties for theming (dark/light)
- CSS Grid for page layout (sidebar + main content)
- No utility framework (Tailwind) — hand-written, <2000 lines, optimized
- Consistent with existing `_HTML_STYLE` in reporting.py

### 2.3 Communication Layer

```
┌─────────────┐     HTTP/REST      ┌──────────────┐
│   Browser    │ ◄──────────────── │   FastAPI     │
│  (Frontend)  │     SSE Stream    │  (Backend)    │
│              │ ◄──────────────── │              │
└─────────────┘                    └──────┬───────┘
                                          │
                                   ┌──────▼───────┐
                                   │  Sentinel     │
                                   │  Core Modules │
                                   │  (runner,     │
                                   │   chaos,      │
                                   │   reporting)  │
                                   └──────────────┘
```

- **REST API** for CRUD operations, starting runs, fetching results
- **Server-Sent Events (SSE)** for live log streaming during test execution
- **No WebSockets** (simpler, sufficient for unidirectional server→client)
- SSE endpoint: `GET /api/runs/{run_id}/stream`

---

## 3. API Design

### 3.1 Scenarios

```
GET    /api/scenarios                    # List all discovered scenarios
GET    /api/scenarios/{id}               # Get scenario details
POST   /api/scenarios                    # Create/save a scenario
PUT    /api/scenarios/{id}               # Update a scenario
DELETE /api/scenarios/{id}               # Delete a scenario
POST   /api/scenarios/{id}/run           # Start a test run
```

**Key insight:** Scenarios are currently YAML files on disk. The WebUI can:
1. Read them directly (file system API) — simplest for local dev
2. Store them in a lightweight SQLite DB — better for SaaS/multi-user

For Phase 7.1, we go with option 1 (file system). SQLite migration is
a Phase 7.2 concern.

### 3.2 Runs

```
GET    /api/runs                         # List recent runs (paginated)
GET    /api/runs/{run_id}                # Get run details + results
DELETE /api/runs/{run_id}                # Delete a run
GET    /api/runs/{run_id}/stream         # SSE: live logs during execution
GET    /api/runs/{run_id}/trace          # Full AgentTrace for visualization
```

**Run lifecycle:**
```
QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED
```

### 3.3 Baselines

```
GET    /api/baselines                    # List all baselines
GET    /api/baselines/{label}            # Get baseline details + results
POST   /api/baselines                    # Record a new baseline
DELETE /api/baselines/{label}            # Delete a baseline
GET    /api/baselines/{label}/diff/{label2}  # Compare two baselines
```

### 3.4 Reports

```
GET    /api/reports/{baseline}/html      # Download HTML report
GET    /api/reports/{baseline}/junit     # Download JUnit XML
GET    /api/reports/compare/{b1}/{b2}/html  # Regression diff report
```

### 3.5 Chaos Builder

```
GET    /api/chaos/presets                 # List chaos presets
GET    /api/chaos/injectors               # List available injectors + params
POST   /api/chaos/preview                 # Preview chaos config as YAML
POST   /api/chaos/validate                # Validate chaos config
```

### 3.6 Model Endpoints

```
GET    /api/models                        # List configured model endpoints
POST   /api/models                        # Add a model endpoint
DELETE /api/models/{id}                   # Remove a model endpoint
POST   /api/models/{id}/test             # Test connection to model
```

**Model endpoint config (stored in sentinel-web.yaml):**
```yaml
endpoints:
  - id: openai-gpt4
    provider: openai
    model: gpt-4
    api_key_env: OPENAI_API_KEY    # Never store keys directly
    base_url: null
  - id: anthropic-claude
    provider: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
  - id: local-ollama
    provider: openai_compatible
    model: llama3
    base_url: http://localhost:11434/v1
    api_key: "ollama"              # Local, no real key needed
```

---

## 4. Frontend Design

### 4.1 Layout

```
┌──────────────────────────────────────────────────────────┐
│  ◉ SENTINEL    [Dashboard] [Scenarios] [Runs] [Baselines]│
│  v0.1.0                        [Chaos] [Settings]        │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │                                                     │ │
│  │              MAIN CONTENT AREA                      │ │
│  │                                                     │ │
│  │  (switches based on nav selection)                  │ │
│  │                                                     │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Live Log Console (collapsible, shows during runs)   │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### 4.2 Page Designs

#### Dashboard (Home)
```
┌─────────────────────────────────────────────────────┐
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ Scenarios│ │  Pass    │ │  Fail    │ │ Chaos  │ │
│  │    12    │ │    9     │ │    3     │ │ Score  │ │
│  └──────────┘ └──────────┘ └──────────┘ │  87%   │ │
│                                          └────────┘ │
│                                                     │
│  Recent Runs                                        │
│  ┌─────────────────────────────────────────────────┐ │
│  │ 2026-07-16 14:32  ✓ 9/12 pass  1.2s  baseline │ │
│  │ 2026-07-16 14:28  ✗ 7/12 pass  2.1s  (regress)│ │
│  │ 2026-07-16 12:00  ✓ 12/12 pass 0.8s  nightly  │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  Pass/Fail Trend (last 10 runs)                     │
│  ┌─────────────────────────────────────────────────┐ │
│  │  ██████████████████████████░░░░░░░░░░░░░░░░░░░ │ │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░ │ │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░ │ │
│  │  Run1  Run2  Run3  Run4  Run5  Run6  Run7  Run8│ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
└─────────────────────────────────────────────────────┘
```

#### Scenarios Page
```
┌─────────────────────────────────────────────────────┐
│  Scenarios                          [+ New Scenario] │
│                                                     │
│  Filter: [All] [basic] [chaos] [governance]         │
│                                                     │
│  ┌─────────────────────────────────────────────────┐ │
│  │ search-basic-001                                │ │
│  │ Basic search agent                              │ │
│  │ Tags: basic, search, smoke-test                 │ │
│  │ [Run ▶] [Edit ✎] [Delete ✗]                    │ │
│  ├─────────────────────────────────────────────────┤ │
│  │ refund-timeout-002                              │ │
│  │ Refund agent handles timeout                    │ │
│  │ Tags: chaos, timeout, refund                    │ │
│  │ [Run ▶] [Edit ✎] [Delete ✗]                    │ │
│  ├─────────────────────────────────────────────────┤ │
│  │ cascade-db-api-003                              │ │
│  │ Cascading failure: DB → API → UI                │ │
│  │ Tags: chaos, cascade, production                │ │
│  │ [Run ▶] [Edit ✎] [Delete ✗]                    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
└─────────────────────────────────────────────────────┘
```

#### Scenario Editor (YAML + Visual)
```
┌─────────────────────────────────────────────────────┐
│  Edit Scenario: search-basic-001                    │
│                                                     │
│  ┌─── YAML Editor ────────────┐ ┌── Preview ──────┐ │
│  │ id: search-basic-001       │ │ ID: search-...   │ │
│  │ name: Basic search agent   │ │ Name: Basic...   │ │
│  │ description: Agent ...     │ │ Task: Search ... │ │
│  │ task: "Search for..."      │ │ Timeout: 30s     │ │
│  │ env_config:                │ │ Assertions: 3    │ │
│  │   tools:                   │ │                  │ │
│  │     search:                │ │ ┌─ Env ────────┐ │ │
│  │       response:            │ │ │ search: ✓    │ │ │
│  │         results:           │ │ │ db: ✗        │ │ │
│  │           - "Refund..."    │ │ └──────────────┘ │ │
│  │ tags:                      │ │                  │ │
│  │   - basic                  │ │ Chaos: None      │ │
│  │ timeout_seconds: 30        │ │                  │ │
│  └────────────────────────────┘ └──────────────────┘ │
│                                                     │
│  Model Endpoint: [OpenAI GPT-4 ▾] [Test Connection] │
│                                                     │
│  [Save] [Run ▶] [Cancel]                            │
└─────────────────────────────────────────────────────┘
```

#### Run Detail / Trace View
```
┌─────────────────────────────────────────────────────┐
│  Run: 2026-07-16 14:32:01              [▶ Re-run]   │
│  Duration: 1.2s  Scenarios: 12  Pass: 9  Fail: 3    │
│                                                     │
│  ┌─ Timeline ─────────────────────────────────────┐ │
│  │ Step 1 ─── search() ──── ✓ 12ms               │ │
│  │ Step 2 ─── db.query() ── ✓ 45ms               │ │
│  │ Step 3 ─── search() ──── ✗ TIMEOUT 5000ms     │ │
│  │         ↳ Chaos: ToolFailureInjector           │ │
│  │ Step 4 ─── search() ──── ✓ 8ms (retry)        │ │
│  │ Step 5 ─── respond() ── ✓ 2ms                 │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ Assertions ───────────────────────────────────┐ │
│  │ ✓ tool_called("search")                        │ │
│  │ ✓ no_tool_errors                               │ │
│  │ ✗ latency("db.query", max_ms=50) — was 45ms   │ │
│  │   (within threshold but chaos added +200ms)    │ │
│  │ ✓ graceful_degradation                         │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ State Changes ────────────────────────────────┐ │
│  │ cart.total: $0 → $29.99 (step 2)              │ │
│  │ cart.total: $29.99 → $29.99 (step 4, stable)  │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
└─────────────────────────────────────────────────────┘
```

#### Baselines & Diff View
```
┌─────────────────────────────────────────────────────┐
│  Baselines                                          │
│                                                     │
│  ┌─────────────────────────────────────────────────┐ │
│  │ v1.2.3   12 scenarios  10 pass  2 fail         │ │
│  │          Git: a1b2c3d4 (main)  2026-07-15      │ │
│  │          [Compare ▶] [Show] [Delete]            │ │
│  ├─────────────────────────────────────────────────┤ │
│  │ v1.3.0   12 scenarios  11 pass  1 fail         │ │
│  │          Git: e5f6g7h8 (main)  2026-07-16      │ │
│  │          [Compare ▶] [Show] [Delete]            │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  Comparing v1.2.3 → v1.3.0:                        │
│  ┌─────────────────────────────────────────────────┐ │
│  │ Verdict: PASS (1 fix, 0 regressions)           │ │
│  │                                                 │ │
│  │ ✓ refund-timeout-002    NEW_PASS (was failing)  │ │
│  │   Fixed: latency("api")                        │ │
│  │                                                 │ │
│  │ ✓ search-basic-001      STILL_PASS             │ │
│  │   Duration: 120ms → 98ms (-18%)                │ │
│  │                                                 │ │
│  │ ✗ cascade-db-api-003    STILL_FAIL             │ │
│  │   Failed: no_silent_failure (unchanged)        │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
└─────────────────────────────────────────────────────┘
```

#### Chaos Configuration Builder
```
┌─────────────────────────────────────────────────────┐
│  Chaos Configuration Builder                        │
│                                                     │
│  Preset: [Production Incident ▾] [Deploy Friday ▾]  │
│          [Traffic Spike ▾] [Custom]                 │
│                                                     │
│  ┌─ Tool Failures ─────────────────────────────────┐ │
│  │ ☑ Enable ToolFailureInjector                    │ │
│  │   Tool: [search ▾]  Type: [timeout ▾]          │ │
│  │   Probability: ──●────────── 30%                │ │
│  │   Seed: [42] (deterministic)                    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ Context Degradation ───────────────────────────┐ │
│  │ ☑ Enable ContextDegradation                     │ │
│  │   Strategy: (●) Truncation ( ) Noise ( ) Drift  │ │
│  │   Max tokens: [4096]                            │ │
│  │   Curve: Quadratic (auto)                       │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ Cascading Failures ────────────────────────────┐ │
│  │ ☐ Enable CascadingFailures                      │ │
│  │   [Configure dependency graph...]               │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ Spec Drift ────────────────────────────────────┐ │
│  │ ☐ Enable SpecDrift                              │ │
│  │   Intensity: [Subtle ▾]                         │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  Budget: Max [10] failures per run                  │
│                                                     │
│  ┌─ Preview ───────────────────────────────────────┐ │
│  │ YAML output (read-only, auto-generated):        │ │
│  │ chaos:                                          │ │
│  │   tool_failure:                                 │ │
│  │     tool_name: search                           │ │
│  │     failure_type: timeout                       │ │
│  │     probability: 0.3                            │ │
│  │   context_degradation:                          │ │
│  │     strategy: TRUNCATION                        │ │
│  │     max_context_tokens: 4096                    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  [Apply to Scenario] [Export YAML] [Cancel]         │
└─────────────────────────────────────────────────────┘
```

#### Settings / Model Endpoints
```
┌─────────────────────────────────────────────────────┐
│  Settings                                           │
│                                                     │
│  ┌─ Model Endpoints ───────────────────────────────┐ │
│  │                                                  │ │
│  │ OpenAI GPT-4                                     │ │
│  │ Provider: openai  Model: gpt-4                   │ │
│  │ API Key: ●●●●●●●● (from env: OPENAI_API_KEY)    │ │
│  │ Status: ✓ Connected  Latency: 230ms             │ │
│  │ [Test] [Edit] [Remove]                           │ │
│  │                                                  │ │
│  │ Anthropic Claude                                 │ │
│  │ Provider: anthropic  Model: claude-sonnet-4-...  │ │
│  │ API Key: ●●●●●●●● (from env: ANTHROPIC_API_KEY) │ │
│  │ Status: ✓ Connected  Latency: 180ms             │ │
│  │ [Test] [Edit] [Remove]                           │ │
│  │                                                  │ │
│  │ Local Ollama                                     │ │
│  │ Provider: openai_compatible  Model: llama3       │ │
│  │ Base URL: http://localhost:11434/v1              │ │
│  │ Status: ✗ Unreachable                           │ │
│  │ [Test] [Edit] [Remove]                           │ │
│  │                                                  │ │
│  │ [+ Add Endpoint]                                 │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ General ───────────────────────────────────────┐ │
│  │ Scenario Directory: [/path/to/scenarios]  [Browse]│
│  │ Baseline Directory: [/path/to/baselines]  [Browse]│
│  │ Auto-save runs: [✓]                             │ │
│  │ Default timeout: [30s]                           │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 5. Live Streaming Architecture

This is the most technically interesting part. When a user clicks "Run" on a
scenario, they should see logs, spans, and assertions appearing in real-time.

### 5.1 SSE Event Flow

```
Browser                          FastAPI                    ScenarioRunner
  │                                │                            │
  │── POST /api/scenarios/X/run ──►│                            │
  │                                │── start_background_task ──►│
  │◄── 202 Accepted {run_id} ──────│                            │
  │                                │                            │
  │── GET /api/runs/X/stream ─────►│                            │
  │   (SSE connection)             │                            │
  │                                │                            │
  │                                │◄── on_step_complete ───────│
  │◄── event: step ────────────────│                            │
  │    data: {"step":1,"tool":"search",...}                     │
  │                                │                            │
  │                                │◄── on_tool_call ───────────│
  │◄── event: tool_call ───────────│                            │
  │    data: {"tool":"db.query",...}│                            │
  │                                │                            │
  │                                │◄── on_assertion ───────────│
  │◄── event: assertion ───────────│                            │
  │    data: {"name":"tool_called",...}                          │
  │                                │                            │
  │                                │◄── on_complete ────────────│
  │◄── event: complete ────────────│                            │
  │    data: {"passed":9,"failed":3}                             │
  │                                │                            │
  │── close ──────────────────────►│                            │
```

### 5.2 Event Types

```python
class StreamEvent(StrEnum):
    RUN_STARTED = "run_started"       # Run begins
    SCENARIO_STARTED = "scenario_started"  # Individual scenario starts
    STEP = "step"                     # Execution step completed
    TOOL_CALL = "tool_call"           # Tool invocation (with timing)
    TOOL_ERROR = "tool_error"         # Tool failure (with chaos info)
    ASSERTION = "assertion"           # Assertion result (pass/fail)
    STATE_CHANGE = "state_change"     # State mutation detected
    ERROR = "error"                   # Error encountered
    SCENARIO_COMPLETED = "scenario_completed"  # Scenario finished
    RUN_COMPLETED = "run_completed"   # All scenarios finished
```

### 5.3 Implementation: EventBridge Pattern

The key challenge: Sentinel's ScenarioRunner doesn't have callback hooks for
live events. We need to inject them without modifying the core.

**Solution: Monkey-patch with callbacks**

```python
# services/runner_service.py

async def run_scenario_streaming(
    scenario: SentinelScenario,
    run_id: str,
    event_queue: asyncio.Queue,
) -> SentinelResult:
    """Run a scenario and push events to an SSE queue."""
    
    original_add_step = AgentTrace.add_step
    original_add_tool_call = AgentTrace.add_tool_call
    original_add_error = AgentTrace.add_error
    
    def patched_add_step(self, step):
        original_add_step(self, step)
        event_queue.put_nowait(StreamEvent(
            type="step",
            data={"step_id": step.step_id, "action": step.action.value,
                  "duration_ms": step.duration_ms}
        ))
    
    def patched_add_tool_call(self, call):
        original_add_tool_call(self, call)
        event_queue.put_nowait(StreamEvent(
            type="tool_call" if call.succeeded else "tool_error",
            data={"tool": call.tool_name, "duration_ms": call.duration_ms,
                  "error": call.error}
        ))
    
    # Apply patches for this run only (thread-local or context var)
    with patch_agent_trace_events(
        on_step=patched_add_step,
        on_tool_call=patched_add_tool_call,
    ):
        runner = ScenarioRunner()
        result = runner.run(scenario)
    
    return result
```

**Alternative (cleaner, Phase 7.2):** Add an optional `event_handler` parameter
to ScenarioRunner:

```python
# In sentinel/runner.py (future modification)
class ScenarioRunner:
    def __init__(self, event_handler: Callable | None = None):
        self.event_handler = event_handler
    
    def _emit(self, event_type: str, data: dict):
        if self.event_handler:
            self.event_handler(event_type, data)
```

This is the cleaner long-term approach but requires touching core code.
For Phase 7.1, the monkey-patch approach works without touching core.

---

## 6. Trace Visualization

The trace view is the "hero feature" — it turns raw AgentTrace data into an
interactive timeline.

### 6.1 Trace Data Structure

From `AgentTrace.to_dict()`, we get:
```json
{
  "total_steps": 5,
  "total_tool_calls": 3,
  "total_duration_ms": 1234.5,
  "tool_names_called": ["search", "db.query"],
  "failed_tool_calls": 1,
  "errors": 1,
  "state_changes": 2,
  "metadata": {}
}
```

But for the trace view, we need the full step-by-step data. The API returns:

```json
{
  "steps": [
    {
      "step_id": 1,
      "action": "tool_call",
      "tool_calls": [
        {
          "tool_name": "search",
          "arguments": {"query": "refund policy"},
          "result": {"results": ["..."]},
          "duration_ms": 12.3,
          "error": null
        }
      ],
      "duration_ms": 12.3,
      "error": null
    },
    {
      "step_id": 2,
      "action": "tool_call",
      "tool_calls": [
        {
          "tool_name": "db.query",
          "arguments": {"sql": "SELECT * FROM orders"},
          "result": null,
          "duration_ms": 5000.0,
          "error": "TimeoutError: query exceeded 5000ms"
        }
      ],
      "duration_ms": 5000.0,
      "error": {"message": "TimeoutError", "severity": "high"}
    }
  ],
  "state_changes": [
    {"key": "cart.total", "old_value": 0, "new_value": 29.99, "step_id": 2}
  ]
}
```

### 6.2 Timeline Visualization (CSS-based, no D3)

```
Step 1  ████░░░░░░░░░░░░░░░░░░░░░░░░  12ms   search()
Step 2  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░  2ms    reason()
Step 3  ████████████████████████████░░  5000ms db.query() ✗ TIMEOUT
        └─ Chaos: ToolFailureInjector (probability: 0.3)
Step 4  ███░░░░░░░░░░░░░░░░░░░░░░░░░░  8ms    search() (retry)
Step 5  █░░░░░░░░░░░░░░░░░░░░░░░░░░░░  2ms    respond()
```

Bar width proportional to duration (log scale for readability).
Colors: green=pass, red=fail, blue=tool call, gray=reasoning.

---

## 7. Implementation Plan

### Phase 7.1: Core WebUI (Week 1-2)

**Goal:** Functional dashboard with run/stop, results viewing, baseline diff.

| Task | Est. Time | Dependencies |
|------|-----------|-------------|
| FastAPI app skeleton + static file serving | 2h | None |
| API: Scenarios CRUD (read YAML files) | 3h | Skeleton |
| API: Run scenario (background task) | 4h | Scenarios API |
| API: SSE streaming endpoint | 3h | Run API |
| Frontend: Layout + router | 3h | Skeleton |
| Frontend: Dashboard page | 3h | Layout |
| Frontend: Scenarios list + run button | 2h | Scenarios API |
| Frontend: Run detail + trace timeline | 4h | Run API + SSE |
| Frontend: Live log console | 2h | SSE |
| Integration testing | 2h | All above |
| **Total** | **~28h** | |

### Phase 7.2: Baselines & Reports (Week 3)

| Task | Est. Time |
|------|-----------|
| API: Baselines CRUD + diff | 4h |
| Frontend: Baselines page + diff view | 4h |
| Frontend: Report download (HTML/JUnit) | 2h |
| Frontend: Baseline comparison visual diff | 3h |
| **Total** | **~13h** |

### Phase 7.3: Chaos Builder (Week 4)

| Task | Est. Time |
|------|-----------|
| API: Chaos presets + injectors metadata | 3h |
| Frontend: Chaos config builder (interactive form) | 6h |
| Frontend: Chaos YAML preview + apply to scenario | 3h |
| **Total** | **~12h** |

### Phase 7.4: Model Endpoints & Settings (Week 5)

| Task | Est. Time |
|------|-----------|
| API: Model endpoint CRUD + test connection | 3h |
| Frontend: Settings page | 3h |
| Integration: Route scenarios to selected model | 4h |
| **Total** | **~10h** |

---

## 8. CLI Integration

The WebUI adds a new CLI command:

```bash
# Start the WebUI server
sentinel serve [--port 8080] [--host 0.0.0.0] [--reload]

# Or as a module
python -m sentinel.web.server --port 8080
```

The existing CLI commands continue to work unchanged. The WebUI is additive.

---

## 9. File Structure Changes

New files (NO existing files modified for Phase 7.1):

```
src/sentinel/web/              # NEW directory
├── __init__.py
├── app.py
├── server.py
├── api/
│   ├── scenarios.py
│   ├── runs.py
│   ├── baselines.py
│   ├── reports.py
│   ├── chaos.py
│   ├── models.py
│   └── events.py             # SSE event types
├── schemas/
│   ├── scenario.py
│   ├── run.py
│   ├── baseline.py
│   └── report.py
├── services/
│   ├── runner_service.py
│   ├── baseline_service.py
│   ├── report_service.py
│   └── stream_service.py
└── static/
    ├── index.html
    ├── css/sentinel.css
    └── js/
        ├── app.js
        ├── router.js
        ├── api.js
        ├── dashboard.js
        ├── scenarios.js
        ├── runs.js
        ├── traces.js
        ├── baselines.js
        ├── chaos-builder.js
        ├── settings.js
        └── streaming.js

pyproject.toml                 # MODIFY: add [web] optional deps
README.md                      # MODIFY: add WebUI section
docs/WEBUI.md                  # NEW: user-facing docs
tests/sentinel/web/            # NEW: web API tests
```

**pyproject.toml changes:**
```toml
[project.optional-dependencies]
web = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "sse-starlette>=2.0.0",
]
```

---

## 10. Security Considerations

1. **No API keys in responses.** Model endpoint configs show `●●●●●●●●` for
   keys. Keys are loaded from environment variables, never stored in the
   sentinel-web.yaml.

2. **Local-only by default.** `sentinel serve` binds to `127.0.0.1` (not
   `0.0.0.0`). Must explicitly pass `--host 0.0.0.0` for network access.

3. **No auth in Phase 7.1.** This is a local dev tool. Auth is a Phase 7.5
   concern when the Web Service (Tier 3) goes live.

4. **File system access.** Scenarios and baselines are read from the local
   file system. The WebUI can only access files the running user can access.

5. **CSRF protection.** FastAPI handles this via SameSite cookies for any
   state-changing operations.

---

## 11. Testing Strategy

1. **API tests** (pytest + httpx): Test every endpoint with mock ScenarioRunner
2. **E2E tests** (pytest + Playwright): Full browser automation for critical paths
3. **SSE tests**: Verify event ordering and completeness during mock runs
4. **No snapshot tests**: Too fragile. Visual regression is manual for now.

---

## 12. Future Considerations (Phase 7.5+)

- **Authentication:** JWT or session-based for multi-user SaaS
- **SQLite storage:** Replace file-system-based scenario/baseline storage
- **WebSocket upgrade:** If bidirectional communication needed (e.g., cancel runs)
- **Plugin system:** Let users add custom dashboard widgets
- **Embeddable:** `<iframe>` or web component for embedding in other tools
- **API versioning:** `/api/v1/` prefix when breaking changes needed

---

## Appendix A: Existing Sentinel API Surface (What We Wrap)

| Sentinel Module | Key Classes/Functions | WebUI Maps To |
|----------------|----------------------|---------------|
| `runner.py` | `ScenarioRunner.run()`, `SentinelScenario` | `/api/runs`, `/api/scenarios` |
| `reporting.py` | `build_regression_report()`, `generate_html_report()` | `/api/reports` |
| `baseline.py` | `record_baseline()`, `load_baseline()`, `list_baselines()` | `/api/baselines` |
| `chaos.py` | `ToolFailureInjector`, `ContextDegradation`, etc. | `/api/chaos` |
| `models.py` | `AgentTrace`, `ToolCall`, `Step`, `StateChange` | Trace visualization |
| `cli.py` | `run`, `list`, `info`, `baseline`, `diff`, `report` | All API endpoints |
| `assertions.py` | 20+ assertion functions | Assertion results display |
| `otel.py` | `OTelSpan` model | Span visualization (future) |
