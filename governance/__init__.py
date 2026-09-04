"""Governance Audit Framework — verify AI agent claims against objective evidence.

Usage:
    from governance import run_audit

    result = run_audit(project_root=".", output_dir="governance/reports/")
    if result.verdict == "FAIL":
        for d in result.discrepancies:
            if d.severity == Severity.CRITICAL:
                print(f"BLOCKED: {d.description}")
"""

from governance.audit import run_audit
from governance.auditor import load_auditor_config, audit
from governance.claims import extract_claims
from governance.evidence import collect_evidence
from governance.extract import extract_findings, format_report
from common.models import (
    AuditResult,
    Claim,
    Discrepancy,
    Evidence,
    Severity,
    Verdict,
)

__all__ = [
    "run_audit",
    "load_auditor_config",
    "audit",
    "extract_claims",
    "collect_evidence",
    "extract_findings",
    "format_report",
    "AuditResult",
    "Claim",
    "Discrepancy",
    "Evidence",
    "Severity",
    "Verdict",
]
