"""Tests for Phase 7: RegressionReport, HTML report, JUnit XML."""

import json
import time

import pytest

from sentinel.models import AgentTrace, Error, ErrorSeverity, Step, StepAction, ToolCall
from sentinel.reporting import (
    ResultDelta,
    RegressionReport,
    ScenarioDelta,
    build_regression_report,
    diff_traces,
    generate_html_report,
    generate_junit_xml,
    generate_junit_xml_from_report,
)
from sentinel.runner import SentinelAssertionResult, SentinelResult


# ──────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────


def _make_result(
    scenario_id: str,
    passed: bool,
    assertion_names: list[str] | None = None,
    tool_names: list[str] | None = None,
    duration_ms: float = 100.0,
) -> SentinelResult:
    """Build a minimal SentinelResult for testing."""
    trace = AgentTrace()
    trace._start_time = time.time() - 1.0
    trace._end_time = time.time()

    if tool_names:
        for name in tool_names:
            trace.add_tool_call(ToolCall(tool_name=name, arguments={}))

    trace.finish()

    assertion_results = []
    if assertion_names:
        for name in assertion_names:
            assertion_results.append(
                SentinelAssertionResult(assertion_name=name, passed=passed)
            )
    elif passed:
        assertion_results.append(
            SentinelAssertionResult(assertion_name="default_assert", passed=True)
        )
    else:
        assertion_results.append(
            SentinelAssertionResult(
                assertion_name="default_assert", passed=False, error_message="boom"
            )
        )

    return SentinelResult(
        scenario_id=scenario_id,
        scenario_name=f"Scenario {scenario_id}",
        passed=passed,
        trace=trace,
        assertion_results=assertion_results,
        duration_ms=duration_ms,
    )


# ──────────────────────────────────────────────────────
# RegressionReport
# ──────────────────────────────────────────────────────


class TestRegressionReport:
    """Tests for RegressionReport dataclass and aggregation properties."""

    def test_empty_report(self):
        report = RegressionReport()
        assert report.total_scenarios == 0
        assert report.verdict == "PASS"
        assert not report.has_regressions
        assert report.regressions == []
        assert report.fixes == []

    def test_all_passing(self):
        baseline = [_make_result("s1", True), _make_result("s2", True)]
        current = [_make_result("s1", True), _make_result("s2", True)]
        report = build_regression_report(baseline, current)
        assert report.verdict == "PASS"
        assert report.total_scenarios == 2
        assert len(report.still_passing) == 2

    def test_regression_detected(self):
        baseline = [_make_result("s1", True), _make_result("s2", True)]
        current = [_make_result("s1", True), _make_result("s2", False)]
        report = build_regression_report(baseline, current)
        assert report.verdict == "FAIL"
        assert len(report.regressions) == 1
        assert report.regressions[0].scenario_id == "s2"

    def test_fix_detected(self):
        baseline = [_make_result("s1", False), _make_result("s2", True)]
        current = [_make_result("s1", True), _make_result("s2", True)]
        report = build_regression_report(baseline, current)
        assert report.verdict == "PASS"
        assert len(report.fixes) == 1
        assert report.fixes[0].scenario_id == "s1"

    def test_new_scenario(self):
        baseline = [_make_result("s1", True)]
        current = [_make_result("s1", True), _make_result("s2", True)]
        report = build_regression_report(baseline, current)
        assert report.total_scenarios == 2
        assert len(report.new_scenarios) == 1
        assert report.new_scenarios[0].scenario_id == "s2"

    def test_removed_scenario(self):
        baseline = [_make_result("s1", True), _make_result("s2", True)]
        current = [_make_result("s1", True)]
        report = build_regression_report(baseline, current)
        assert report.total_scenarios == 2
        removed = [d for d in report.deltas if d.delta == ResultDelta.REMOVED]
        assert len(removed) == 1
        assert removed[0].scenario_id == "s2"

    def test_assertion_level_diff(self):
        baseline = [_make_result("s1", False, ["assert_a", "assert_b"])]
        current = [_make_result("s1", False, ["assert_b", "assert_c"])]
        report = build_regression_report(baseline, current)
        d = report.deltas[0]
        assert "assert_a" in d.fixed_assertions
        assert "assert_c" in d.new_failures

    def test_still_failing_warns(self):
        baseline = [_make_result("s1", False)]
        current = [_make_result("s1", False)]
        report = build_regression_report(baseline, current)
        assert report.verdict == "WARN"
        assert len(report.still_failing) == 1

    def test_summary_string(self):
        baseline = [_make_result("s1", True), _make_result("s2", True)]
        current = [_make_result("s1", True), _make_result("s2", False)]
        report = build_regression_report(baseline, current)
        assert "FAIL" in report.summary
        assert "1 regression" in report.summary

    def test_to_dict(self):
        baseline = [_make_result("s1", True)]
        current = [_make_result("s1", True)]
        report = build_regression_report(baseline, current, metadata={"key": "val"})
        d = report.to_dict()
        assert d["verdict"] == "PASS"
        assert d["metadata"] == {"key": "val"}
        assert len(d["deltas"]) == 1

    def test_scenario_delta_properties(self):
        d = ScenarioDelta(
            scenario_id="s1",
            scenario_name="Test",
            delta=ResultDelta.NEW_FAIL,
        )
        assert d.is_regression
        assert not d.is_fix

    def test_mixed_scenario(self):
        """Complex mix: regression, fix, new, removed, still-fail."""
        baseline = [
            _make_result("s1", True),   # will regress
            _make_result("s2", False),  # will be fixed
            _make_result("s3", False),  # still failing
            _make_result("s4", True),   # will be removed
        ]
        current = [
            _make_result("s1", False),  # regression
            _make_result("s2", True),   # fix
            _make_result("s3", False),  # still failing
            _make_result("s5", True),   # new
        ]
        report = build_regression_report(baseline, current, baseline_label="v1", current_label="v2")
        assert report.total_scenarios == 5
        assert len(report.regressions) == 1
        assert len(report.fixes) == 1
        assert len(report.new_scenarios) == 1
        removed = [d for d in report.deltas if d.delta == ResultDelta.REMOVED]
        assert len(removed) == 1
        assert report.verdict == "FAIL"


