"""Governance API router.

Endpoints for running audits and fetching audit results/history.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Resolve project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_GOV_REPORTS_DIR = _PROJECT_ROOT / "governance" / "reports"

# Ensure project root is in sys.path so we can import from governance
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from governance.audit import run_audit  # noqa: E402 — sys.path must be set first

router = APIRouter(prefix="/api/governance", tags=["governance"])


class AuditRequest(BaseModel):
    """Request body for triggering an audit."""
    diary_date: str | None = Field(default=None, description="Diary date in YYYY-MM-DD format")


class FindingItem(BaseModel):
    """Single audit discrepancy/finding."""
    id: str
    severity: str
    description: str


class HistoryItem(BaseModel):
    """Audit history item."""
    id: str
    date: str
    status: str
    findings: int


class GovernanceSummaryResponse(BaseModel):
    """Compliance summary and audit history."""
    total_audits: int
    passed_audits: int
    pass_rate: int
    critical_findings: int
    last_audit: str | None = None
    findings: list[FindingItem] = Field(default_factory=list)
    history: list[HistoryItem] = Field(default_factory=list)


@router.post("/audit", response_model=dict)
async def trigger_audit(request: AuditRequest | None = None) -> dict:
    """Run a new governance audit.

    Collects evidence, extracts claims, and runs the configured auditor.
    Saves the output report to the governance reports directory.
    """
    diary_date = request.diary_date if request else None
    try:
        result = run_audit(
            project_root=str(_PROJECT_ROOT),
            diary_date=diary_date,
            output_dir=str(_GOV_REPORTS_DIR)
        )
        return result.to_dict()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Governance audit failed: {e}"
        )


@router.get("", response_model=GovernanceSummaryResponse)
async def get_governance_summary() -> GovernanceSummaryResponse:
    """Retrieve compliance scorecard, recent findings, and audit history.

    Reads completed audit report JSON files from the governance reports directory.
    """
    if not _GOV_REPORTS_DIR.exists():
        return GovernanceSummaryResponse(
            total_audits=0,
            passed_audits=0,
            pass_rate=100,
            critical_findings=0,
            last_audit=None,
            findings=[],
            history=[]
        )

    # List all json reports in descending order of filename (which sorts them chronologically)
    report_paths = sorted(_GOV_REPORTS_DIR.glob("audit-*.json"), reverse=True)

    history: list[HistoryItem] = []
    total_audits = 0
    passed_audits = 0
    last_audit_iso: str | None = None
    recent_findings: list[FindingItem] = []
    critical_findings_count = 0

    for path in report_paths:
        # Parse timestamp from filename to construct ISO date
        # filename pattern: audit-20260707-182110.json
        m = re.match(r"^audit-(\d{8}-\d{6})$", path.stem)
        if m:
            dt_str = m.group(1)
            try:
                dt = datetime.strptime(dt_str, "%Y%m%d-%H%M%S")
                iso_date = dt.isoformat() + "Z"
            except Exception:
                iso_date = datetime.fromtimestamp(path.stat().st_mtime).isoformat() + "Z"
        else:
            iso_date = datetime.fromtimestamp(path.stat().st_mtime).isoformat() + "Z"

        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        total_audits += 1
        verdict = data.get("verdict", "FAIL")
        if verdict == "PASS":
            passed_audits += 1

        discrepancies = data.get("discrepancies", [])
        findings_count = len(discrepancies)

        # The first report in descending order is the most recent
        if total_audits == 1:
            last_audit_iso = iso_date
            critical_findings_count = sum(
                1 for d in discrepancies if d.get("severity") == "CRITICAL"
            )
            # Map recent findings
            for idx, d in enumerate(discrepancies):
                recent_findings.append(
                    FindingItem(
                        id=f"f{idx + 1}",
                        severity=d.get("severity", "INFO"),
                        description=d.get("description") or d.get("summary") or "Discrepancy"
                    )
                )

        history.append(
            HistoryItem(
                id=path.stem,
                date=iso_date,
                status=verdict,
                findings=findings_count
            )
        )

    pass_rate = int(passed_audits / total_audits * 100) if total_audits > 0 else 100

    return GovernanceSummaryResponse(
        total_audits=total_audits,
        passed_audits=passed_audits,
        pass_rate=pass_rate,
        critical_findings=critical_findings_count,
        last_audit=last_audit_iso,
        findings=recent_findings,
        history=history
    )


@router.get("/reports/{report_id}", response_model=dict)
async def get_raw_report(report_id: str) -> dict:
    """Retrieve full details of a specific audit report by its file ID (stem)."""
    # Prevent directory traversal attacks
    if not re.match(r"^audit-\d{8}-\d{6}$", report_id):
        raise HTTPException(status_code=400, detail="Invalid report ID format")

    report_path = _GOV_REPORTS_DIR / f"{report_id}.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    try:
        with report_path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {e}")
