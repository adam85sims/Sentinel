"""Uvicorn entry point for the Sentinel WebUI server.

Provides a CLI entry point registered as ``sentinel-serve`` in
pyproject.toml.  Also callable as ``python -m sentinel.web.server``.

Usage:
    sentinel-serve                          # defaults: 127.0.0.1:8080
    sentinel-serve --port 3000              # custom port
    sentinel-serve --host 0.0.0.0 --port 80  # all interfaces
    sentinel-serve --reload                 # auto-reload on code changes
"""

from __future__ import annotations

import sys


def main() -> None:
    """CLI entry point — parses args and runs uvicorn.

    Uses argparse (stdlib) instead of click to keep the web extra
    dependency-light.  The sentinel CLI itself uses click, but the
    web server is a separate entry point.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="sentinel-serve",
        description="Sentinel WebUI — Agent Behavioral Testing Dashboard",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to listen on (default: 8080)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes (dev mode)",
    )
    parser.add_argument(
        "--scenario-dir",
        default="examples",
        help="Directory containing scenario YAML/JSON files (default: examples/)",
    )

    args = parser.parse_args()

    # Import uvicorn here to keep the module importable even if
    # uvicorn isn't installed (e.g. when running tests).
    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn is required to run the web server.\n"
            "Install it with: pip install 'sentinel[web]'",
            file=sys.stderr,
        )
        sys.exit(1)

    # Build the ASGI app — uvicorn needs the app object or an import path.
    # We use the factory directly for clarity.
    from sentinel.web.app import create_app

    app = create_app(scenario_dir=args.scenario_dir)

    print(
        f"Starting Sentinel WebUI on http://{args.host}:{args.port}\n"
        f"  API docs:  http://{args.host}:{args.port}/api/docs\n"
        f"  Scenarios: {args.scenario_dir}/"
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


# Allow running as a module: python -m sentinel.web.server
if __name__ == "__main__":
    main()
