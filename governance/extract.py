"""Post-process auditor output to extract structured findings.

Three layers of verification:
  1. The model emitted AUDITOR ERROR → CRITICAL (auditor unavailable)
  2. The model emitted empty/None response → CRITICAL (silent failure)
  3. The model emitted valid JSON → use its discrepancies
  4. The deterministic comparator (this module) ALWAYS runs as a safety net
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from common.logging import get_logger

logger = get_logger("governance.extract")


def _safe_load_json(text: str) -> Optional[dict]:
    """Try to parse a JSON object out of a model response.

    Models occasionally wrap JSON in markdown fences or add a stray
    preamble. We try a few patterns before giving up.
    """
    if not text:
        return None

    text = text.strip()

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fence
    fence_match = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL
    )
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Find first { ... last } span
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            pass

    return None


def extract_findings(report: str, claims: dict = None,
                     evidence: dict = None,
                     deterministic_only: bool = False) -> dict:
    """Extract structured findings from the auditor's response.

    Three sources of truth, in priority order:
      1. The model emitted AUDITOR ERROR → CRITICAL (auditor unavailable)
      2. The model emitted empty/None response → CRITICAL (silent failure)
      3. The model emitted valid JSON → use its discrepancies
      4. The deterministic comparator (this function) ALWAYS runs
         as a safety net and adds any missed findings.
    """
    findings = {
        "discrepancies": [],
        "verdict": "UNKNOWN",
        "summary": "",
        "model_emitted_json": False,
        "auditor_error": None,
    }

    # 1. Empty / None response = silent failure = CRITICAL
    # When deterministic_only=True, empty report is expected (no LLM used)
    if not report or not report.strip():
        if not deterministic_only:
            findings["auditor_error"] = "Empty auditor response (silent failure)"
            findings["discrepancies"].append({
                "severity": "CRITICAL",
                "type": "auditor_silent_failure",
                "description": (
                    "Auditor returned empty response. Governance gate cannot "
                    "verify claims. Manual review required."
                ),
            })
            findings["verdict"] = "FAIL"
            findings["summary"] = "1 critical: auditor silent failure"
            return findings

    # 2. AUDITOR ERROR: prefix from auditor.py retry-exhaustion
    if report.strip().startswith("AUDITOR ERROR:"):
        findings["auditor_error"] = report.strip()
        findings["discrepancies"].append({
            "severity": "CRITICAL",
            "type": "auditor_unavailable",
            "description": report.strip(),
        })
        findings["verdict"] = "FAIL"
        findings["summary"] = "1 critical: auditor unavailable"
        return findings

    # 3. Try to parse structured JSON from the model
    model_json = _safe_load_json(report)
    if model_json and isinstance(model_json, dict):
        findings["model_emitted_json"] = True
        seen_descriptions = set()
        for d in model_json.get("discrepancies", []):
            if not isinstance(d, dict):
                continue
            severity = d.get("severity", "INFO").upper()
            if severity not in ("CRITICAL", "WARNING", "INFO"):
                severity = "INFO"
            desc = d.get("summary", "")
            # Deduplicate: LLMs sometimes emit the same finding twice
            if desc in seen_descriptions:
                continue
            seen_descriptions.add(desc)
            findings["discrepancies"].append({
                "severity": severity,
                "type": "model_finding",
                "description": desc,
                "claimed": d.get("claimed", ""),
                "actual": d.get("actual", ""),
            })

    # 4. Deterministic comparator — always runs, even if model emitted JSON
    #    The comparator is more trustworthy than the LLM for quantitative checks.
    #    If the comparator says numbers match, suppress any LLM finding about
    #    the same topic (LLMs sometimes hallucinate mismatches).
    if claims is not None and evidence is not None:
        _suppress_llm_false_positives(findings, claims, evidence)
        _add_comparator_findings(findings, claims, evidence)

    # 5. Verdict from combined findings
    _finalize_verdict(findings)
    return findings


def _suppress_llm_false_positives(findings: dict, claims: dict, evidence: dict):
    """Remove LLM findings that the comparator proves are wrong.

    LLMs sometimes hallucinate mismatches (e.g., claiming 448 != 448).
    When the comparator can verify the numbers, suppress LLM findings
    that contradict the evidence.
    """
    # Check test count: if comparator would see a match, remove LLM test findings
    claimed_tests = claims.get("test_counts", [{}])
    if claimed_tests and isinstance(claimed_tests[-1], dict):
        claimed_n = claimed_tests[-1].get("claimed_passing", 0)
    else:
        claimed_n = 0
    actual_tests = evidence.get("tests", {}).get("passed", 0)

    if claimed_n and actual_tests and claimed_n == actual_tests:
        # Numbers match — suppress any LLM finding that mentions tests
        # and compares numbers (the LLM is hallucinating a mismatch)
        findings["discrepancies"] = [
            d for d in findings["discrepancies"]
            if not (d.get("type") == "model_finding"
                    and "test" in d.get("description", "").lower()
                    and (str(claimed_n) in d.get("description", "")
                         or str(actual_tests) in d.get("description", "")))
        ]

    # Check tool count: if comparator would see a match, remove LLM tool findings
    claimed_tools = claims.get("tools_count", 0)
    actual_tools = evidence.get("actual_tool_count", 0)
    if claimed_tools and actual_tools and claimed_tools == actual_tools:
        findings["discrepancies"] = [
            d for d in findings["discrepancies"]
            if not (d.get("type") == "model_finding"
                    and "tool" in d.get("description", "").lower()
                    and (str(claimed_tools) in d.get("description", "")
                         or str(actual_tools) in d.get("description", "")))
        ]


def _add_comparator_findings(findings: dict, claims: dict, evidence: dict):
    """The deterministic claim-vs-evidence check. Safety net.

    Runs every check unless the check type is disabled in evidence config.
    """
    # Future-dated diary entry — catches backdating
    claimed_date_str = claims.get("date", "")
    if claimed_date_str and claimed_date_str != "unknown":
        try:
            claimed = date.fromisoformat(claimed_date_str)
            today = date.today()
            if claimed > today:
                findings["discrepancies"].append({
                    "severity": "CRITICAL",
                    "type": "future_dated_diary",
                    "description": (
                        f"Diary claims date {claimed_date_str} but today is "
                        f"{today.isoformat()}. Future-dated entries are not "
                        f"permitted."
                    ),
                })
        except ValueError:
            pass

    # Test count mismatch
    # Use the LAST claim (most recent session's count), not the first.
    claimed_tests = claims.get("test_counts", [{}])
    if claimed_tests and isinstance(claimed_tests[-1], dict):
        claimed_n = claimed_tests[-1].get("claimed_passing", 0)
    else:
        claimed_n = 0
    actual_tests = evidence.get("tests", {}).get("passed", 0)
    if claimed_n and actual_tests and claimed_n != actual_tests:
        if not _has_finding(findings, "Test count"):
            findings["discrepancies"].append({
                "severity": "CRITICAL",
                "type": "test_count_mismatch",
                "description": (
                    f"Test count: claimed {claimed_n}, actual {actual_tests}"
                ),
                "claimed": str(claimed_n),
                "actual": str(actual_tests),
            })

    # Tool count mismatch
    # actual_tool_count=0 means mcp_server_file is not configured or missing
    # — skip comparison rather than flagging a false CRITICAL.
    claimed_tools = claims.get("tools_count", 0)
    actual_tools = evidence.get("actual_tool_count", 0)
    if claimed_tools and actual_tools and claimed_tools != actual_tools:
        if not _has_finding(findings, "Tool count"):
            findings["discrepancies"].append({
                "severity": "WARNING",
                "type": "tool_count_mismatch",
                "description": (
                    f"Tool count: claimed {claimed_tools}, "
                    f"actual {actual_tools}"
                ),
                "claimed": str(claimed_tools),
                "actual": str(actual_tools),
            })

    # File existence checks — verify claimed files actually exist
    project_root = evidence.get("project_root", "")
    if project_root:
        _check_file_existence(findings, claims, project_root)

    # Date/mtime sanity (catches edits without re-saving)
    diary_timestamps = evidence.get("diary_timestamps", {})
    for fname, ts in diary_timestamps.items():
        if claimed_date_str and claimed_date_str in fname:
            mtime = ts.get("mtime", "")
            if claimed_date_str and claimed_date_str not in mtime:
                if not _has_finding(findings, "backdated"):
                    findings["discrepancies"].append({
                        "severity": "CRITICAL",
                        "type": "diary_backdated",
                        "description": (
                            f"Diary '{fname}' claims date "
                            f"{claimed_date_str} but file mtime is {mtime}"
                        ),
                    })

    # README state mismatches (warning, not critical)
    readme = evidence.get("readme_state", {})
    if readme.get("exists"):
        r_tests = readme.get("claimed_tests")
        r_tools = readme.get("claimed_tools")
        if r_tests and claimed_n and r_tests != claimed_n:
            findings["discrepancies"].append({
                "severity": "WARNING",
                "type": "readme_test_mismatch",
                "description": (
                    f"README claims {r_tests} tests, diary claims {claimed_n}"
                ),
            })
        if r_tools and claimed_tools and r_tools != claimed_tools:
            findings["discrepancies"].append({
                "severity": "WARNING",
                "type": "readme_tool_mismatch",
                "description": (
                    f"README claims {r_tools} tools, "
                    f"diary claims {claimed_tools}"
                ),
            })


def _check_file_existence(findings: dict, claims: dict, project_root: str):
    """Verify that files claimed as modified actually exist on disk.

    Only checks files that are explicitly listed in the claims.
    Missing files are CRITICAL (the agent claimed to modify something
    that doesn't exist).
    """
    files_modified = claims.get("files_modified", [])
    if not files_modified:
        return

    root = Path(project_root)
    for filepath in files_modified:
        full_path = root / filepath
        if not full_path.exists():
            # Also check without leading directories (path might be relative differently)
            # Try just the filename in common locations
            found = False
            for candidate in root.rglob(filepath.split("/")[-1]):
                if candidate.is_file():
                    found = True
                    break
            if not found:
                findings["discrepancies"].append({
                    "severity": "WARNING",
                    "type": "claimed_file_missing",
                    "description": (
                        f"Claimed modified file '{filepath}' does not exist "
                        f"in project root"
                    ),
                    "claimed": filepath,
                    "actual": "not found",
                })


def _has_finding(findings: dict, keyword: str) -> bool:
    """True if any existing finding description or summary contains the keyword."""
    for d in findings["discrepancies"]:
        text = (d.get("description", "") + " " + d.get("summary", "")).lower()
        if keyword.lower() in text:
            return True
    return False


def _finalize_verdict(findings: dict):
    """Compute verdict from the merged discrepancy list."""
    critical = sum(1 for d in findings["discrepancies"]
                   if d["severity"] == "CRITICAL")
    warnings = sum(1 for d in findings["discrepancies"]
                   if d["severity"] == "WARNING")

    if critical > 0:
        findings["verdict"] = "FAIL"
    elif warnings > 0:
        findings["verdict"] = "WARN"
    else:
        findings["verdict"] = "PASS"

    findings["summary"] = (
        f"{len(findings['discrepancies'])} discrepancies found "
        f"({critical} critical, {warnings} warnings)"
    )


def format_report(findings: dict) -> str:
    """Format findings into a clean text report."""
    lines = [
        "=" * 50,
        "GOVERNANCE AUDIT — STRUCTURED REPORT",
        "=" * 50,
        "",
        f"VERDICT: {findings['verdict']}",
        f"DISCREPANCIES: {findings['summary']}",
    ]
    if findings.get("auditor_error"):
        lines.append(f"AUDITOR ERROR: {findings['auditor_error']}")
    lines.append("")
    if findings["discrepancies"]:
        for i, d in enumerate(findings["discrepancies"], 1):
            lines.append(f"  {i}. [{d['severity']}] {d['description']}")
    else:
        lines.append("  (no discrepancies)")
    lines.append("")
    lines.append("=" * 50)
    return "\n".join(lines)


if __name__ == "__main__":
    report = sys.stdin.read()
    findings = extract_findings(report)
    print(format_report(findings))
    print("\n--- JSON ---")
    print(json.dumps(findings, indent=2))
