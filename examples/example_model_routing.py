#!/usr/bin/env python3
"""Example: Model routing for autonomous agent sessions.

Demonstrates how to route different task types to the optimal model
based on the capability tiers defined in agent-frameworks.yaml.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from automation import ModelRouter


def main():
    router = ModelRouter(root=Path("."))

    # List all configured task types
    print("Configured Task Types:")
    print("=" * 50)
    for task, tier in sorted(router.list_tasks().items()):
        print(f"  {task:25s} -> {tier}")

    print()

    # Route specific tasks
    tasks_to_route = ["research", "scaffolding", "debugging", "writing"]

    print("Routing Results:")
    print("=" * 50)
    for task in tasks_to_route:
        model = router.route(task)
        info = router.describe(task)
        print(f"  {task:15s}  tier={info['tier']:10s}  -> {model['provider']}/{model['model']}")

    print()

    # Show fallback chains
    print("Fallback Chains:")
    print("=" * 50)
    for task in ["research", "scaffolding"]:
        models = router.route_all(task)
        print(f"  {task}:")
        for i, m in enumerate(models):
            label = "primary" if i == 0 else f"fallback {i}"
            print(f"    {label}: {m['provider']}/{m['model']}")


if __name__ == "__main__":
    main()