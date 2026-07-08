#!/usr/bin/env python3
"""HERMES GOVERNANCE HARNESS
=========================
Independent audit of autonomous agent output.

Flow:
  1. Collect evidence (independent observation)
  2. Extract claims (from diary entry)
  3. Send both to the configured LLM auditor
  4. Post-process with deterministic comparator safety net
  5. Store report + return AuditResult

Usage:
    # As a library:
    from governance import run_audit
    result = run_audit(".")

    # As a CLI:
    python3 governance/audit.py . --output governance/reports/
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from common.config import load_config
from common.logging import get_logger, setup_logging
from common.models import AuditResult, AuditResult, Verdict

from governance.auditor import audit, load_auditor_config
from governance.claims import extract_claims
from governance.evidence import collect_evidence
from governance.extract import extract_findings, format_report

logger = get_logger("governance.audit")


def run_audit(project_root: str, diary_date: str = None,
              output_dir: str = None) -> AuditResult:
    """Run a full governance audit.

    Args:
        project_root: Path to the project root directory.
        diary_date: Specific diary date to audit (YYYY-MM-DD).
                    If None, uses the most recent diary entry.
        output_dir: Directory to save reports. If None, no files written.

    Returns:
        AuditResult with verdict, discrepancies, claims, and evidence.
    """
    root = Path(project_root)

    # Load project config
    config = load_config(root=root)
    gov_cfg = config.get("governance", {})

    # Step 1: Collect evidence FIRST (before reading any claims)
    logger.info("[1/5] Collecting evidence...")
    evidence_dict = collect_evidence(str(root))

    # Step 2: Find the diary entry
    diary_dir_name = gov_cfg.get("diary_dir", "updates")
    diary_dir = root / diary_dir_name

    if diary_date:
        diary_path = diary_dir / f"{diary_date}.md"
        if not diary_path.exists():
            logger.error("No diary entry for %s found in %s", diary_date, diary_dir)
            return AuditResult(
                verdict=Verdict.FAIL,
                summary=f"No diary entry for {diary_date}",
            )
    else:
        # Use the most recent diary entry
        if diary_dir.exists():
            diaries = sorted(diary_dir.glob("*.md"))
        else:
            diaries = []
        if not diaries:
            logger.error("No diary entries found in %s", diary_dir)
            return AuditResult(
                verdict=Verdict.FAIL,
                summary=f"No diary entries found in {diary_dir}",
            )
        diary_path = diaries[-1]

    logger.info("[2/5] Extracting claims from %s...", diary_path.name)
    claims_dict = extract_claims(str(diary_path))

    # Clean claims for LLM: collapse test_counts to the most recent entry
    # so the auditor doesn't get confused by historical counts in multi-session diaries.
    if claims_dict.get("test_counts"):
        claims_dict["test_counts"] = [claims_dict["test_counts"][-1]]

    # Step 3: Send to auditor
    auditor_cfg = load_auditor_config(root)
    auditor_model = auditor_cfg.get("primary", {}).get("model", "unknown")
    logger.info("[3/5] Sending to %s auditor...", auditor_model)
    raw_report = audit(claims_dict, evidence_dict, config=auditor_cfg)

    # Step 4: Post-process to extract structured findings
    logger.info("[4/5] Extracting findings...")
    findings = extract_findings(raw_report, claims_dict, evidence_dict)

    # Escalation: if primary model failed OR didn't emit valid JSON,
    # try the escalation model and merge findings.
    if (not findings.get("model_emitted_json")
            or findings.get("auditor_error")):
        esc_model = auditor_cfg.get("escalation")
        if esc_model:
            logger.info(
                "[4/5] Primary model failed/unparseable, "
                "escalating to %s...",
                esc_model.get("model"),
            )
            esc_raw = audit(claims_dict, evidence_dict, config=auditor_cfg,
                            use_escalation=True)
            esc_findings = extract_findings(esc_raw, claims_dict, evidence_dict)
            if esc_findings.get("model_emitted_json"):
                findings = esc_findings
                raw_report = (
                    f"--- PRIMARY FAILED ---\n{raw_report}\n\n"
                    f"--- ESCALATION ({esc_model.get('model')}) ---\n"
                    f"{esc_raw}"
                )

    # Step 5: Build AuditResult
    logger.info("[5/5] Building audit result...")
    result = AuditResult(
        verdict=_parse_verdict(findings.get("verdict", "UNKNOWN")),
        discrepancies=[
            _dict_to_discrepancy(d) for d in findings.get("discrepancies", [])
        ],
        summary=findings.get("summary", ""),
        auditor_model=auditor_model,
        raw_report=raw_report,
        model_emitted_json=findings.get("model_emitted_json", False),
        auditor_error=findings.get("auditor_error"),
    )

    # Store reports if output_dir specified
    if output_dir:
        _save_reports(result, output_dir, diary_path, auditor_model)

    logger.info("Audit complete: %s", result.verdict.value)
    return result


def _parse_verdict(value: str) -> Verdict:
    """Parse verdict string to Verdict enum."""
    try:
        return Verdict(value)
    except ValueError:
        return Verdict.FAIL


def _dict_to_discrepancy(d: dict):
    """Convert a discrepancy dict to a Discrepancy dataclass."""
    from common.models import Discrepancy, Severity
    severity = d.get("severity", "INFO")
    try:
        severity = Severity(severity)
    except ValueError:
        severity = Severity.INFO
    return Discrepancy(
        severity=severity,
        type=d.get("type", "unknown"),
        description=d.get("description", ""),
        claimed=d.get("claimed"),
        actual=d.get("actual"),
    )


def _save_reports(result: AuditResult, output_dir: str,
                  diary_path: Path, auditor_model: str):
    """Save audit reports in both JSON and human-readable formats."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # JSON report
    report_path = out / f"audit-{timestamp}.json"
    report_path.write_text(json.dumps(result.to_dict(), indent=2))
    logger.info("Report saved to %s", report_path)

    # Human-readable report
    txt_path = out / f"audit-{timestamp}.txt"
    txt_path.write_text(f"""GOVERNANCE AUDIT REPORT
======================
Date: {result.auditor_model}
Diary: {diary_path}
Auditor: {auditor_model}

VERDICT: {result.verdict.value}
{result.summary}

{format_report(result.to_dict())}

RAW AUDITOR OUTPUT
{result.raw_report}
""")
    logger.info("Human-readable: %s", txt_path)


def main():
    parser = argparse.ArgumentParser(description="Governance Audit Framework")
    parser.add_argument("project_root", help="Path to the project root")
    parser.add_argument("--diary", help="Diary date to audit (YYYY-MM-DD)", default=None)
    parser.add_argument("--output", help="Output directory for reports", default=None)
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")

    args = parser.parse_args()

    # Set up logging for CLI usage
    setup_logging(level="INFO")

    result = run_audit(args.project_root, args.diary, args.output)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_report(result.to_dict()))


if __name__ == "__main__":
    main()
