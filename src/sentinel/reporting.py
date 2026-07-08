"""Reporting and regression detection for Sentinel test results.

Provides:
- RegressionReport: baseline vs current comparison with new/fixed/regression tracking
- HTML report generation with inline diffs
- JUnit XML output for CI consumption
- Trace diffing (compare two AgentTraces)
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from xml.dom import minidom

from sentinel.models import AgentTrace, ToolCall
from sentinel.runner import SentinelAssertionResult, SentinelResult


# ──────────────────────────────────────────────────────
# RegressionReport — baseline vs current (architecture §6.3)
# ──────────────────────────────────────────────────────


class ResultDelta(str, Enum):
    """Classification of result changes between baseline and current."""

    NEW_PASS = "new_pass"        # scenario was failing, now passes
    NEW_FAIL = "new_fail"        # scenario was passing, now fails
    STILL_PASS = "still_pass"    # scenario passes in both
    STILL_FAIL = "still_fail"    # scenario fails in both
    NEW_SCENARIO = "new_scenario"  # scenario exists only in current
    REMOVED = "removed"          # scenario exists only in baseline


@dataclass
class ScenarioDelta:
    """Delta for a single scenario between baseline and current."""

    scenario_id: str
    scenario_name: str
    delta: ResultDelta
    baseline_passed: Optional[bool] = None
    current_passed: Optional[bool] = None
    baseline_duration_ms: Optional[float] = None
    current_duration_ms: Optional[float] = None
    new_failures: List[str] = field(default_factory=list)
    fixed_assertions: List[str] = field(default_factory=list)
    trace_diff: Optional[Dict[str, Any]] = None

    @property
    def is_regression(self) -> bool:
        return self.delta == ResultDelta.NEW_FAIL

    @property
    def is_fix(self) -> bool:
        return self.delta == ResultDelta.NEW_PASS


@dataclass
class RegressionReport:
    """Full regression report comparing baseline vs current run.

    Architecture §6.3: captures the delta between two sets of test
    results, identifying regressions, fixes, and unchanged scenarios.

    Attributes:
        baseline_label: Identifier for the baseline (e.g., "v1.2.3" or git SHA).
        current_label: Identifier for the current run.
        deltas: Per-scenario deltas.
        baseline_timestamp: When the baseline was recorded.
        current_timestamp: When the current run was executed.
        metadata: Arbitrary extra info (git branch, CI run ID, etc.).
    """

    baseline_label: str = ""
    current_label: str = ""
    deltas: List[ScenarioDelta] = field(default_factory=list)
    baseline_timestamp: float = 0.0
    current_timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Aggregate properties ──

    @property
    def total_scenarios(self) -> int:
        return len(self.deltas)

    @property
    def regressions(self) -> List[ScenarioDelta]:
        """Scenarios that went from passing to failing."""
        return [d for d in self.deltas if d.is_regression]

    @property
    def fixes(self) -> List[ScenarioDelta]:
        """Scenarios that went from failing to passing."""
        return [d for d in self.deltas if d.is_fix]

    @property
    def still_passing(self) -> List[ScenarioDelta]:
        return [d for d in self.deltas if d.delta == ResultDelta.STILL_PASS]

    @property
    def still_failing(self) -> List[ScenarioDelta]:
        return [d for d in self.deltas if d.delta == ResultDelta.STILL_FAIL]

    @property
    def new_scenarios(self) -> List[ScenarioDelta]:
        return [d for d in self.deltas if d.delta == ResultDelta.NEW_SCENARIO]

    @property
    def has_regressions(self) -> bool:
        return len(self.regressions) > 0

    @property
    def verdict(self) -> str:
        """One-line verdict: PASS, FAIL (regressions exist), or WARN (new failures)."""
        if self.has_regressions:
            return "FAIL"
        if self.still_failing:
            return "WARN"
        return "PASS"

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        n_reg = len(self.regressions)
        n_fix = len(self.fixes)
        n_new = len(self.new_scenarios)
        n_sp = len(self.still_passing)
        n_sf = len(self.still_failing)
        parts = [f"{self.total_scenarios} scenario(s) compared"]
        if n_reg:
            parts.append(f"{n_reg} regression(s)")
        if n_fix:
            parts.append(f"{n_fix} fix(es)")
        if n_new:
            parts.append(f"{n_new} new")
        parts.append(f"{n_sp} still pass, {n_sf} still fail")
        return f"[{self.verdict}] " + ", ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "baseline_label": self.baseline_label,
            "current_label": self.current_label,
            "verdict": self.verdict,
            "total_scenarios": self.total_scenarios,
            "regressions": len(self.regressions),
            "fixes": len(self.fixes),
            "deltas": [
                {
                    "scenario_id": d.scenario_id,
                    "scenario_name": d.scenario_name,
                    "delta": d.delta.value,
                    "baseline_passed": d.baseline_passed,
                    "current_passed": d.current_passed,
                    "baseline_duration_ms": d.baseline_duration_ms,
                    "current_duration_ms": d.current_duration_ms,
                    "new_failures": d.new_failures,
                    "fixed_assertions": d.fixed_assertions,
                }
                for d in self.deltas
            ],
            "metadata": self.metadata,
        }


# ──────────────────────────────────────────────────────
# Report generation from results
# ──────────────────────────────────────────────────────


def build_regression_report(
    baseline_results: List[SentinelResult],
    current_results: List[SentinelResult],
    baseline_label: str = "baseline",
    current_label: str = "current",
    metadata: Optional[Dict[str, Any]] = None,
) -> RegressionReport:
    """Build a RegressionReport by comparing baseline and current results.

    Matches scenarios by scenario_id. Handles:
    - Scenarios present in both (pass/pass, pass/fail, fail/pass, fail/fail)
    - Scenarios only in current (new_scenario)
    - Scenarios only in baseline (removed)
    """
    baseline_map: Dict[str, SentinelResult] = {r.scenario_id: r for r in baseline_results}
    current_map: Dict[str, SentinelResult] = {r.scenario_id: r for r in current_results}

    all_ids = set(baseline_map.keys()) | set(current_map.keys())
    deltas: List[ScenarioDelta] = []

    for sid in sorted(all_ids):
        b = baseline_map.get(sid)
        c = current_map.get(sid)

        if b and c:
            # Scenario in both — classify
            if b.passed and c.passed:
                delta = ResultDelta.STILL_PASS
            elif not b.passed and not c.passed:
                delta = ResultDelta.STILL_FAIL
            elif not b.passed and c.passed:
                delta = ResultDelta.NEW_PASS
            else:  # b.passed and not c.passed
                delta = ResultDelta.NEW_FAIL

            # Find new failures and fixes by comparing assertion names
            b_failed = {a.assertion_name for a in b.assertion_results if not a.passed}
            c_failed = {a.assertion_name for a in c.assertion_results if not a.passed}

            new_failures = sorted(c_failed - b_failed)
            fixed_assertions = sorted(b_failed - c_failed)

            # Trace diff
            trace_diff = diff_traces(b.trace, c.trace) if (b.trace and c.trace) else None

            deltas.append(
                ScenarioDelta(
                    scenario_id=sid,
                    scenario_name=c.scenario_name,
                    delta=delta,
                    baseline_passed=b.passed,
                    current_passed=c.passed,
                    baseline_duration_ms=b.duration_ms,
                    current_duration_ms=c.duration_ms,
                    new_failures=new_failures,
                    fixed_assertions=fixed_assertions,
                    trace_diff=trace_diff,
                )
            )
        elif c:
            deltas.append(
                ScenarioDelta(
                    scenario_id=sid,
                    scenario_name=c.scenario_name,
                    delta=ResultDelta.NEW_SCENARIO,
                    current_passed=c.passed,
                    current_duration_ms=c.duration_ms,
                )
            )
        else:
            # Only in baseline — marked removed
            assert b is not None  # for type checker
            deltas.append(
                ScenarioDelta(
                    scenario_id=sid,
                    scenario_name=b.scenario_name,
                    delta=ResultDelta.REMOVED,
                    baseline_passed=b.passed,
                    baseline_duration_ms=b.duration_ms,
                )
            )

    return RegressionReport(
        baseline_label=baseline_label,
        current_label=current_label,
        deltas=deltas,
        metadata=metadata or {},
    )


# ──────────────────────────────────────────────────────
# Trace diff
# ──────────────────────────────────────────────────────


def diff_traces(
    baseline: AgentTrace,
    current: AgentTrace,
) -> Dict[str, Any]:
    """Compare two AgentTraces and return a structural diff.

    Returns a dict with:
        - tool_calls_added: tools called in current but not baseline
        - tool_calls_removed: tools called in baseline but not current
        - tool_call_count_delta: {tool_name: (baseline_count, current_count)}
        - errors_added: count of new errors in current
        - duration_delta_ms: current - baseline total duration
        - state_changes_added: count of new state changes
    """
    b_tools = set(baseline.tool_names_called)
    c_tools = set(current.tool_names_called)

    # Per-tool call count delta
    b_counts = {name: len(baseline.tool_calls_by_name(name)) for name in b_tools}
    c_counts = {name: len(current.tool_calls_by_name(name)) for name in c_tools}
    all_tool_names = sorted(b_tools | c_tools)
    count_delta = {}
    for name in all_tool_names:
        bc = b_counts.get(name, 0)
        cc = c_counts.get(name, 0)
        if bc != cc:
            count_delta[name] = (bc, cc)

    return {
        "tool_calls_added": sorted(c_tools - b_tools),
        "tool_calls_removed": sorted(b_tools - c_tools),
        "tool_call_count_delta": count_delta,
        "errors_added": max(0, len(current.errors) - len(baseline.errors)),
        "duration_delta_ms": current.total_duration_ms - baseline.total_duration_ms,
        "state_changes_added": max(
            0, len(current.state_changes) - len(baseline.state_changes)
        ),
    }


# ──────────────────────────────────────────────────────
# HTML Report Generation
# ──────────────────────────────────────────────────────

# Inline CSS — self-contained, no external deps.
_HTML_STYLE = """
<style>
  :root { --bg: #0d1117; --fg: #c9d1d9; --accent: #58a6ff; --pass: #3fb950;
          --fail: #f85149; --warn: #d29922; --card: #161b22; --border: #30363d; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--fg); padding: 2rem; line-height: 1.6; }
  h1 { color: var(--accent); margin-bottom: 0.5rem; font-size: 1.5rem; }
  .verdict { display: inline-block; padding: 0.25rem 0.75rem; border-radius: 4px;
             font-weight: bold; font-size: 0.9rem; }
  .verdict-PASS { background: var(--pass); color: #000; }
  .verdict-FAIL { background: var(--fail); color: #fff; }
  .verdict-WARN { background: var(--warn); color: #000; }
  .summary { color: #8b949e; margin-bottom: 1.5rem; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 6px;
          padding: 1rem; margin-bottom: 0.75rem; }
  .card-header { display: flex; justify-content: space-between; align-items: center; }
  .card-title { font-weight: 600; }
  .delta-tag { padding: 0.15rem 0.5rem; border-radius: 3px; font-size: 0.75rem; font-weight: 600; }
  .delta-new_pass { background: var(--pass); color: #000; }
  .delta-new_fail { background: var(--fail); color: #fff; }
  .delta-still_pass { background: #1a4d2e; color: var(--pass); }
  .delta-still_fail { background: #4d1a1a; color: var(--fail); }
  .delta-new_scenario { background: #1a3a4d; color: var(--accent); }
  .delta-removed { background: #3d3d3d; color: #8b949e; }
  .delta-detail { margin-top: 0.5rem; font-size: 0.85rem; color: #8b949e; }
  .delta-detail .failure { color: var(--fail); }
  .delta-detail .fix { color: var(--pass); }
  .timing { font-size: 0.8rem; color: #8b949e; }
  table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
  th, td { padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }
  th { color: var(--accent); font-weight: 600; font-size: 0.85rem; }
  td { font-size: 0.85rem; }
  .meta { margin-top: 2rem; font-size: 0.75rem; color: #484f58; }
</style>
"""


def generate_html_report(report: RegressionReport) -> str:
    """Generate a self-contained HTML regression report.

    Returns a complete HTML document string. No external dependencies.
    """
    # Build scenario rows
    rows_html = []
    for d in report.deltas:
        detail_parts = []
        if d.new_failures:
            detail_parts.append(
                '<span class="failure">New failures: '
                + ", ".join(d.new_failures)
                + "</span>"
            )
        if d.fixed_assertions:
            detail_parts.append(
                '<span class="fix">Fixed: '
                + ", ".join(d.fixed_assertions)
                + "</span>"
            )
        detail_html = "<br>".join(detail_parts)

        timing_parts = []
        if d.baseline_duration_ms is not None:
            timing_parts.append(f"baseline: {d.baseline_duration_ms:.0f}ms")
        if d.current_duration_ms is not None:
            timing_parts.append(f"current: {d.current_duration_ms:.0f}ms")
        timing_str = ", ".join(timing_parts) or "—"

        rows_html.append(
            f'<div class="card">'
            f'  <div class="card-header">'
            f'    <span class="card-title">{_esc(d.scenario_name)} ({_esc(d.scenario_id)})</span>'
            f'    <span class="delta-tag delta-{d.delta.value}">{d.delta.value}</span>'
            f'  </div>'
            f'  <div class="delta-detail">{detail_html}</div>'
            f'  <div class="timing">{timing_str}</div>'
            f"</div>"
        )

    scenarios_html = "\n".join(rows_html) if rows_html else '<p class="summary">No scenarios to compare.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel Regression Report — {report.verdict}</title>
{_HTML_STYLE}
</head>
<body>
  <h1>Sentinel Regression Report</h1>
  <p>
    <span class="verdict verdict-{report.verdict}">{report.verdict}</span>
    <span class="summary" style="margin-left: 1rem;">{_esc(report.summary)}</span>
  </p>
  <div class="summary">
    Baseline: {_esc(report.baseline_label or '(none)')} &nbsp;|&nbsp;
    Current: {_esc(report.current_label or '(none)')}
  </div>
  {scenarios_html}
  <div class="meta">
    Generated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report.current_timestamp))}
    {_esc(' | '.join(f'{k}: {v}' for k, v in report.metadata.items())) if report.metadata else ''}
  </div>
</body>
</html>"""
    return html


def _esc(text: str) -> str:
    """Minimal HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ──────────────────────────────────────────────────────
# JUnit XML Generation
# ──────────────────────────────────────────────────────


def generate_junit_xml(results: List[SentinelResult], suite_name: str = "sentinel") -> str:
    """Generate JUnit XML from a list of test results.

    Compatible with CI systems (GitHub Actions, GitLab CI, Jenkins, etc.).
    Returns a pretty-printed XML string.
    """
    total = len(results)
    failures = sum(1 for r in results if not r.passed)
    total_time_ms = sum(r.duration_ms for r in results)

    testsuite = ET.Element(
        "testsuite",
        name=suite_name,
        tests=str(total),
        failures=str(failures),
        errors="0",
        time=f"{total_time_ms / 1000:.3f}",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    )

    for r in results:
        testcase = ET.SubElement(
            testsuite,
            "testcase",
            name=r.scenario_name,
            classname=r.scenario_id,
            time=f"{r.duration_ms / 1000:.3f}",
        )

        if not r.passed:
            failure = ET.SubElement(testcase, "failure", message=r.error or "Assertion failure")
            # Include failed assertion details
            failed = r.failed_assertions()
            if failed:
                failure.text = "\n".join(
                    f"  {a.assertion_name}: {a.error_message}" for a in failed
                )

        # Add stdout with trace summary
        stdout_parts = [f"Scenario: {r.scenario_name} ({r.scenario_id})"]
        stdout_parts.append(f"Duration: {r.duration_ms:.0f}ms")
        if r.trace.tool_names_called:
            stdout_parts.append(f"Tools called: {r.trace.tool_names_called}")
        stdout_parts.append(f"Total steps: {r.trace.total_steps}")
        stdout_parts.append(f"Total tool calls: {r.trace.total_tool_calls}")
        if r.error:
            stdout_parts.append(f"Error: {r.error}")

        stdout = ET.SubElement(testcase, "stdout")
        stdout.text = "\n".join(stdout_parts)

    # Pretty-print
    rough = ET.tostring(testsuite, encoding="unicode")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding=None)


def generate_junit_xml_from_report(report: RegressionReport, suite_name: str = "sentinel-regression") -> str:
    """Generate JUnit XML from a RegressionReport.

    Each ScenarioDelta becomes a testcase. Regressions are failures,
    fixes are passes, still-failing are failures, etc.
    """
    total = report.total_scenarios
    failures = len(report.regressions) + len(report.still_failing)

    testsuite = ET.Element(
        "testsuite",
        name=suite_name,
        tests=str(total),
        failures=str(failures),
        errors="0",
        time="0.000",
    )

    for d in report.deltas:
        testcase = ET.SubElement(
            testsuite,
            "testcase",
            name=d.scenario_name,
            classname=d.scenario_id,
            time=f"{(d.current_duration_ms or 0) / 1000:.3f}",
        )

        if d.delta in (ResultDelta.NEW_FAIL, ResultDelta.STILL_FAIL):
            failure = ET.SubElement(
                testcase, "failure",
                message=f"Regression: {d.delta.value}" if d.delta == ResultDelta.NEW_FAIL
                        else f"Still failing: {d.delta.value}",
            )
            parts = []
            if d.new_failures:
                parts.append(f"New assertion failures: {', '.join(d.new_failures)}")
            if d.fixed_assertions:
                parts.append(f"Fixed assertions: {', '.join(d.fixed_assertions)}")
            failure.text = "\n".join(parts) if parts else f"Delta: {d.delta.value}"

    rough = ET.tostring(testsuite, encoding="unicode")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding=None)
