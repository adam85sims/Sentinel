"""
Sentinel CLI — Command-line interface for running sentinel tests.

Usage:
    sentinel-run run --scenario <name> [--verbose]
    sentinel-run run --all [--verbose]
    sentinel-run run --path <scenario-file> [--verbose]
    sentinel-run baseline record <label> [--path results.json]
    sentinel-run baseline list
    sentinel-run baseline show <label>
    sentinel-run diff <baseline1> <baseline2>
    sentinel-run report --baseline <label> [--format html|junit] [--output file]
    sentinel-run run --help
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import click


@click.group()
@click.version_option(package_name="sentinel")
def cli() -> None:
    """Sentinel — Agent Behavioral Testing Platform.

    Run behavioral tests against agents to verify what they DO,
    not just what they SAY.
    """


# ──────────────────────────────────────────────────────
# sentinel run
# ──────────────────────────────────────────────────────


@cli.command()
@click.option(
    "--scenario",
    required=False,
    help="Name of the test scenario to run.",
)
@click.option(
    "--all",
    "run_all",
    is_flag=True,
    default=False,
    help="Run all discovered scenarios.",
)
@click.option(
    "--path",
    "scenario_path",
    type=click.Path(exists=True),
    required=False,
    help="Path to a scenario file (JSON or YAML).",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable verbose output with detailed test results.",
)
@click.option(
    "--json-output",
    is_flag=True,
    default=False,
    help="Output results as JSON.",
)
def run(
    scenario: str | None,
    run_all: bool,
    scenario_path: str | None,
    verbose: bool,
    json_output: bool,
) -> None:
    """Run sentinel test scenarios.

    \b
    Examples:
        sentinel-run run --scenario injection-resistance
        sentinel-run run --scenario tool-abuse --verbose
        sentinel-run run --all --verbose
        sentinel-run run --path scenarios/refund_agent.json
    """
    from sentinel.runner import ScenarioRunner, TestResult

    runner = ScenarioRunner()

    # Collect scenarios to run
    scenarios = []

    if scenario_path:
        # Load from file
        scenarios = _load_scenario_file(scenario_path)
        if not scenarios:
            click.echo("[sentinel] ERROR: No scenarios found in file.", err=True)
            sys.exit(1)
    elif scenario:
        # Load specific scenario by name from discovery
        found = _discover_scenarios()
        match = [s for s in found if s.id == scenario or s.name == scenario]
        if not match:
            click.echo(
                f"[sentinel] ERROR: Scenario '{scenario}' not found.\n"
                f"Available: {', '.join(s.id for s in found)}",
                err=True,
            )
            sys.exit(1)
        scenarios = match
    elif run_all:
        scenarios = _discover_scenarios()
        if not scenarios:
            click.echo("[sentinel] No scenarios discovered.", err=True)
            sys.exit(0)
    else:
        click.echo(
            "[sentinel] ERROR: Specify --scenario, --all, or --path.\n"
            "Run 'sentinel-run run --help' for usage.",
            err=True,
        )
        sys.exit(1)

    # Execute scenarios
    click.echo(f"[sentinel] Running {len(scenarios)} scenario(s)...\n")

    results: list[TestResult] = []
    start_time = time.time()

    for i, scenario in enumerate(scenarios, 1):
        if verbose:
            click.echo(f"  [{i}/{len(scenarios)}] {scenario.name}")
            click.echo(f"    Task: {scenario.task}")
            click.echo(f"    Tags: {', '.join(scenario.tags) if scenario.tags else 'none'}")

        result = runner.run(scenario)
        results.append(result)

        status = "PASS" if result.passed else "FAIL"
        click.echo(f"  [{status}] {result.summary}")

        if verbose and not result.passed:
            for a in result.failed_assertions():
                click.echo(f"    ✗ {a.assertion_name}: {a.error_message}")
            if result.error:
                click.echo(f"    ERROR: {result.error[:200]}")

        if verbose:
            click.echo()

    # Summary
    total_time = (time.time() - start_time) * 1000
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    click.echo("─" * 60)
    click.echo(
        f"[sentinel] {len(results)} scenario(s): "
        f"{passed} passed, {failed} failed "
        f"({total_time:.0f}ms total)"
    )

    if json_output:
        output = {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "duration_ms": total_time,
            "results": [
                {
                    "scenario_id": r.scenario_id,
                    "scenario_name": r.scenario_name,
                    "passed": r.passed,
                    "duration_ms": r.duration_ms,
                    "assertion_results": [
                        {
                            "name": a.assertion_name,
                            "passed": a.passed,
                            "error": a.error_message,
                        }
                        for a in r.assertion_results
                    ],
                    "error": r.error,
                }
                for r in results
            ],
        }
        click.echo(json.dumps(output, indent=2))

    if failed > 0:
        sys.exit(1)


# ──────────────────────────────────────────────────────
# sentinel list
# ──────────────────────────────────────────────────────


@cli.command()
def list() -> None:  # noqa: A001 — shadowing built-in is intentional for CLI name
    """List all discovered test scenarios."""
    scenarios = _discover_scenarios()
    if not scenarios:
        click.echo("[sentinel] No scenarios discovered.")
        return

    click.echo(f"[sentinel] Found {len(scenarios)} scenario(s):\n")
    for s in scenarios:
        tags = ", ".join(s.tags) if s.tags else "no tags"
        click.echo(f"  {s.id}: {s.name}")
        if s.description:
            click.echo(f"    {s.description}")
        click.echo(f"    Tags: {tags}")
        click.echo()


# ──────────────────────────────────────────────────────
# sentinel info
# ──────────────────────────────────────────────────────


@cli.command()
@click.argument("scenario_id")
def info(scenario_id: str) -> None:
    """Show detailed info about a specific scenario."""
    scenarios = _discover_scenarios()
    match = [s for s in scenarios if s.id == scenario_id]
    if not match:
        click.echo(f"[sentinel] ERROR: Scenario '{scenario_id}' not found.", err=True)
        sys.exit(1)

    s = match[0]
    click.echo(f"Scenario: {s.id}")
    click.echo(f"  Name: {s.name}")
    click.echo(f"  Description: {s.description or '(none)'}")
    click.echo(f"  Task: {s.task or '(none)'}")
    click.echo(f"  Tags: {', '.join(s.tags) if s.tags else 'none'}")
    click.echo(f"  Timeout: {s.timeout_seconds}s")
    click.echo(f"  Assertions: {len(s.assertions)}")


# ──────────────────────────────────────────────────────
# sentinel baseline (group)
# ──────────────────────────────────────────────────────


@cli.group()
def baseline() -> None:
    """Manage test baselines — record, list, show, delete."""
    pass


@baseline.command("record")
@click.argument("label")
@click.option("--path", "results_path", type=click.Path(exists=True),
              help="Path to results JSON file (from sentinel run --json-output).")
@click.option("--tag", "tags", multiple=True, help="Tag(s) for this baseline (repeatable).")
@click.option("--description", "-d", default="", help="Description of this baseline.")
def baseline_record(
    label: str,
    results_path: str | None,
    tags: tuple[str, ...],
    description: str,
) -> None:
    """Record a baseline from results.

    \b
    Examples:
        sentinel-run baseline record v1.2.3 --path results.json
        sentinel-run baseline record nightly --tag ci --tag nightly
    """
    from sentinel.baseline import record_baseline

    if results_path:
        # Load results from JSON file
        with open(results_path) as f:
            raw = json.load(f)

        # If it's the sentinel run --json-output format, extract results
        if isinstance(raw, dict) and "results" in raw:
            raw = raw["results"]

        results = _deserialize_results_from_json(raw)
    else:
        # Try to read from stdin (pipe support)
        if not sys.stdin.isatty():
            raw = json.load(sys.stdin)
            if isinstance(raw, dict) and "results" in raw:
                raw = raw["results"]
            results = _deserialize_results_from_json(raw)
        else:
            click.echo(
                "[sentinel] ERROR: Provide results via --path or pipe JSON to stdin.\n"
                "  sentinel-run run --all --json-output | sentinel-run baseline record my-label",
                err=True,
            )
            sys.exit(1)

    # Detect git info
    git_sha, git_branch = _detect_git_info()

    path = record_baseline(
        results=results,
        label=label,
        tags=list(tags),
        description=description,
        git_sha=git_sha,
        git_branch=git_branch,
    )
    click.echo(f"[sentinel] Baseline '{label}' recorded at {path}")
    click.echo(f"  Scenarios: {len(results)}, Passed: {sum(1 for r in results if r.passed)}")


@baseline.command("list")
def baseline_list() -> None:
    """List all recorded baselines."""
    from sentinel.baseline import list_baselines

    labels = list_baselines()
    if not labels:
        click.echo("[sentinel] No baselines recorded.")
        return

    click.echo(f"[sentinel] {len(labels)} baseline(s):\n")
    for label in labels:
        # Load metadata for display
        try:
            from sentinel.baseline import load_baseline
            meta, _ = load_baseline(label)
            tags_str = f" [{', '.join(meta.tags)}]" if meta.tags else ""
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(meta.timestamp))
            click.echo(
                f"  {label}{tags_str} — {meta.scenario_count} scenarios, "
                f"{meta.pass_count} pass, {meta.fail_count} fail ({ts})"
            )
        except Exception:
            click.echo(f"  {label}")


@baseline.command("show")
@click.argument("label")
def baseline_show(label: str) -> None:
    """Show details of a specific baseline."""
    from sentinel.baseline import load_baseline

    try:
        meta, results = load_baseline(label)
    except FileNotFoundError as e:
        click.echo(f"[sentinel] ERROR: {e}", err=True)
        sys.exit(1)

    click.echo(f"Baseline: {meta.label}")
    click.echo(f"  Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(meta.timestamp))}")
    if meta.git_sha:
        click.echo(f"  Git: {meta.git_sha[:8]} ({meta.git_branch})")
    if meta.tags:
        click.echo(f"  Tags: {', '.join(meta.tags)}")
    if meta.description:
        click.echo(f"  Description: {meta.description}")
    click.echo(f"  Scenarios: {meta.scenario_count} ({meta.pass_count} pass, {meta.fail_count} fail)")
    click.echo()

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        click.echo(f"  [{status}] {r.summary}")


@baseline.command("delete")
@click.argument("label")
def baseline_delete(label: str) -> None:
    """Delete a baseline by label."""
    from sentinel.baseline import delete_baseline

    if delete_baseline(label):
        click.echo(f"[sentinel] Baseline '{label}' deleted.")
    else:
        click.echo(f"[sentinel] ERROR: Baseline '{label}' not found.", err=True)
        sys.exit(1)


# ──────────────────────────────────────────────────────
# sentinel diff
# ──────────────────────────────────────────────────────


@cli.command()
@click.argument("baseline1")
@click.argument("baseline2")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def diff(baseline1: str, baseline2: str, json_output: bool) -> None:
    """Compare two baselines and show regressions/fixes.

    \b
    Examples:
        sentinel-run diff v1.2.3 v1.3.0
        sentinel-run diff main-abc1234 main-def5678 --json-output
    """
    from sentinel.baseline import load_baseline
    from sentinel.reporting import build_regression_report

    try:
        meta1, results1 = load_baseline(baseline1)
    except FileNotFoundError as e:
        click.echo(f"[sentinel] ERROR: {e}", err=True)
        sys.exit(1)

    try:
        meta2, results2 = load_baseline(baseline2)
    except FileNotFoundError as e:
        click.echo(f"[sentinel] ERROR: {e}", err=True)
        sys.exit(1)

    report = build_regression_report(
        baseline_results=results1,
        current_results=results2,
        baseline_label=baseline1,
        current_label=baseline2,
        metadata={"baseline1_timestamp": meta1.timestamp, "baseline2_timestamp": meta2.timestamp},
    )

    if json_output:
        click.echo(json.dumps(report.to_dict(), indent=2))
        return

    # Human-readable output
    click.echo(f"\n[diff] Comparing {baseline1} → {baseline2}\n")
    click.echo(f"  Verdict: {report.verdict}")
    click.echo(f"  {report.summary}\n")

    if report.regressions:
        click.echo("  REGRESSIONS:")
        for d in report.regressions:
            click.echo(f"    ✗ {d.scenario_name} ({d.scenario_id})")
            if d.new_failures:
                for f in d.new_failures:
                    click.echo(f"      New failure: {f}")
        click.echo()

    if report.fixes:
        click.echo("  FIXES:")
        for d in report.fixes:
            click.echo(f"    ✓ {d.scenario_name} ({d.scenario_id})")
            if d.fixed_assertions:
                for f in d.fixed_assertions:
                    click.echo(f"      Fixed: {f}")
        click.echo()

    if report.still_failing:
        click.echo("  STILL FAILING:")
        for d in report.still_failing:
            click.echo(f"    ✗ {d.scenario_name} ({d.scenario_id})")
        click.echo()

    if report.new_scenarios:
        click.echo("  NEW SCENARIOS:")
        for d in report.new_scenarios:
            status = "PASS" if d.current_passed else "FAIL"
            click.echo(f"    [{status}] {d.scenario_name} ({d.scenario_id})")
        click.echo()


# ──────────────────────────────────────────────────────
# sentinel report
# ──────────────────────────────────────────────────────


@cli.command()
@click.option("--baseline", "baseline_label", required=True, help="Baseline label to generate report for.")
@click.option("--format", "report_format", type=click.Choice(["html", "junit", "both"]),
              default="both", help="Report format.")
@click.option("--output", "-o", "output_dir", type=click.Path(), default=".",
              help="Output directory for report files.")
def report(baseline_label: str, report_format: str, output_dir: str) -> None:
    """Generate HTML and/or JUnit reports from a baseline.

    \b
    Examples:
        sentinel-run report --baseline v1.2.3
        sentinel-run report --baseline nightly --format html --output ./reports
        sentinel-run report --baseline v1.3.0 --format junit -o .
    """
    from sentinel.baseline import load_baseline
    from sentinel.reporting import generate_html_report, generate_junit_xml

    try:
        meta, results = load_baseline(baseline_label)
    except FileNotFoundError as e:
        click.echo(f"[sentinel] ERROR: {e}", err=True)
        sys.exit(1)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if report_format in ("html", "both"):
        # Build a simple RegressionReport from just these results
        # (no baseline comparison — single-run report)
        from sentinel.reporting import RegressionReport, ResultDelta, ScenarioDelta

        deltas = []
        for r in results:
            delta = ResultDelta.STILL_PASS if r.passed else ResultDelta.STILL_FAIL
            deltas.append(
                ScenarioDelta(
                    scenario_id=r.scenario_id,
                    scenario_name=r.scenario_name,
                    delta=delta,
                    current_passed=r.passed,
                    current_duration_ms=r.duration_ms,
                )
            )

        report_obj = RegressionReport(
            baseline_label=baseline_label,
            current_label=baseline_label,
            deltas=deltas,
            metadata=meta.metadata,
        )

        html = generate_html_report(report_obj)
        html_path = out_path / f"sentinel-report-{baseline_label}.html"
        html_path.write_text(html)
        click.echo(f"[sentinel] HTML report: {html_path}")

    if report_format in ("junit", "both"):
        xml = generate_junit_xml(results, suite_name=f"sentinel-{baseline_label}")
        xml_path = out_path / f"sentinel-report-{baseline_label}.xml"
        xml_path.write_text(xml)
        click.echo(f"[sentinel] JUnit XML: {xml_path}")


# ──────────────────────────────────────────────────────
# sentinel trace (OTel export)
# ──────────────────────────────────────────────────────


@cli.command()
@click.argument("baseline_label")
@click.option("--output", "-o", "output_path", type=click.Path(), default=None,
              help="Output file path (default: stdout as JSON).")
@click.option("--endpoint", default=None,
              help="OTLP collector endpoint for live export.")
def trace(baseline_label: str, output_path: str | None, endpoint: str | None) -> None:
    """Export baseline traces as OpenTelemetry spans.

    \b
    Examples:
        sentinel-run trace v1.2.3                          # JSON to stdout
        sentinel-run trace v1.2.3 -o traces.json          # JSON to file
        sentinel-run trace v1.2.3 --endpoint localhost:4317  # live OTLP export
    """
    from sentinel.baseline import load_baseline
    from sentinel.otel import trace_to_spans

    try:
        meta, results = load_baseline(baseline_label)
    except FileNotFoundError as e:
        click.echo(f"[sentinel] ERROR: {e}", err=True)
        sys.exit(1)

    all_spans = []
    for r in results:
        spans = trace_to_spans(
            r.trace,
            service_name=f"sentinel.{r.scenario_id}",
        )
        all_spans.extend(spans)

    if endpoint:
        # Live export via OTel SDK
        click.echo(f"[sentinel] Exporting {len(all_spans)} spans to {endpoint}...")
        from sentinel.otel import export_to_otel

        for r in results:
            ok = export_to_otel(r.trace, service_name=f"sentinel.{r.scenario_id}", endpoint=endpoint)
            if not ok:
                click.echo("[sentinel] ERROR: OTel SDK not available. Install opentelemetry-sdk.", err=True)
                sys.exit(1)
        click.echo("[sentinel] Export complete.")
    else:
        # JSON output
        spans_json = [s.to_dict() for s in all_spans]
        output = json.dumps(spans_json, indent=2)

        if output_path:
            Path(output_path).write_text(output)
            click.echo(f"[sentinel] {len(all_spans)} spans written to {output_path}")
        else:
            click.echo(output)


# ──────────────────────────────────────────────────────
# Discovery helpers
# ──────────────────────────────────────────────────────


def _discover_scenarios() -> list:
    """Discover test scenarios from sentinel_test-decorated functions.

    Searches for pytest-compatible test functions with the _sentinel_test
    attribute set by the @sentinel_test decorator.
    """
    from sentinel.runner import TestScenario

    scenarios = []

    # Look for test files in the standard locations
    project_root = Path(__file__).parent.parent.parent
    test_dirs = [project_root / "tests", project_root / "test"]

    for test_dir in test_dirs:
        if not test_dir.exists():
            continue
        for test_file in test_dir.rglob("test_*.py"):
            try:
                # Import the test module
                rel_path = test_file.relative_to(project_root)
                module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
                mod = importlib.import_module(module_name)

                # Find sentinel_test-decorated functions
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name, None)
                    if callable(attr) and getattr(attr, "_sentinel_test", False):
                        scenario = TestScenario(
                            id=attr_name,
                            name=attr.__name__,
                            description=attr.__doc__ or "",
                            task=getattr(attr, "_sentinel_task", ""),
                            tags=getattr(attr, "_sentinel_tags", []),
                            timeout_seconds=getattr(attr, "_sentinel_timeout", 30),
                        )
                        scenarios.append(scenario)
            except Exception:
                # Skip modules that can't be imported
                continue

    return scenarios


def _load_scenario_file(path: str) -> list:
    """Load scenarios from a JSON or YAML file."""
    from sentinel.runner import TestScenario

    file_path = Path(path)
    content = file_path.read_text()

    if file_path.suffix in (".yaml", ".yml"):
        try:
            import yaml
            data = yaml.safe_load(content)
        except ImportError:
            click.echo("[sentinel] ERROR: PyYAML required for YAML files.", err=True)
            return []
    else:
        data = json.loads(content)

    scenarios = []
    items = data if isinstance(data, list) else [data]

    for item in items:
        scenario = TestScenario(
            id=item.get("id", item.get("name", "unnamed")),
            name=item.get("name", item.get("id", "unnamed")),
            description=item.get("description", ""),
            task=item.get("task", ""),
            tags=item.get("tags", []),
            timeout_seconds=item.get("timeout_seconds", 30),
            env_config=item.get("env_config", {}),
        )
        scenarios.append(scenario)

    return scenarios


def _deserialize_results_from_json(raw: list) -> list:
    """Deserialize a list of JSON dicts into SentinelResult objects."""
    from sentinel.baseline import _deserialize_result

    return [_deserialize_result(item) for item in raw]


def _detect_git_info() -> tuple[str, str]:
    """Try to detect git SHA and branch from the current directory."""
    import subprocess

    sha = ""
    branch = ""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
    except Exception:
        pass

    return sha, branch


if __name__ == "__main__":
    cli()
