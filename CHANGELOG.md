# Changelog

All notable changes to **Sentinel** are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[SemVer](https://semver.org/).

## [Unreleased]

### Added
- CI pipeline (pytest + ruff) for Sentinel and pattern-memory.
- LICENSE file (MIT).

## [0.2.0] — 2026-08-18

### Added
- Full `__all__` exports across all modules; `py.typed` marker.
- docs/API_REFERENCE.md generated from docstrings.
- 32 edge-case tests (empty scenarios, malformed YAML, missing tools).

### Changed
- Ruff target-version corrected to `py311`; imports consolidated at top of files.
- Version bumped from `0.1.0` to `0.2.0`.

## [0.1.0] — 2026-07-08

Initial release. Six development phases complete:

- **Phase 1** — Real-agent integration (LangChain ReAct harness, integration tests).
- **Phase 2** — Packaging & distribution (hatch build, git install, GitHub repo).
- **Phase 3** — Documentation & examples (QUICKSTART, CHAOS_GUIDE, ADAPTERS_GUIDE).
- **Phase 4** — Governance model resolution (deterministic comparator default).
- **Phase 5** — Polish & edge cases.
- **Phase 6** — Advanced chaos (NetworkPartition, ClockSkew, MemoryPressure, 7 presets).

516 tests passing.