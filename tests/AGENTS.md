# Testing rules for `sentinel/`

This file is the source of truth for how tests in this directory should be
written. Follow it when adding or modifying tests, and update it if you make
a deliberate exception.

## Invariants

Tests in this directory must be **parallel-safe** (work under `pytest -n auto`)
and **order-independent** (work under `pytest -p randomly` across seeds).
Both are locally verified before each commit.

If a change breaks either property, that's a bug — fix the test, don't relax
the rule.

## Hard rules

### No mutating shared state
- **No** `os.chdir`. Use `monkeypatch.chdir` if you really need to.
- **No** direct `os.environ[...] =` writes. Use `monkeypatch.setenv`.
- **No** patching a module attribute by hand. Use `monkeypatch.setattr` —
  it auto-restores on teardown even if the test fails.
- **No** `random.seed(...)` on the global `random` module. The chaos
  injectors already use per-instance `random.Random(seed)`; if a test needs
  determinism, use that pattern, not the global.
- **No** mutating `sys.path`, registering atexit handlers, or anything else
  that leaks past test boundaries.

### No subprocess in tests
- **No** `subprocess.run(...)` calling out to pytest, the real CLI, or the
  real auditor. Stub with `monkeypatch.setattr(subprocess, "run", ...)` or
  `monkeypatch.setattr(module, "subprocess", fake)`.
- The `evidence.py` collector in `governance/` invokes `pytest` recursively
  when a `tests/` directory is present — the audit test stubs this out.

### Filesystem isolation
- Use the `tmp_path` fixture for any path work. Never write into the
  repo or the user's CWD.
- Use `tmp_baseline_dir` (from `tests/conftest.py`) for baseline tests —
  it overrides `sentinel.baseline.get_baseline_dir` cleanly.

### Helpers go in `conftest.py`
- If you find yourself duplicating a factory across two or more test files,
  promote it to `tests/conftest.py` as a fixture. Don't keep a private
  copy in each file.
- Existing fixtures: `make_trace`, `make_tool_call`, `make_state_change`,
  `make_error`, `make_result`, `tmp_baseline_dir`.

### Assertions should be specific
- `try/except: pass` swallows unrelated errors. Don't write
  "accepts-or-raises-X" tests — pick the behaviour you want and assert it.
- Don't assert on a literal value if the value is an implementation
  detail. Lock the *shape* (e.g. `provider/name` regex) instead.
- If you find an `assert "key" in d` test where the key is always present
  by default, the test isn't testing what you think it is. Fix it.

## Recommended local commands

```sh
# fast feedback (parallel)
.venv/Scripts/python.exe -m pytest -n auto

# order-independence check (catches state leaks)
.venv/Scripts/python.exe -m pytest -p randomly --randomly-seed=12345
.venv/Scripts/python.exe -m pytest -p randomly --randomly-seed=67890

# both at once
.venv/Scripts/python.exe -m pytest -n auto -p randomly

# just the slow governance tests
.venv/Scripts/python.exe -m pytest tests/test_governance.py
```

## When you're about to do something weird

Before reaching for `os.environ` writes, a class-level autouse fixture, a
custom `pytest_configure`, or a `@pytest.fixture(autouse=True, scope="session")`,
ask: is there a simpler way that doesn't touch shared state? Usually yes.
