# Sentinel — Code Review & Improvement Suggestions

Sentinel is a well-structured behavioral testing platform for AI agents. All 6 planned phases are complete (519 tests). The architecture is clean and the zero-dependency core is a strong design choice. Below are findings grouped by priority.

---

## 🔴 Bugs / Correctness Issues

### 1. `Tuple` import at the bottom of `baseline.py`
[baseline.py](file:///home/adam/projects/sentinel/src/sentinel/baseline.py#L379)

The `Tuple` import from `typing` is placed at the **bottom** of the file (line 379), but it's used in the `load_baseline` return type annotation at line 305. This works at runtime due to `from __future__ import annotations`, but it's a confusing anti-pattern and will break if `annotations` is ever removed.

```diff
-# Type hint for the tuple return
-from typing import Tuple
+# (move this to the top-level imports block, line 19)
```

### 2. `__all__` is defined twice in `assertions.py`
[assertions.py](file:///home/adam/projects/sentinel/src/sentinel/assertions.py#L22-L50) and [L276-L304](file:///home/adam/projects/sentinel/src/sentinel/assertions.py#L276-L304)

There are **two `__all__` lists** — the first is silently overwritten by the second. The first `__all__` (line 22) is dead code.

```diff
-# Remove the first __all__ block entirely (lines 22–50)
```

### 3. `detect_state_collisions` is not in `__all__` but is a public function
[assertions.py](file:///home/adam/projects/sentinel/src/sentinel/assertions.py#L806)

`detect_state_collisions()` is a standalone public utility function but missing from `__all__`. This means `from sentinel.assertions import *` won't expose it.

### 4. `assert_state_no_collisions` — `allowed_keys` semantics are inverted
[assertions.py](file:///home/adam/projects/sentinel/src/sentinel/assertions.py#L886-L888)

The docstring says "only check for collisions on these keys" but the filter `if c["key"] in allowed_set` keeps only collisions **on** `allowed_keys`. This is counterintuitive — `allowed_keys` should typically mean keys that *are allowed* to collide (i.e., ignore them). The parameter name and logic are in conflict.

### 5. `chaos.py` imports `copy` and `hashlib` after the module docstring but before class definitions — not at the top
[chaos.py](file:///home/adam/projects/sentinel/src/sentinel/chaos.py#L46-L47)

`import copy` and `import hashlib` are placed mid-file (lines 46–47) after `__all__`. They should be with the other imports at the top.

---

## 🟡 Design / Architecture Improvements

### 6. `ScenarioRunner.run_batch()` is single-threaded with no parallelism option
[runner.py](file:///home/adam/projects/sentinel/src/sentinel/runner.py#L301-L310)

```python
def run_batch(self, scenarios, agent_fn=None):
    return [self.run(scenario, agent_fn=agent_fn) for scenario in scenarios]
```

For large test suites this is slow. A simple improvement would be to add an optional `max_workers` parameter using `concurrent.futures.ThreadPoolExecutor`:

```python
def run_batch(self, scenarios, agent_fn=None, max_workers=1):
    if max_workers == 1:
        return [self.run(s, agent_fn=agent_fn) for s in scenarios]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(self.run, s, agent_fn=agent_fn) for s in scenarios]
        return [f.result() for f in futures]
```

### 7. `MockTool.side_effect` is destructive (one-shot only)
[env.py](file:///home/adam/projects/sentinel/src/sentinel/env.py#L143-L149)

```python
if self.side_effect is not None:
    error = self.side_effect
    self.side_effect = None  # Only fire once
```

This mutates the mock's state in-place with no way to configure repeat-firing, and makes the tool non-reusable across test runs without reconstruction. Consider adding a `side_effect_count` or making it a callable.

### 8. `CascadingFailures` cascade target derivation is hardcoded
[chaos.py](file:///home/adam/projects/sentinel/src/sentinel/chaos.py#L929-L940)

```python
cascade_map = {
    "database": "api_server",
    "api_server": "user_interface",
    ...
}
```

This hardcoded map limits the usefulness of `CascadingFailures` — the original `CascadingFailures` class in the README shows it accepting a `dependency_graph` parameter. The class constructor accepts `dependency_graph` only in examples but this internal map ignores it. The user-facing `dependency_graph` from the README example is not wired into `_derive_cascading_target`.

### 9. `ChaosBudget` has no `get_injectors()` on the public interface
[runner.py](file:///home/adam/projects/sentinel/src/sentinel/runner.py#L437)

`_apply_chaos()` calls `chaos.get_injectors()` but this method's existence can only be inferred — it's not in `__all__`, not in the README, and not easily discoverable. The `FailureInjector` Protocol also doesn't include it. This is a hidden interface contract.

### 10. `ContextDegradation.current_degradation_level` uses quadratic of a linear value
[chaos.py](file:///home/adam/projects/sentinel/src/sentinel/chaos.py#L606-L611)

```python
raw = elapsed * self.degradation_rate
return min(1.0, raw * raw)
```

The comment says "quadratic acceleration" but `raw * raw` is really `(elapsed * rate)^2`, which grows very slowly for small `degradation_rate` values (e.g., 0.1 rate at 5 steps = `(0.5)^2 = 0.25`). This is fine, but would benefit from a test that documents the expected acceleration curve numerically so users can reason about it.

---

## 🟢 Quality / Polish Improvements

### 11. `ruff` target-version is wrong in `pyproject.toml`
[pyproject.toml](file:///home/adam/projects/sentinel/pyproject.toml#L89)

```toml
[tool.ruff]
target-version = "0.1.0"   # ← This is a Ruff version, not a Python version
```

`target-version` should be a Python version string like `"py311"`, not a Ruff version number. This means Ruff is silently ignoring it or using a default.

```diff
-target-version = "0.1.0"
+target-version = "py311"
```

### 12. Version is stuck at `0.1.0`
[pyproject.toml](file:///home/adam/projects/sentinel/pyproject.toml#L7)

Six phases are complete, 519 tests pass, and it's been pushed to GitHub. A `0.1.0` label undersells the maturity. Consider bumping to `0.2.0` or `0.3.0` to reflect the completed roadmap.

### 13. README badge shows hardcoded test count
[README.md](file:///home/adam/projects/sentinel/README.md#L7)

```
[![Tests](https://img.shields.io/badge/tests-424%20passing-brightgreen.svg)]
```

The badge says 424 but `TODO.md` says 519 are passing. This will drift further unless automated. Consider switching to a dynamic Shields.io endpoint or a CI badge.

### 14. Missing `pytest-asyncio` for async agent adapters
[pyproject.toml](file:///home/adam/projects/sentinel/pyproject.toml#L48-L53)

The dev dependencies don't include `pytest-asyncio`. If users test agents that are async (common with OpenAI SDK), they'll hit issues. Consider adding it as an optional dev dependency.

### 15. No `CHANGELOG.md`
The project is now at a shippable state, but has no `CHANGELOG.md`. Adding one (even a minimal one documenting the 6 phases) would be good practice before users start depending on it.

### 16. `chaos_presets.py` all use the same seed `42`
[chaos_presets.py](file:///home/adam/projects/sentinel/src/sentinel/chaos_presets.py#L34)

Every injector in every preset uses `seed=42`. This means all presets produce the same failure sequence, which reduces the value of having multiple presets for different failure scenarios. Each preset should either use unique seeds or document clearly that seeds are meant for reproducibility.

### 17. `MockDatabase` latency applies to all operations identically
[env.py](file:///home/adam/projects/sentinel/src/sentinel/env.py#L538-L543)

The `MockDatabase` uses a single `latency_ms` for all operations. Real databases have very different latency profiles (SELECTs vs INSERTs vs full-table scans). A per-operation latency map would make tests more realistic.

### 18. No type stubs / `py.typed` marker
The package ships no `py.typed` marker, so downstream type-checkers (mypy, pyright) won't know Sentinel is typed. Adding an empty `src/sentinel/py.typed` file would enable this.

---

## 🔵 Feature Suggestions (Post-v1)

| Feature | Value |
|---|---|
| **`pytest` plugin** (`conftest.py`-level hooks) | Let Sentinel hooks integrate with standard `pytest` output/fixtures natively |
| **Async chaos injection** | `async def __call__` support so `MockTool` works directly with async agent frameworks |
| **Snapshot testing** for traces | `assert_trace_matches_snapshot()` — save a reference trace and diff structurally |
| **Built-in retry assertion** | `assert_retried_after_failure(tool_name, max_retries=3)` |
| **Time-bounded chaos** | Inject failures only within a wall-clock window (e.g., first 5 seconds of run) |
| **Prometheus metrics export** | Expose chaos injection rates, assertion pass rates as metrics for CI dashboards |

---

## Summary Table

| Category | Count | Priority |
|---|---|---|
| Bugs / Correctness | 5 | 🔴 Fix first |
| Design Improvements | 6 | 🟡 Before v1 |
| Quality / Polish | 8 | 🟢 Nice to have |
| Feature Suggestions | 6 | 🔵 Future |
