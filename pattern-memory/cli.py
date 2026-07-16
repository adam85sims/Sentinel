#!/usr/bin/env python3
"""Pattern Memory — CLI Interface

Use Pattern Memory from the command line. Records corrections and
retrieves patterns without needing a full MCP client.

Usage:
    python3 cli.py record "used var" "use const" --context "JS dev" --category code_style
    python3 cli.py get "JavaScript variable declarations"
    python3 cli.py search "code formatting"
    python3 cli.py list
    python3 cli.py confirm <pattern_id>
    python3 cli.py reject <pattern_id>
    python3 cli.py stats
"""
import argparse
import json
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from config import get_config
from storage import Storage
from pattern_engine import PatternEngine


def get_engine() -> PatternEngine:
    config = get_config()
    storage = Storage(
        db_path=config["db_path"],
        chroma_url=config["chroma_url"],
        collection_name=config["collection_name"],
    )
    return PatternEngine(storage)


def cmd_record(args):
    engine = get_engine()
    result = engine.record_correction(
        original=args.original,
        corrected=args.corrected,
        context=args.context or "",
        category=args.category or None,
    )
    print(json.dumps(result, indent=2))


def cmd_get(args):
    engine = get_engine()
    results = engine.get_patterns_for_context(
        context=args.context,
        limit=args.limit,
        min_confidence=args.min_confidence,
    )
    if not results:
        print("No patterns found for this context.")
        return
    for i, r in enumerate(results, 1):
        p = r["pattern"]
        print(f"\n  [{i}] confidence={p['confidence']:.2f} category={p['category']}")
        print(f"      trigger: {p['trigger'][:70]}")
        print(f"      action:  {p['action'][:70]}")
        print(f"      id: {p['id']}")


def cmd_search(args):
    engine = get_engine()
    results = engine.storage.search_patterns(args.query, limit=args.limit)
    if not results:
        print("No patterns found.")
        return
    for i, r in enumerate(results, 1):
        p = r["pattern"]
        dist = r.get("distance", "?")
        print(f"\n  [{i}] distance={dist} confidence={p['confidence']:.2f}")
        print(f"      {p['trigger'][:60]}")
        print(f"      -> {p['action'][:60]}")


def cmd_list(args):
    engine = get_engine()
    patterns = engine.storage.list_patterns(
        category=args.category or None,
        sort_by=args.sort,
        limit=args.limit,
    )
    if not patterns:
        print("No patterns stored.")
        return
    for p in patterns:
        print(f"  [{p.confidence:.2f}] [{p.category}] {p.action[:60]}")
        print(f"    id: {p.id} | uses: {p.use_count}")


def cmd_confirm(args):
    engine = get_engine()
    result = engine.confirm_pattern(args.pattern_id)
    print(json.dumps(result, indent=2))


def cmd_reject(args):
    engine = get_engine()
    result = engine.reject_pattern(args.pattern_id)
    print(json.dumps(result, indent=2))


def cmd_stats(args):
    engine = get_engine()
    stats = engine.get_stats()
    print(json.dumps(stats, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Pattern Memory CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # record
    p_record = sub.add_parser("record", help="Record a user correction")
    p_record.add_argument("original", help="What the agent did wrong")
    p_record.add_argument("corrected", help="What the user wanted instead")
    p_record.add_argument("--context", help="What was being worked on")
    p_record.add_argument("--category", help="Category hint")
    p_record.set_defaults(func=cmd_record)

    # get
    p_get = sub.add_parser("get", help="Get patterns for context")
    p_get.add_argument("context", help="Current task context")
    p_get.add_argument("--limit", type=int, default=5)
    p_get.add_argument("--min-confidence", type=float, default=0.3)
    p_get.set_defaults(func=cmd_get)

    # search
    p_search = sub.add_parser("search", help="Semantic search patterns")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    # list
    p_list = sub.add_parser("list", help="List all patterns")
    p_list.add_argument("--category", help="Filter by category")
    p_list.add_argument("--sort", default="confidence", choices=["confidence", "recent", "usage"])
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    # confirm
    p_confirm = sub.add_parser("confirm", help="Confirm a pattern")
    p_confirm.add_argument("pattern_id")
    p_confirm.set_defaults(func=cmd_confirm)

    # reject
    p_reject = sub.add_parser("reject", help="Reject a pattern")
    p_reject.add_argument("pattern_id")
    p_reject.set_defaults(func=cmd_reject)

    # stats
    p_stats = sub.add_parser("stats", help="Show statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
