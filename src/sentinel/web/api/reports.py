"""Report Download API — generate and serve HTML/JUnit reports.

Provides endpoints for downloading Sentinel reports in various formats.
Wraps the core reporting module for the WebUI.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Resolve project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


@router.get("/{baseline_label}/html")
async def download_html_report(baseline_label: str) -> HTMLResponse:
    """Generate and download an HTML report for a baseline."""
    try:
        from sentinel.baseline import load_baseline
        from sentinel.reporting import generate_html_report

        baseline = load_baseline(baseline_label)
        if baseline is None:
            raise HTTPException(status_code=404, detail=f"Baseline '{baseline_label}' not found")

        html = generate_html_report(baseline)
        return HTMLResponse(content=html)
    except ImportError:
        raise HTTPException(status_code=500, detail="Report generation requires the sentinel core package")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {e}")


@router.get("/{baseline_label}/junit")
async def download_junit_report(baseline_label: str) -> Response:
    """Generate and download a JUnit XML report for a baseline."""
    try:
        from sentinel.baseline import load_baseline
        from sentinel.reporting import generate_junit_xml

        baseline = load_baseline(baseline_label)
        if baseline is None:
            raise HTTPException(status_code=404, detail=f"Baseline '{baseline_label}' not found")

        xml = generate_junit_xml(baseline)
        return Response(
            content=xml,
            media_type="application/xml",
            headers={"Content-Disposition": f"attachment; filename=sentinel-{baseline_label}.xml"},
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="Report generation requires the sentinel core package")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {e}")


@router.get("/compare/{label_a}/{label_b}/html")
async def download_comparison_report(label_a: str, label_b: str) -> HTMLResponse:
    """Generate and download a regression comparison report."""
    try:
        from sentinel.baseline import load_baseline
        from sentinel.reporting import build_regression_report, generate_html_report

        baseline_a = load_baseline(label_a)
        baseline_b = load_baseline(label_b)
        if baseline_a is None:
            raise HTTPException(status_code=404, detail=f"Baseline '{label_a}' not found")
        if baseline_b is None:
            raise HTTPException(status_code=404, detail=f"Baseline '{label_b}' not found")

        report = build_regression_report(baseline_a, baseline_b)
        html = generate_html_report(report)
        return HTMLResponse(content=html)
    except ImportError:
        raise HTTPException(status_code=500, detail="Report generation requires the sentinel core package")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {e}")
