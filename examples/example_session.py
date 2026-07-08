#!/usr/bin/env python3
"""Example: Session state management for autonomous agent workflows.

Demonstrates how to use SessionState to track goals, decisions, and
project structure across agent sessions.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from automation import SessionState, WorkQueue


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else "."

    # ─── Session State ──────────────────────────────────────────

    session = SessionState(root=Path(project_root))
    session.start("Implement user authentication")

    print(f"Session started: {session.goal}")
    print(f"Status: {session.status}")

    # Simulate work
    session.add_next_step("Create user model")
    session.add_next_step("Write auth endpoints")
    session.add_next_step("Add JWT middleware")

    session.add_decision(
        "Used JWT over session cookies",
        "Stateless architecture, better for API-first design",
    )
    session.add_gotcha(
        "Token expiry not tested",
        "Add test case for refresh token flow",
    )

    # Update project map
    session.update_map(
        entry_points=["src/main.py", "src/app.py"],
        key_components={
            "auth": "src/auth/",
            "models": "src/models/",
            "middleware": "src/middleware/",
        },
        test_commands=["pytest tests/test_auth.py -v"],
    )

    session.save()
    print(f"\nSession saved to {project_root}/.brain/")
    print(f"  session.md, memory.md, map.json")

    # ─── Work Queue ─────────────────────────────────────────────

    print(f"\nLoading work queue from {project_root}/TODO.md")
    queue = WorkQueue(root=Path(project_root))
    queue.load()

    print(f"Pending: {queue.pending_count()}")
    print(f"Done: {queue.done_count()}")
    print(f"Blocked: {queue.blocked_count()}")

    # Process items
    print("\nProcessing queue:")
    while True:
        item = queue.next_item()
        if item is None:
            print("  Queue empty!")
            break

        print(f"  -> {item.description}")
        # In a real session, you'd do the work here, then:
        queue.complete(item.id)
        print(f"     Done!")

        # Check exit conditions
        reason = queue.should_exit()
        if reason:
            print(f"\n  Stopping: {reason}")
            break

    queue.save()
    print(f"\nQueue saved. Completed {queue.completed_this_session} items this session.")


if __name__ == "__main__":
    main()