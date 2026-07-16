#!/usr/bin/env python3
"""Example: Run a governance audit on the current project.

This script demonstrates how to use the governance module as a library
to audit a project and inspect the results programmatically.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from governance import run_audit
from common.models import Severity, Verdict


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else "."

    print(f"Running governance audit on: {project_root}\n")

    result = run_audit(
        project_root=project_root,
        output_dir="governance/reports/",
    )

    # Print verdict
    print(f"Verdict: {result.verdict.value.upper()}")
    print(f"Critical: {result.critical_count}")
    print(f"Warnings: {result.warning_count}")

    # Print discrepancies
    if result.discrepancies:
        print("\nDiscrepancies:")
        for d in result.discrepancies:
            icon = {"critical": "X", "warning": "!", "info": "i"}.get(d.severity.value, "?")
            print(f"  [{icon}] {d.description}")
            if d.claimed and d.actual:
                print(f"      Claimed: {d.claimed}")
                print(f"      Actual:  {d.actual}")
    else:
        print("\nNo discrepancies found.")

    # Exit code: non-zero if CRITICAL issues
    if result.verdict == Verdict.FAIL and result.critical_count > 0:
        print("\nBLOCKED by CRITICAL issues")
        sys.exit(1)
    elif result.warning_count > 0:
        print("\nPassed with warnings")
        sys.exit(0)
    else:
        print("\nAll checks passed")
        sys.exit(0)


if __name__ == "__main__":
    main()