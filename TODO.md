# Sentinel — Development Queue

> The agent works through this list top-to-bottom during each session.
> Pick the first unchecked item. Mark done when complete. Run governance audit.

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

> The governance audit works but the LLM auditor needs a decision.

- [ ] Document governance model options in docs/GOVERNANCE_DECISION.md
- [ ] Option A: Base granite-4.1-3b + deterministic comparator (current)
- [ ] Option B: Try a different small model (phi-3, gemma-2, etc.)
- [ ] Option C: Rule-based auditor with no LLM (pure deterministic)
- [ ] Run governance audit on current codebase with each approach
- [ ] Make decision and document rationale

## Phase 5: Polish & Edge Cases

> Harden the existing functionality before adding new features.

- [ ] Resolve tool count discrepancy (README: 13, memory: 17)
- [ ] Complete missing diary entries (Phases 9-10)
- [ ] Add type hints to all public APIs (mypy strict mode)
- [ ] Add `__all__` exports to all modules
- [ ] Create docs/API_REFERENCE.md from docstrings
- [ ] Add edge case tests: empty scenarios, malformed YAML, missing tools

## Phase 6: Advanced Chaos (Differentiator Expansion)

> The chaos module is the commercial differentiator. Expand it.

- [ ] Research additional production failure modes (network partitions, clock skew, memory pressure)
- [ ] Implement NetworkPartition chaos injector
- [ ] Implement ClockSkew chaos injector
- [ ] Implement MemoryPressure chaos injector
- [ ] Add chaos scenario presets (e.g., "production incident", "deploy Friday", "traffic spike")
- [ ] Write benchmark: Sentinel chaos vs real production logs (prove correlation)

---

## Done

- [x] Extract sentinel from automation framework into standalone project
- [x] Set up pyproject.toml with proper optional dependencies
- [x] Create README.md with architecture overview
- [x] Verify all 408 sentinel tests pass in new location
- [x] Verify all 33 governance tests pass in new location
- [x] Phase 1: LangChain integration tests (16 tests, all passing)
- [x] Phase 1: Quickstart example (examples/langchain_quickstart.py)
- [x] Phase 1: Integration testing documentation (docs/INTEGRATION_TESTING.md)
- [x] Phase 2: Hatch build verified (wheel + sdist correct)
- [x] Phase 2: pip install -e . works from clean state
- [x] Phase 2: Individual extras install (langchain, openai, governance, otel, dev)
- [x] Phase 2: Version bumping script (scripts/bump_version.py)
- [x] Phase 2: Git install verified (pip install git+file://...)
- [x] Phase 3: Quickstart guide (docs/QUICKSTART.md)
- [x] Phase 3: Chaos guide (docs/CHAOS_GUIDE.md)
- [x] Phase 3: Adapters guide (docs/ADAPTERS_GUIDE.md)
- [x] Phase 3: YAML scenarios (basic + chaos)
- [x] Phase 3: README with badges and full doc links
- [x] Phase 3: All pushed to GitHub

## Blocked

(empty)

## Notes

- `pip install -e ".[all]"` works but crewai takes 60+ seconds to resolve (heavy dependency tree)
- Repo at https://github.com/adam85sims/Sentinel
