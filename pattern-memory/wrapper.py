#!/usr/bin/env python3
"""Pattern Memory — Session Wrapper

Wrap any coding session to automatically record corrections and
retrieve learned patterns. Works as a pre/post hook for any workflow.

Usage:
    # Start a session (records start time, retrieves patterns)
    python3 wrapper.py start --context "Python web API"

    # Record a correction during the session
    python3 wrapper.py correct "used requests" "use httpx"

    # End session (shows what was learned)
    python3 wrapper.py end

    # Or use as a pre-commit hook
    python3 wrapper.py pre-commit "fixed type hints" "added Optional[] annotations"
"""
import argparse
import json
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import get_config
from storage import Storage
from pattern_engine import PatternEngine


_config = get_config()
SESSION_FILE = Path(_config["session_file"])


def get_engine() -> PatternEngine:
    storage = Storage(
        db_path=_config["db_path"],
        chroma_url=_config["chroma_url"],
        collection_name=_config["collection_name"],
    )
    return PatternEngine(storage)


def cmd_start(args):
    """Start a new session — retrieve relevant patterns."""
    engine = get_engine()

    # Save session state
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    session = {
        "context": args.context,
        "started_at": datetime.now(UTC).isoformat(),
        "corrections": 0,
    }
    SESSION_FILE.write_text(json.dumps(session))

    # Get relevant patterns
    patterns = engine.get_patterns_for_context(
        context=args.context,
        limit=args.limit,
        min_confidence=args.min_confidence,
    )

    if patterns:
        print(f"\n📝 Learned patterns for '{args.context}':")
        for i, r in enumerate(patterns, 1):
            p = r["pattern"]
            conf = p["confidence"]
            bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
            print(f"  [{bar}] {conf:.2f} | {p['action'][:60]}")
        print()
    else:
        print(f"\n📝 No learned patterns yet for '{args.context}'")
        print("   Corrections you make will be remembered for next time.\n")


def cmd_correct(args):
    """Record a correction during the session."""
    engine = get_engine()

    # Load session
    session = {}
    if SESSION_FILE.exists():
        session = json.loads(SESSION_FILE.read_text())

    result = engine.record_correction(
        original=args.original,
        corrected=args.corrected,
        context=session.get("context", ""),
        category=args.category or None,
    )

    session["corrections"] = session.get("corrections", 0) + 1
    SESSION_FILE.write_text(json.dumps(session))

    if result["is_new_pattern"]:
        print(f"  ✨ New pattern learned: {args.corrected[:50]}")
    else:
        print(f"  🔄 Pattern reinforced (confidence: {result['confidence']:.2f})")


def cmd_end(args):
    """End session — show what was learned."""
    engine = get_engine()

    session = {}
    if SESSION_FILE.exists():
        session = json.loads(SESSION_FILE.read_text())
        SESSION_FILE.unlink(missing_ok=True)

    corrections = session.get("corrections", 0)
    context = session.get("context", "unknown")

    print(f"\n📊 Session summary: '{context}'")
    print(f"   Corrections recorded: {corrections}")

    if corrections > 0:
        patterns = engine.get_patterns_for_context(context, limit=5)
        print(f"   Active patterns: {len(patterns)}")
        for r in patterns:
            p = r["pattern"]
            print(f"     [{p['confidence']:.2f}] {p['action'][:50]}")

    print()
    return session


def cmd_commit(args):
    """Record a correction as a pre-commit hook."""
    engine = get_engine()
    result = engine.record_correction(
        original=args.original,
        corrected=args.corrected,
        context="pre-commit",
        category=args.category or None,
    )
    if result["is_new_pattern"]:
        print(f"pattern-memory: new pattern recorded")
    else:
        print(f"pattern-memory: pattern reinforced ({result['confidence']:.2f})")


def main():
    parser = argparse.ArgumentParser(description="Pattern Memory Session Wrapper")
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Start session, retrieve patterns")
    p_start.add_argument("--context", required=True, help="Session context")
    p_start.add_argument("--limit", type=int, default=5)
    p_start.add_argument("--min-confidence", type=float, default=0.3)
    p_start.set_defaults(func=cmd_start)

    # correct
    p_correct = sub.add_parser("correct", help="Record a correction")
    p_correct.add_argument("original", help="What was wrong")
    p_correct.add_argument("corrected", help="What it should be")
    p_correct.add_argument("--category", help="Category hint")
    p_correct.set_defaults(func=cmd_correct)

    # end
    p_end = sub.add_parser("end", help="End session, show summary")
    p_end.set_defaults(func=cmd_end)

    # commit (alias for correct with auto-context)
    p_commit = sub.add_parser("commit", help="Pre-commit correction")
    p_commit.add_argument("original", help="What was wrong")
    p_commit.add_argument("corrected", help="What it should be")
    p_commit.add_argument("--category", help="Category hint")
    p_commit.set_defaults(func=cmd_commit)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
