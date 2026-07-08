#!/usr/bin/env python3
"""Pattern Memory — Demo: Realistic Coding Session

Simulates a developer using Pattern Memory across multiple coding sessions.
Shows how corrections are learned and applied over time.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from storage import Storage
from pattern_engine import PatternEngine


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_patterns(patterns, label="Learned patterns"):
    if not patterns:
        print(f"  (none)")
        return
    print(f"  {label}:")
    for r in patterns:
        p = r["pattern"]
        conf = p["confidence"]
        bar = "█" * int(conf * 20) + "░" * (20 - int(conf * 20))
        print(f"  [{bar}] {conf:.2f} | {p['action'][:50]}")


def main():
    # Fresh storage
    db_path = str(Path.home() / ".pattern-memory" / "demo.db")
    store = Storage(db_path=db_path, chroma_url="http://127.0.0.1:8000")
    try:
        store.chroma.delete_collection("pattern_memory")
    except Exception:
        pass
    store.collection = store.chroma.get_or_create_collection(
        "pattern_memory", metadata={"hnsw:space": "cosine"}
    )
    engine = PatternEngine(store)

    # ── Session 1: First day with a new project ──────────────────────
    print_header("SESSION 1: First day on a Python web project")

    print("Agent writes: import requests; r = requests.get(url)")
    print("Developer: 'Use httpx instead, it supports async'\n")
    engine.record_correction(
        original="used requests library",
        corrected="use httpx library (supports async)",
        context="Python web API client",
        category="tool_choice",
    )

    print("Agent writes: data = json.loads(response.text)")
    print("Developer: 'Use response.json() method'\n")
    engine.record_correction(
        original="parsed JSON manually with json.loads",
        corrected="use response.json() method",
        context="Python HTTP response handling",
        category="code_style",
    )

    print("Agent writes: if len(items) > 0:")
    print("Developer: 'Use if items: Pythonic'\n")
    engine.record_correction(
        original="checked length with len() > 0",
        corrected="use truthiness check: if items:",
        context="Pythonic conditional",
        category="code_style",
    )

    print_patterns(engine.get_patterns_for_context("Python web project", limit=5))
    print(f"\n  Stats: {engine.get_stats()}")

    # ── Session 2: Next day, same project ────────────────────────────
    print_header("SESSION 2: Next day, continuing work")

    print("Agent starts new task. What does it know?")
    patterns = engine.get_patterns_for_context("Python web project", limit=5)
    print_patterns(patterns, "Patterns carried from Session 1")

    print("\nAgent writes: import requests")
    print("Developer: 'Remember, use httpx'\n")
    engine.record_correction(
        original="imported requests",
        corrected="import httpx",
        context="Python web project",
        category="tool_choice",
    )

    print("Agent writes: result = json.loads(resp.text)")
    print("Developer: 'resp.json() please'\n")
    engine.record_correction(
        original="json.loads(resp.text)",
        corrected="resp.json()",
        context="Python HTTP handling",
        category="code_style",
    )

    print_patterns(engine.get_patterns_for_context("Python web project", limit=5))
    print(f"\n  Stats: {engine.get_stats()}")

    # ── Session 3: Week later ────────────────────────────────────────
    print_header("SESSION 3: A week later, patterns are solid")

    patterns = engine.get_patterns_for_context("Python web project", limit=5)
    print_patterns(patterns, "Strong patterns after multiple corrections")

    # Confirm a pattern
    if patterns:
        pid = patterns[0]["pattern"]["id"]
        engine.confirm_pattern(pid)
        print(f"\n  User confirmed pattern {pid[:8]}...")

    print(f"\n  Final stats: {engine.get_stats()}")
    print()

    store.close()


if __name__ == "__main__":
    main()
