"""Sentinel WebUI — Browser-based dashboard for agent behavioral testing.

Provides a FastAPI-powered web interface for running scenarios, viewing
traces, managing baselines, and configuring chaos injection — all wrapping
the existing Sentinel core without modifying it.

Usage:
    sentinel-serve                        # Start on localhost:8080
    sentinel-serve --port 3000            # Custom port
    sentinel-serve --host 0.0.0.0         # All interfaces
    sentinel-serve --reload               # Auto-reload on code changes
"""
from __future__ import annotations

from sentinel.web.app import create_app

__all__: list[str] = ["create_app"]
