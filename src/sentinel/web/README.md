# Sentinel WebUI

Browser-based dashboard for the Sentinel Agent Behavioral Testing Platform.

## Quick Start

```bash
# Install Sentinel with web dependencies
pip install "sentinel[web]"

# From the project root
pip install -e ".[web]"

# Start the server
sentinel serve
```

Open **http://localhost:8080** in your browser.

### Options

```bash
sentinel serve --host 127.0.0.1 --port 9090    # Custom host/port
sentinel serve --reload                         # Auto-reload on code changes

# Or run directly with uvicorn
uvicorn sentinel.web.app:create_app --host 127.0.0.1 --port 8080 --factory
```

## Pages

### Dashboard (`#/`)
Overview of your testing environment — total scenarios, recent pass/fail rate,
quick action buttons to jump to scenarios or runs.

### Scenarios (`#/scenarios`)
Browse all discovered scenario YAML/JSON files. Click a scenario to see its
full config (task, env, tags, timeout) and hit **Run** to execute it.

### Runs (`#/runs`)
All test runs, most recent first. Click a run to see:
- Step-by-step trace timeline (tool calls, durations, errors)
- Assertion results (pass/fail per assertion)
- State changes detected during execution

### Baselines (`#/baselines`)
Saved test results for comparison. Select two baselines and hit **Compare**
to see a regression diff — which scenarios improved, regressed, or stayed stable.

### Settings (`#/settings`)
Model endpoint configuration (OpenAI, Anthropic, local Ollama). General
settings for scenario/baseline directories.

## Architecture

```
src/sentinel/web/
├── app.py                 # FastAPI application factory
├── server.py              # Uvicorn entry point (sentinel serve)
├── api/
│   ├── scenarios.py       # GET /api/scenarios, GET /api/scenarios/{id}
│   ├── runs.py            # POST /api/runs, GET /api/runs, SSE stream
│   └── baselines.py       # GET /api/baselines, diff, delete
├── schemas/
│   ├── scenario.py        # Pydantic models for scenario requests/responses
│   ├── run.py             # Pydantic models for run requests/responses
│   └── baseline.py        # Pydantic models for baseline requests/responses
├── services/
│   ├── runner_service.py  # Wraps ScenarioRunner, manages run lifecycle
│   ├── baseline_service.py # Wraps baseline module
│   └── stream_service.py  # SSE event pub/sub for live streaming
└── static/
    ├── index.html          # SPA shell
    ├── css/sentinel.css    # Dark-theme stylesheet
    ├── img/sentinel-logo.svg
    └── js/
        ├── api.js          # API client (window.SentinelAPI)
        ├── router.js       # Hash-based SPA router
        ├── app.js          # Main orchestrator + nav management
        ├── dashboard.js    # Dashboard page
        ├── scenarios.js    # Scenario list + detail + run
        ├── runs.js         # Run list + detail
        ├── traces.js       # Trace timeline visualization
        ├── baselines.js    # Baselines + diff comparison
        ├── settings.js     # Settings page
        └── streaming.js    # SSE client + live log console
```

## How It Works

The WebUI is a **thin wrapper** around Sentinel's Python core. Every API
endpoint maps directly to an existing Sentinel function:

| WebUI API              | Sentinel Module         | Function                  |
|------------------------|-------------------------|---------------------------|
| `GET /api/scenarios`   | File system scan        | `discover_scenarios()`    |
| `POST /api/runs`       | `sentinel.runner`       | `ScenarioRunner.run()`    |
| `GET /api/runs`        | In-memory store         | `RunManager.list_runs()`  |
| `GET /api/baselines`   | `sentinel.baseline`     | `list_baselines()`        |
| `GET /api/baselines/…/diff/…` | `sentinel.reporting` | `build_regression_report()` |

No new logic is added. The WebUI just presents existing capabilities through
a visual interface.

## API Endpoints

### Scenarios
```
GET  /api/scenarios              List all discovered scenarios
GET  /api/scenarios/{id}         Get scenario detail
```

### Runs
```
POST /api/runs                   Start a new run (returns 202)
GET  /api/runs                   List all runs
GET  /api/runs/{id}              Get run detail + results
GET  /api/runs/{id}/stream       SSE: live events during execution
```

### Baselines
```
GET    /api/baselines                     List all baselines
GET    /api/baselines/{label}             Get baseline detail
DELETE /api/baselines/{label}             Delete a baseline
GET    /api/baselines/{a}/diff/{b}        Compare two baselines
```

### Health
```
GET  /api/health                 Health check (status + version)
```

## Development

### File Structure

The frontend is vanilla JS — no build step, no npm. Just edit files in
`static/` and refresh the browser. The server uses `--reload` for auto-reload.

### Adding a New Page

1. Create `static/js/mypage.js` with a `renderMyPage()` function
2. Add a route in `router.js`
3. Import it in `index.html`
4. Add the nav link in `index.html`

### Adding a New API Endpoint

1. Create or extend a router in `api/`
2. Add Pydantic schemas in `schemas/`
3. Add service logic in `services/`
4. Register the router in `app.py`

### Testing

```bash
# Run web API tests
pytest tests/sentinel/web/test_api.py -v

# Run all tests (includes web)
pytest tests/ -v
```

## Current Status

Phase 7.1 complete — core dashboard, run/stop, traces, live streaming
infrastructure, baseline management, and dark-theme UI all functional.

See the main [TODO.md](../../TODO.md) for the full phase roadmap.
