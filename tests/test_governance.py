"""Tests for governance modules — evidence, claims, extract, auditor config, and library API."""

import json
from datetime import date, timedelta

from common.models import AuditResult, Severity, Verdict

# ─── Evidence collection ──────────────────────────────────────────

class TestEvidenceCollection:
    """Evidence collection should read from config and handle missing dirs."""

    def test_collect_evidence_returns_dict(self, tmp_path):
        from governance.evidence import collect_evidence
        result = collect_evidence(str(tmp_path))
        assert isinstance(result, dict)
        assert "tests" in result
        assert "source_files" in result
        assert "actual_tool_count" in result

    def test_collect_evidence_with_no_src_dir(self, tmp_path):
        from governance.evidence import collect_evidence
        result = collect_evidence(str(tmp_path))
        # Should not crash, just return empty results
        assert result["actual_tool_count"] == 0
        assert result["source_files"] == []

    def test_collect_evidence_with_src_dir(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("def hello(): pass")
        (src / "utils.py").write_text("def helper(): pass")

        from governance.evidence import collect_evidence
        result = collect_evidence(str(tmp_path))
        assert len(result["source_files"]) == 2

    def test_collect_evidence_counts_mcp_tools(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "server.py").write_text(
            '@mcp.tool()\ndef tool_a(): pass\n\n@mcp.tool()\ndef tool_b(): pass'
        )

        # Point config at our test dir
        config_file = tmp_path / "agent-frameworks.yaml"
        config_file.write_text('governance:\n  src_dir: "src"\n  mcp_server_file: "src/server.py"\n')

        from governance.evidence import collect_evidence
        result = collect_evidence(str(tmp_path))
        assert result["actual_tool_count"] == 2

    def test_collect_evidence_with_no_test_dir(self, tmp_path):
        from governance.evidence import collect_evidence
        result = collect_evidence(str(tmp_path))
        assert result["tests"]["passed"] == 0
        assert result["tests"]["failed"] == 0

    def test_collect_evidence_diary_timestamps(self, tmp_path):
        updates = tmp_path / "updates"
        updates.mkdir()
        (updates / "2026-06-27.md").write_text("# Day 1")

        from governance.evidence import collect_evidence
        result = collect_evidence(str(tmp_path))
        assert "2026-06-27.md" in result["diary_timestamps"]


# ─── Claims extraction ────────────────────────────────────────────

class TestClaimsExtraction:
    """Claims extraction should parse diary entries and extract verifiable claims."""

    def _make_diary(self, tmp_path, content):
        diary = tmp_path / "updates" / "2026-06-27.md"
        diary.parent.mkdir(exist_ok=True)
        diary.write_text(content)
        return str(diary)

    def test_extract_date_from_path(self):
        from governance.claims import extract_date
        assert extract_date("/path/to/2026-06-27.md") == "2026-06-27"
        assert extract_date("/path/to/diary.md") == "unknown"

    def test_extract_test_counts(self):
        from governance.claims import extract_test_counts
        text = "All 68/68 tests pass. Previously had 53/53 passing."
        counts = extract_test_counts(text)
        assert len(counts) == 2
        assert counts[0]["claimed_passing"] == 68
        assert counts[1]["claimed_passing"] == 53

    def test_extract_tools_count(self):
        from governance.claims import extract_tools_count
        text = "Started with 12 tools. Now have 13 MCP tools."
        assert extract_tools_count(text) == 13

    def test_extract_version(self):
        from governance.claims import extract_version
        assert extract_version("Released v0.13.0 today") == "0.13.0"
        assert extract_version("No version mentioned") == "unknown"

    def test_extract_features(self):
        from governance.claims import extract_features
        text = "- **Conflict detection** added\n- **Auto-confirm** feature\n- Regular bullet"
        features = extract_features(text)
        assert len(features) == 2
        assert "Conflict detection" in features

    def test_extract_files_modified(self):
        from governance.claims import extract_files_modified
        text = "## Files Modified\n- `server.py`\n- `storage.py`\n\n## Other Section"
        files = extract_files_modified(text)
        assert len(files) == 2
        assert "server.py" in files

    def test_extract_key_sections(self):
        from governance.claims import extract_key_sections
        text = "# Title\n## Summary\nDid stuff\n## Details\nMore stuff"
        sections = extract_key_sections(text)
        assert "Summary" in sections
        assert "Did stuff" in sections["Summary"]

    def test_extract_claims_full(self, tmp_path):
        from governance.claims import extract_claims
        diary = self._make_diary(tmp_path, """# Daily Update
## Summary
- **Conflict detection** added
## Test Results
68/68 tests passing
## Version
Released v0.13.0
13 MCP tools now available
## Files Modified
- `server.py`
- `storage.py`
""")
        claims = extract_claims(diary)
        assert claims["date"] == "2026-06-27"
        assert claims["version"] == "0.13.0"
        assert claims["tools_count"] == 13
        assert len(claims["test_counts"]) > 0
        assert claims["test_counts"][0]["claimed_passing"] == 68
        assert "Conflict detection" in claims["features"]
        assert "server.py" in claims["files_modified"]

    def test_custom_patterns(self, tmp_path):
        from governance.claims import extract_claims
        diary = self._make_diary(tmp_path, "Deployed to 3 regions. 99.9% uptime.")
        claims = extract_claims(diary, custom_patterns={
            "region_count": r"(\d+)\s*regions?",
        })
        assert "region_count" in claims
        assert "3" in claims["region_count"]


# ─── Extract (deterministic comparator) ───────────────────────────

class TestExtractFindings:
    """The deterministic comparator should catch discrepancies."""

    def test_empty_report_is_critical(self):
        from governance.extract import extract_findings
        findings = extract_findings("")
        assert findings["verdict"] == "FAIL"
        assert findings["auditor_error"] is not None
        assert any(d["severity"] == "CRITICAL" for d in findings["discrepancies"])

    def test_auditor_error_is_critical(self):
        from governance.extract import extract_findings
        findings = extract_findings("AUDITOR ERROR: Model not found")
        assert findings["verdict"] == "FAIL"
        assert "auditor_unavailable" in [d["type"] for d in findings["discrepancies"]]

    def test_valid_json_parsed(self):
        from governance.extract import extract_findings
        report = json.dumps({
            "claims_total": 5,
            "verified": 4,
            "discrepancies": [
                {"severity": "WARNING", "summary": "Minor mismatch"}
            ],
            "verdict": "WARN",
        })
        findings = extract_findings(report)
        assert findings["model_emitted_json"] is True
        assert len(findings["discrepancies"]) >= 1

    def test_json_in_markdown_fence(self):
        from governance.extract import extract_findings
        report = '```json\n{"verdict": "PASS", "discrepancies": []}\n```'
        findings = extract_findings(report)
        assert findings["model_emitted_json"] is True

    def test_test_count_mismatch_is_critical(self):
        from governance.extract import extract_findings
        claims = {"test_counts": [{"claimed_passing": 10, "claimed_total": 10}]}
        evidence = {"tests": {"passed": 8, "failed": 2}}
        findings = extract_findings("{}", claims, evidence)
        types = [d["type"] for d in findings["discrepancies"]]
        assert "test_count_mismatch" in types

    def test_tool_count_mismatch_is_critical(self):
        from governance.extract import extract_findings
        claims = {"tools_count": 13}
        evidence = {"actual_tool_count": 10}
        findings = extract_findings("{}", claims, evidence)
        types = [d["type"] for d in findings["discrepancies"]]
        assert "tool_count_mismatch" in types

    def test_future_dated_diary_is_critical(self):
        from governance.extract import extract_findings
        future = (date.today() + timedelta(days=1)).isoformat()
        claims = {"date": future}
        evidence = {}
        findings = extract_findings("{}", claims, evidence)
        types = [d["type"] for d in findings["discrepancies"]]
        assert "future_dated_diary" in types

    def test_missing_claimed_file(self):
        from governance.extract import extract_findings
        claims = {"files_modified": ["nonexistent_file.py"]}
        evidence = {"project_root": "/tmp/empty_project_xyz"}
        findings = extract_findings("{}", claims, evidence)
        types = [d["type"] for d in findings["discrepancies"]]
        assert "claimed_file_missing" in types

    def test_pass_when_no_discrepancies(self):
        from governance.extract import extract_findings
        report = json.dumps({"verdict": "PASS", "discrepancies": []})
        findings = extract_findings(report)
        assert findings["verdict"] == "PASS"

    def test_format_report_contains_verdict(self):
        from governance.extract import extract_findings, format_report
        findings = extract_findings("")  # will be FAIL
        report = format_report(findings)
        assert "FAIL" in report
        assert "GOVERNANCE AUDIT" in report


# ─── Auditor config ───────────────────────────────────────────────

class TestAuditorConfig:
    """Auditor config should load from yaml and support env overrides."""

    def test_load_default_config(self):
        from governance.auditor import load_auditor_config
        cfg = load_auditor_config()
        assert "backend" in cfg
        assert "primary" in cfg
        assert cfg["backend"]["type"] == "none"  # Default is deterministic-only

    def test_default_model(self):
        from governance.auditor import load_auditor_config
        cfg = load_auditor_config()
        # Model configured in auditor.yaml — base granite-4.1-3b
        assert "granite" in cfg["primary"]["model"].lower()

    def test_env_override_url(self, monkeypatch):
        monkeypatch.setenv("AGENT_FW_AUDITOR_URL", "http://custom:9999/v1/chat/completions")
        from governance.auditor import load_auditor_config
        cfg = load_auditor_config()
        assert cfg["backend"]["url"] == "http://custom:9999/v1/chat/completions"

    def test_env_override_model(self, monkeypatch):
        monkeypatch.setenv("AGENT_FW_AUDITOR_MODEL", "custom/model-1b")
        from governance.auditor import load_auditor_config
        cfg = load_auditor_config()
        assert cfg["primary"]["model"] == "custom/model-1b"


# ─── Library API ──────────────────────────────────────────────────

class TestGovernanceAPI:
    """The governance package should expose a clean Python API."""

    def test_import_all_public_names(self):
        from governance import (
            collect_evidence,
            extract_claims,
            run_audit,
        )
        # Just verify all imports work
        assert callable(run_audit)
        assert callable(extract_claims)
        assert callable(collect_evidence)

    def test_run_audit_returns_audit_result(self, tmp_path, monkeypatch):
        import subprocess
        from types import SimpleNamespace

        from governance import run_audit

        # Stub subprocess.run so collect_evidence does not recursively invoke
        # the real pytest suite. evidence.py only reads returncode and stdout
        # from the result, so a SimpleNamespace is enough.
        fake_result = SimpleNamespace(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        # Create minimal project structure
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "updates").mkdir()
        (tmp_path / "updates" / "2026-06-27.md").write_text("# Update")

        result = run_audit(str(tmp_path))
        assert isinstance(result, AuditResult)
        assert result.verdict in (Verdict.PASS, Verdict.WARN, Verdict.FAIL)

    def test_severity_enum(self):
        assert Severity.CRITICAL == "CRITICAL"
        assert Severity.WARNING == "WARNING"
        assert Severity.INFO == "INFO"

    def test_verdict_enum(self):
        assert Verdict.PASS == "PASS"
        assert Verdict.WARN == "WARN"
        assert Verdict.FAIL == "FAIL"
