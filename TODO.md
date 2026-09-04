# Sentinel — Development Queue

> Phase 7 is currently pending.

## Rules

1. **Pick the first `[ ]` item** under "Pending" — do it, mark `[x]`, move to "Done"
2. **New items must be added to the TODO when discovered** — only add tasks you discovered from doing other tasks
3. **Exit ONLY when ANY of these is true:**
   - Queue is empty (all items done or blocked)
   - Audit shows CRITICAL — fix first, then re-audit, then stop
   - Blocker hit (needs user input) — mark blocked with explanation, write diary, stop
   - 2 phases completed this session (excellent work — finalize and stop)
   - Cannot continue quality work (repeated failures, unavailable resources)
4. **After completing each item, IMMEDIATELY move to the next** — do not stop, summarize, or ask what to do next
5. **New items go at the END of Pending** — unless you can argue they're higher priority
6. **Never mark something done without doing it** — the governance audit checks
7. **When the queue is near empty, self-seed** — find concrete issues in the codebase and add them

---

## Phase 1: Proof of Value (Real Agent Integration)

- [x] Install langchain-core and create a minimal LangChain agent (ReAct pattern, 2 tools)
- [x] Write integration test: run LangChain agent through Sentinel with mock environment
- [x] Inject a tool failure mid-run and verify Sentinel catches the behavioral regression
- [x] Write integration test: context degradation scenario with real LangChain agent
- [x] Create example script: `examples/langchain_quickstart.py` — runnable demo
- [x] Document integration test results in docs/INTEGRATION_TESTING.md

## Phase 2: Package & Distribution

- [x] Add MANIFEST.in or verify hatch build includes all necessary files
- [x] Create .gitignore (standard Python + sentinel-specific: reports/, .brain/, baselines/)
- [x] Verify `pip install -e .` works from clean state (no leftover deps)
- [x] Verify `pip install -e ".[all]"` installs all optional dependency groups
- [x] Add version bumping strategy (hatch version or manual)
- [x] Create GitHub repo and push initial commit (https://github.com/adam85sims/Sentinel)
- [x] Verify `pip install git+https://github.com/adam85sims/sentinel.git` works

## Phase 3: Documentation & Examples

- [x] Create docs/QUICKSTART.md — 5-minute guide from install to first test
- [x] Create docs/CHAOS_GUIDE.md — deep dive on chaos injection patterns
- [x] Create docs/ADAPTERS_GUIDE.md — how to write custom adapters
- [x] Create examples/basic_scenario.yaml — minimal YAML scenario
- [x] Create examples/chaos_scenario.yaml — chaos injection demo
- [x] Create examples/langchain_quickstart.py — runnable demo (created in Phase 1)
- [x] Update README.md with badges (CI, coverage, version)

## Phase 4: Governance Model Resolution

- [x] Document governance model options in docs/GOVERNANCE_DECISION.md
- [x] Option C: Pure deterministic comparator (selected as default)
- [x] Updated auditor.yaml to default to backend.type: "none"
- [x] Fixed auditor.py and extract.py for deterministic-only mode
- [x] Governance audit passes with deterministic comparator

## Phase 5: Polish & Edge Cases

- [x] Resolve tool count discrepancy (docs updated)
- [x] Add `__all__` exports to all modules
- [x] Create docs/API_REFERENCE.md from docstrings
- [x] Add edge case tests: empty scenarios, malformed YAML, missing tools

## Phase 6: Advanced Chaos (Differentiator Expansion)

- [x] Research additional production failure modes (network partitions, clock skew, memory pressure)
- [x] Implement NetworkPartition chaos injector
- [x] Implement ClockSkew chaos injector
- [x] Implement MemoryPressure chaos injector
- [x] Add chaos scenario presets (production incident, deploy Friday, traffic spike, etc.)
- [x] Write benchmark: Sentinel chaos vs real production logs (docs/CHAOS_BENCHMARK.md)

## Phase 7: WebUI & Next-Gen Features

- [ ] Design and implement a WebUI dashboard for Sentinel (running tests, viewing trace visualization, comparing baselines)
- [ ] Add model endpoint selector in the WebUI to point test runs at different LLMs/providers (OpenAI, Anthropic, local)
- [ ] Add interactive chaos configuration builder in the WebUI
- [ ] Implement live log/span streaming in WebUI using WebSockets or Server-Sent Events (SSE)
- [ ] Implement trace snapshot comparison diffing UI (visual git diff of baseline vs current run)
- [ ] Add a `pytest` plugin for native reporting and direct execution of YAML scenarios
- [ ] Add asynchronous chaos injection support for native async agent frameworks
- [ ] Implement built-in retry assertions (e.g., `assert_retried_after_failure(tool_name, max_retries=3)`)
- [ ] Implement Prometheus metrics exporter for CI/CD run dashboards

---

## Done

All 6 phases complete. 519 tests passing.

- [x] Phase 1: LangChain integration tests (16 tests)
- [x] Phase 2: Package & distribution (build, install, version bump)
- [x] Phase 3: Documentation & examples (3 guides, 2 scenarios, README)
- [x] Phase 4: Governance resolution (deterministic auditor)
- [x] Phase 5: Polish (__all__ exports, API ref, 32 edge case tests)
- [x] Phase 6: Advanced chaos (3 new injectors, 7 presets, benchmark doc)

## Blocked

(empty)

## Notes

- Repo at https://github.com/adam85sims/Sentinel
- Governance default is deterministic-only (no LLM required)
- All phases complete — ready for production use
