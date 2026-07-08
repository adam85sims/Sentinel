"""Shared data models for agent-frameworks.

These dataclasses represent the core data flowing between modules:
evidence collection, claim extraction, audit results, and discrepancies.

All models support to_dict() / from_dict() for JSON serialization boundaries.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    """Audit finding severity tiers."""
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class Verdict(str, Enum):
    """Audit verdict outcomes."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class Discrepancy:
    """A single discrepancy found during audit.

    Attributes:
        severity: How serious the finding is (CRITICAL/WARNING/INFO).
        type: Machine-readable type identifier (e.g., "test_count_mismatch").
        description: Human-readable explanation.
        claimed: The value the agent claimed (optional).
        actual: The value actually observed (optional).
    """
    severity: Severity
    type: str
    description: str
    claimed: Optional[str] = None
    actual: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value if isinstance(self.severity, Severity) else self.severity,
            "type": self.type,
            "description": self.description,
            "claimed": self.claimed,
            "actual": self.actual,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Discrepancy":
        severity = data.get("severity", "INFO")
        if isinstance(severity, str):
            severity = Severity(severity)
        return cls(
            severity=severity,
            type=data.get("type", "unknown"),
            description=data.get("description", ""),
            claimed=data.get("claimed"),
            actual=data.get("actual"),
        )


@dataclass
class Evidence:
    """Independently collected facts about a project's state.

    This is gathered BEFORE reading any claims — pure observation.
    """
    collected_at: str = ""
    project_root: str = ""
    tests_passed: int = 0
    tests_failed: int = 0
    tests_total: int = 0
    actual_tool_count: int = 0
    actual_test_count: int = 0
    source_files: list = field(default_factory=list)
    diary_timestamps: dict = field(default_factory=dict)
    readme_state: dict = field(default_factory=dict)
    file_timestamps: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Evidence":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Claim:
    """An extracted claim from a diary entry.

    Represents what the agent SAID it did, to be verified against Evidence.
    """
    date: str = "unknown"
    test_counts: list = field(default_factory=list)
    tools_count: int = 0
    version: str = "unknown"
    features: list = field(default_factory=list)
    files_modified: list = field(default_factory=list)
    raw_sections: dict = field(default_factory=dict)
    file: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Claim":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AuditResult:
    """The complete output of a governance audit.

    This is the top-level object returned by run_audit().
    """
    verdict: Verdict = Verdict.PASS
    discrepancies: list = field(default_factory=list)
    summary: str = ""
    claims: Optional[Claim] = None
    evidence: Optional[Evidence] = None
    auditor_model: str = "unknown"
    raw_report: str = ""
    model_emitted_json: bool = False
    auditor_error: Optional[str] = None

    @property
    def critical_count(self) -> int:
        return sum(1 for d in self.discrepancies
                   if (d.severity if isinstance(d.severity, Severity) else Severity(d.severity)) == Severity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.discrepancies
                   if (d.severity if isinstance(d.severity, Severity) else Severity(d.severity)) == Severity.WARNING)

    def to_dict(self) -> dict:
        result = {
            "verdict": self.verdict.value if isinstance(self.verdict, Verdict) else self.verdict,
            "discrepancies": [d.to_dict() if hasattr(d, "to_dict") else d for d in self.discrepancies],
            "summary": self.summary,
            "auditor_model": self.auditor_model,
            "raw_report": self.raw_report,
            "model_emitted_json": self.model_emitted_json,
            "auditor_error": self.auditor_error,
        }
        if self.claims:
            result["claims"] = self.claims.to_dict()
        if self.evidence:
            result["evidence"] = self.evidence.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "AuditResult":
        verdict = data.get("verdict", "PASS")
        if isinstance(verdict, str):
            verdict = Verdict(verdict)
        discrepancies = [
            Discrepancy.from_dict(d) if isinstance(d, dict) else d
            for d in data.get("discrepancies", [])
        ]
        claims = Claim.from_dict(data["claims"]) if data.get("claims") else None
        evidence = Evidence.from_dict(data["evidence"]) if data.get("evidence") else None
        return cls(
            verdict=verdict,
            discrepancies=discrepancies,
            summary=data.get("summary", ""),
            claims=claims,
            evidence=evidence,
            auditor_model=data.get("auditor_model", "unknown"),
            raw_report=data.get("raw_report", ""),
            model_emitted_json=data.get("model_emitted_json", False),
            auditor_error=data.get("auditor_error"),
        )
