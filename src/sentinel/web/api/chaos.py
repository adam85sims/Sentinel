"""Chaos Configuration Builder API.

Provides endpoints for listing chaos presets, injector metadata, and
previewing/validating chaos configurations as YAML.
"""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter

from pydantic import BaseModel

router = APIRouter(prefix="/api/chaos", tags=["chaos"])


# ── Injector metadata ──
# Each injector type with its configurable parameters.
# This is the source of truth for the chaos builder UI.

INJECTORS: list[dict[str, Any]] = [
    {
        "type": "tool_failure",
        "name": "Tool Failure Injector",
        "description": "Fail tool calls with configurable type and probability",
        "params": [
            {"name": "tool_name", "type": "string", "default": "", "description": "Target tool (empty = all tools)"},
            {"name": "failure_type", "type": "select", "options": ["timeout", "error", "rate_limit", "malformed", "partial"], "default": "timeout"},
            {"name": "probability", "type": "range", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.3},
            {"name": "seed", "type": "number", "default": 42, "description": "Deterministic seed"},
        ],
    },
    {
        "type": "context_degradation",
        "name": "Context Degradation",
        "description": "Degrade context window with truncation, noise, or drift",
        "params": [
            {"name": "strategy", "type": "select", "options": ["TRUNCATION", "NOISE", "DRIFT"], "default": "TRUNCATION"},
            {"name": "max_context_tokens", "type": "number", "default": 4096, "min": 256, "max": 128000},
            {"name": "degradation_rate", "type": "range", "min": 0.01, "max": 1.0, "step": 0.01, "default": 0.1},
        ],
    },
    {
        "type": "cascading_failures",
        "name": "Cascading Failures",
        "description": "Multi-service error propagation via dependency graph",
        "params": [
            {"name": "cascade_probability", "type": "range", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.7},
            {"name": "max_cascade_depth", "type": "number", "default": 3, "min": 1, "max": 10},
            {"name": "initial_failure", "type": "string", "default": "database", "description": "Starting service"},
        ],
    },
    {
        "type": "spec_drift",
        "name": "Spec Drift",
        "description": "Agent improvisation under pressure",
        "params": [
            {"name": "intensity", "type": "select", "options": ["subtle", "moderate", "aggressive"], "default": "moderate"},
            {"name": "drift_probability", "type": "range", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.3},
        ],
    },
    {
        "type": "network_partition",
        "name": "Network Partition",
        "description": "Simulate network connectivity issues between services",
        "params": [
            {"name": "partition_probability", "type": "range", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.5},
            {"name": "affected_services", "type": "string", "default": "database,api_server", "description": "Comma-separated services"},
        ],
    },
    {
        "type": "memory_pressure",
        "name": "Memory Pressure",
        "description": "Force context eviction under memory constraints",
        "params": [
            {"name": "max_memory_tokens", "type": "number", "default": 8192, "min": 512, "max": 128000},
            {"name": "eviction_strategy", "type": "select", "options": ["lru", "priority", "random"], "default": "lru"},
        ],
    },
]

# ── Presets ──
# Each preset maps to a combination of injectors.

PRESETS: list[dict[str, Any]] = [
    {
        "id": "production-incident",
        "name": "Production Incident",
        "description": "Simulates a real production outage — database down, cascading failures, rate limits",
        "injectors": {
            "tool_failure": {"failure_type": "timeout", "probability": 0.4},
            "cascading_failures": {"cascade_probability": 0.8, "max_cascade_depth": 3, "initial_failure": "database"},
        },
    },
    {
        "id": "deploy-friday",
        "name": "Deploy Friday",
        "description": "Everything that can go wrong on a Friday deploy — mixed failures, context drift",
        "injectors": {
            "tool_failure": {"failure_type": "error", "probability": 0.2},
            "context_degradation": {"strategy": "DRIFT", "degradation_rate": 0.15},
            "spec_drift": {"intensity": "subtle", "drift_probability": 0.2},
        },
    },
    {
        "id": "traffic-spike",
        "name": "Traffic Spike",
        "description": "Rate limiting and timeouts under high load",
        "injectors": {
            "tool_failure": {"failure_type": "rate_limit", "probability": 0.5},
            "memory_pressure": {"max_memory_tokens": 4096, "eviction_strategy": "lru"},
        },
    },
    {
        "id": "network-issues",
        "name": "Network Instability",
        "description": "Partial network connectivity and partitions",
        "injectors": {
            "network_partition": {"partition_probability": 0.6, "affected_services": "database,api_server"},
            "tool_failure": {"failure_type": "timeout", "probability": 0.3},
        },
    },
    {
        "id": "full-chaos",
        "name": "Full Chaos",
        "description": "Maximum chaos — all injectors active at moderate levels",
        "injectors": {
            "tool_failure": {"failure_type": "timeout", "probability": 0.3},
            "context_degradation": {"strategy": "TRUNCATION", "degradation_rate": 0.1},
            "cascading_failures": {"cascade_probability": 0.5, "max_cascade_depth": 2},
            "spec_drift": {"intensity": "moderate", "drift_probability": 0.25},
        },
    },
]


class ChaosPreviewRequest(BaseModel):
    """Request body for chaos config preview."""
    injectors: dict[str, dict[str, Any]] = {}
    budget_max_failures: int = 10


@router.get("/injectors")
async def list_injectors() -> dict[str, Any]:
    """List all available chaos injectors with their parameter schemas."""
    return {"injectors": INJECTORS, "total": len(INJECTORS)}


@router.get("/presets")
async def list_presets() -> dict[str, Any]:
    """List all chaos presets."""
    return {"presets": PRESETS, "total": len(PRESETS)}


@router.post("/preview")
async def preview_chaos_config(request: ChaosPreviewRequest) -> dict[str, Any]:
    """Preview a chaos configuration as YAML.

    Accepts the chaos builder form data and returns the equivalent
    YAML that would be inserted into a scenario file.
    """
    chaos_config: dict[str, Any] = {}

    for injector_type, params in request.injectors.items():
        if not params:
            continue
        chaos_config[injector_type] = params

    # Add budget if specified
    if request.budget_max_failures and request.budget_max_failures != 10:
        chaos_config["budget"] = {"max_failures": request.budget_max_failures}

    # Convert to YAML
    yaml_content = yaml.dump(
        {"chaos": chaos_config},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    return {
        "yaml": yaml_content,
        "config": chaos_config,
        "injector_count": len(chaos_config),
    }


@router.post("/validate")
async def validate_chaos_config(request: ChaosPreviewRequest) -> dict[str, Any]:
    """Validate a chaos configuration.

    Checks that all injector types are valid and parameters are within bounds.
    """
    errors: list[str] = []

    valid_types = {injector["type"] for injector in INJECTORS}
    for injector_type in request.injectors:
        if injector_type not in valid_types:
            errors.append(f"Unknown injector type: '{injector_type}'")

    if request.budget_max_failures < 1:
        errors.append("budget_max_failures must be at least 1")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }
