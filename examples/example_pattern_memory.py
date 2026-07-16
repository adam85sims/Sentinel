#!/usr/bin/env python3
"""Example: Pattern memory for learning from corrections.

Demonstrates how to use pattern-memory's storage layer directly
(without the MCP server) to record and retrieve corrections.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pattern-memory"))

from storage import Storage
from models import Pattern, Correction


def main():
    # Initialize storage (uses config defaults, falls back to SQLite-only)
    storage = Storage()

    print("Pattern Memory Example")
    print("=" * 50)

    # Record corrections
    print("\n1. Recording corrections...")

    corrections = [
        Correction(
            id=f"corr-{i}",
            original_behavior=orig,
            corrected_behavior=fixed,
            context=ctx,
            category=cat,
        )
        for i, (orig, fixed, ctx, cat) in enumerate([
            (
                "Using capsys for log assertions",
                "Use caplog instead of capsys for log assertion tests",
                "capsys captures stdout, not logging output. Use caplog fixture to assert log messages.",
                "testing",
            ),
            (
                "Truthiness check on empty dicts",
                "Use 'is not None' for empty dict checks, not truthiness",
                "Empty dicts are falsy, so 'if claims and evidence:' fails when either is {}.",
                "python",
            ),
            (
                "Using \\s* in regex across lines",
                "Use [^\\S\\n] instead of \\s* when bridging across newlines",
                "\\s* matches newlines, which can cause regex to bridge across line boundaries unexpectedly.",
                "regex",
            ),
        ])
    ]

    for c in corrections:
        cid = storage.store_correction(c)
        print(f"   Stored: {c.corrected_behavior[:60]}... -> ID: {cid}")

    # Search for patterns (semantic search via ChromaDB, empty in SQLite-only)
    print("\n2. Searching for patterns...")

    queries = ["log assertions", "empty dict", "regex newline"]
    for query in queries:
        results = storage.search_patterns(query, limit=3)
        print(f"\n   Query: '{query}' -> {len(results)} result(s)")
        for r in results:
            p = r["pattern"]
            print(f"      [{p.get('category', '?')}] {p.get('trigger', '')[:70]}")

    if not any(storage.search_patterns(q) for q in queries):
        print("   (Semantic search requires ChromaDB — SQLite-only mode returns empty)")

    # List patterns
    print("\n3. Listing patterns by category:")
    categories = set()
    for c in corrections:
        categories.add(c.category)
    for cat in sorted(categories):
        patterns = storage.list_patterns(category=cat, limit=5)
        print(f"   {cat}: {len(patterns)} pattern(s)")

    # Get stats
    print("\n4. Storage statistics:")
    print(f"   Total patterns: {storage.count_patterns()}")
    print(f"   Total corrections: {storage.count_corrections()}")

    print("\nDone. In a real setup, the MCP server would expose these")
    print("as tools that your AI agent can call during sessions.")

    storage.close()


if __name__ == "__main__":
    main()