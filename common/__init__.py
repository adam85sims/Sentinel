"""Agent Frameworks — Shared infrastructure for autonomous agent tools."""

__version__ = "0.1.0"

from common.config import Config, load_config, deep_merge
from common.logging import get_logger, setup_logging
from common.models import (
    AuditResult,
    Claim,
    Discrepancy,
    Evidence,
    Severity,
    Verdict,
)

__all__ = [
    "Config",
    "load_config",
    "deep_merge",
    "get_logger",
    "setup_logging",
    "AuditResult",
    "Claim",
    "Discrepancy",
    "Evidence",
    "Severity",
    "Verdict",
    "__version__",
]