# ──────────────────────────────────────────────────────
# Trace diff
# ──────────────────────────────────────────────────────


class TestDiffTraces:
    def test_identical_traces(self):
        t1 = AgentTrace()
        t1.add_tool_call(ToolCall(tool_name="search", arguments={"q": "hello"}))
        t1.finish()

        t2 = AgentTrace()
        t2.add_tool_call(ToolCall(tool_name="search", arguments={"q": "hello"}))
        t2.finish()

        d = diff_traces(t1, t2)
        assert d["tool_calls_added"] == []
        assert d["tool_calls_removed"] == []
        assert d["tool_call_count_delta"] == {}

    def test_new_tool_in_current(self):
        t1 = AgentTrace()
        t1.finish()
        t2 = AgentTrace()
        t2.add_tool_call(ToolCall(tool_name="web_search", arguments={}))
        t2.finish()
        d = diff_traces(t1, t2)
        assert "web_search" in d["tool_calls_added"]

    def test_removed_tool(self):
        t1 = AgentTrace()
        t1.add_tool_call(ToolCall(tool_name="old_tool", arguments={}))
        t1.finish()
        t2 = AgentTrace()
        t2.finish()
        d = diff_traces(t1, t2)
        assert "old_tool" in d["tool_calls_removed"]

    def test_count_delta(self):
        t1 = AgentTrace()
        t1.add_tool_call(ToolCall(tool_name="search", arguments={}))
        t1.add_tool_call(ToolCall(tool_name="search", arguments={}))
        t1.finish()

        t2 = AgentTrace()
        t2.add_tool_call(ToolCall(tool_name="search", arguments={}))
        t2.finish()

        d = diff_traces(t1, t2)
        assert d["tool_call_count_delta"]["search"] == (2, 1)


# ──────────────────────────────────────────────────────
# HTML Report
# ──────────────────────────────────────────────────────


class TestHTMLReport:
    def test_generates_valid_html(self):
        report = RegressionReport(
            baseline_label="v1",
            current_label="v2",
            deltas=[
                ScenarioDelta(scenario_id="s1", scenario_name="S1", delta=ResultDelta.STILL_PASS),
                ScenarioDelta(scenario_id="s2", scenario_name="S2", delta=ResultDelta.NEW_FAIL),
            ],
        )
        html = generate_html_report(report)
        assert "<!DOCTYPE html>" in html
        assert "S1" in html
        assert "S2" in html
        assert "FAIL" in html

    def test_empty_report(self):
        report = RegressionReport()
        html = generate_html_report(report)
        assert "PASS" in html

    def test_html_escaping(self):
        report = RegressionReport(
            deltas=[
                ScenarioDelta(
                    scenario_id="s<script>",
                    scenario_name="<b>XSS</b>",
                    delta=ResultDelta.STILL_PASS,
                )
            ],
        )
        html = generate_html_report(report)
        assert "<script>" not in html
        assert "&lt;b&gt;" in html


# ──────────────────────────────────────────────────────
# JUnit XML
# ──────────────────────────────────────────────────────


class TestJUnitXML:
    def test_generates_valid_xml(self):
        results = [
            _make_result("s1", True),
            _make_result("s2", False),
        ]
        xml = generate_junit_xml(results)
        assert '<?xml version="1.0"' in xml
        assert 'tests="2"' in xml
        assert 'failures="1"' in xml
        assert "S1" in xml or "Scenario s1" in xml

    def test_junit_from_report(self):
        report = RegressionReport(
            deltas=[
                ScenarioDelta(scenario_id="s1", scenario_name="S1", delta=ResultDelta.NEW_FAIL),
                ScenarioDelta(scenario_id="s2", scenario_name="S2", delta=ResultDelta.STILL_PASS),
            ],
        )
        xml = generate_junit_xml_from_report(report)
        assert 'tests="2"' in xml
        assert 'failures="1"' in xml

    def test_junit_empty(self):
        xml = generate_junit_xml([])
        assert 'tests="0"' in xml
        assert 'failures="0"' in xml
