# Sentinel

**Agent Behavioral Testing Platform** — Tests what agents DO, not just what they SAY.

## The Problem

88% of AI agents fail in production. The dominant failure modes are operational:
- Tool errors (28%)
- Memory/state issues (22%)
- Edge cases (18%)

Yet the entire evaluation ecosystem (DeepEval, LangSmith, MS AGT) focuses on
output quality or observability. Nobody tests agent **behavior** in production-like
environments before deployment.

## The Solution

Sentinel fills that gap. It's a behavioral testing platform that:

1. **Mocks your agent's environment** — tools, APIs, databases with configurable
   latency, errors, and rate limits
2. **Injects chaos** — tool failures, context degradation, cascading errors,
   spec drift under pressure
3. **Asserts behavior** — 20+ assertions across tool calls, state consistency,
   governance compliance, resilience, and performance
4. **Reports regressions** — structural diffing, baseline comparison, HTML + JUnit reports

## Quick Start

```bash
# Install (zero dependencies by default)
pip install -e .

# Or with framework adapters
pip install -e ".[adapters]"

# Run your first test
sentinel run scenarios/basic.yaml
```

## Architecture

```
src/sentinel/
├── env.py          # MockTool, MockAPI, MockDatabase, EnvironmentBuilder
├── chaos.py        # ToolFailureInjector, ContextDegradation, CascadingFailures
├── assertions.py   # 20+ behavioral assertions
├── runner.py       # @sentinel_test decorator, ScenarioRunner
├── reporting.py    # Regression reports, JUnit XML, HTML
├── baseline.py     # JSON baseline storage with git integration
├── otel.py         # OpenTelemetry span model
├── cli.py          # Full CLI: run, list, info, baseline, diff, report
└── adapters/       # LangChain, CrewAI, OpenAI SDK, Generic
```

## The Chaos Module (Differentiator)

Sentinel's chaos injection is what sets it apart:

- **ContextDegradation** — Quadratic acceleration curve matching real context
  window pressure (last 20% is much worse than first 20%)
- **CascadingFailures** — Multi-agent error propagation with dependency graphs
  (database → api_server → ui)
- **SpecDrift** — Agent improvisation under pressure with intensity levels
  and cumulative drift scoring

No other tool tests these production failure modes.

## CLI Commands

```bash
sentinel run <scenario>          # Run a test scenario
sentinel list                    # List available scenarios
sentinel info <scenario>         # Show scenario details
sentinel baseline record         # Record current state as baseline
sentinel baseline show           # Show recorded baseline
sentinel diff                    # Compare current vs baseline
sentinel report                  # Generate regression report
sentinel trace <run-id>          # Show execution trace
```

## Framework Adapters

Sentinel works with any agent framework through optional adapters:

```python
# LangChain
from sentinel.adapters.langchain import wrap_agent
wrapped = wrap_agent(your_agent)

# CrewAI
from sentinel.adapters.crewai import wrap_crew_agent
wrapped = wrap_crew_agent(your_crew)

# OpenAI SDK
from sentinel.adapters.openai import wrap_agent
wrapped = wrap_agent(your_agent)

# Generic (any framework)
from sentinel.adapters.generic import HookAdapter
adapter = HookAdapter(mock=your_mock, before=hook_fn)
```

## Chaos Example

```python
from sentinel.chaos import (
    ToolFailureInjector,
    ContextDegradation,
    CascadingFailures,
    ChaosBudget,
)

# Fail 30% of tool calls with timeout errors
injector = ToolFailureInjector(
    failure_type="timeout",
    probability=0.3,
)

# Degrade context with quadratic acceleration
degradation = ContextDegradation(strategy="TRUNCATION")

# Cascade failures from database to API to UI
cascade = CascadingFailures(
    dependency_graph={
        "database": ["api_server"],
        "api_server": ["ui"],
    },
)

# Cap total failures per run
budget = ChaosBudget(max_failures=10)
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=sentinel --cov-report=html

# Lint
ruff check src/ tests/
```

## License

MIT
