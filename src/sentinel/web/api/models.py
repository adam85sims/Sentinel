"""Model Endpoints API router.

Provides endpoints for listing, adding, deleting, and testing connection to model endpoints.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException

from sentinel.web.schemas.model import (
    ModelEndpointCreate,
    ModelEndpointListResponse,
    ModelEndpointResponse,
    ModelEndpointTestResponse,
)

router = APIRouter(prefix="/api/model-endpoints", tags=["model-endpoints"])

# Resolve project root for sentinel-web.yaml configuration storage
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_CONFIG_FILE = _PROJECT_ROOT / "sentinel-web.yaml"


def _load_endpoints() -> list[dict[str, Any]]:
    """Load model endpoints from sentinel-web.yaml."""
    if not _CONFIG_FILE.exists():
        return []
    try:
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data.get("endpoints", [])
    except Exception:
        return []


def _save_endpoints(endpoints: list[dict[str, Any]]) -> None:
    """Save model endpoints to sentinel-web.yaml."""
    try:
        data = {}
        if _CONFIG_FILE.exists():
            with open(_CONFIG_FILE, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        data["endpoints"] = endpoints
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
    except Exception:
        pass


@router.get("", response_model=ModelEndpointListResponse)
async def list_endpoints() -> ModelEndpointListResponse:
    """List all configured model endpoints."""
    items = _load_endpoints()
    endpoints = [ModelEndpointResponse(**item) for item in items]
    return ModelEndpointListResponse(endpoints=endpoints, total=len(endpoints))


@router.post("", response_model=ModelEndpointResponse, status_code=201)
async def add_endpoint(payload: ModelEndpointCreate) -> ModelEndpointResponse:
    """Add a new model endpoint."""
    endpoints = _load_endpoints()

    # Generate a unique slug ID if not already existing
    provider_slug = payload.provider.lower().replace("_", "-").replace(" ", "-")
    model_slug = payload.model.lower().replace("/", "-").replace("_", "-").replace(" ", "-")
    endpoint_id = f"{provider_slug}-{model_slug}"

    # Check for duplicate IDs, append uuid fragment if exists
    existing_ids = {ep.get("id") for ep in endpoints}
    if endpoint_id in existing_ids:
        endpoint_id = f"{endpoint_id}-{str(uuid.uuid4())[:8]}"

    new_endpoint = {
        "id": endpoint_id,
        "provider": payload.provider,
        "model": payload.model,
        "base_url": payload.base_url,
        "api_key_env": payload.api_key_env,
    }

    endpoints.append(new_endpoint)
    _save_endpoints(endpoints)

    return ModelEndpointResponse(**new_endpoint)


@router.delete("/{endpoint_id}", status_code=204)
async def delete_endpoint(endpoint_id: str) -> None:
    """Delete a model endpoint by ID."""
    endpoints = _load_endpoints()
    updated = [ep for ep in endpoints if ep.get("id") != endpoint_id]

    if len(updated) == len(endpoints):
        raise HTTPException(
            status_code=404,
            detail=f"Model endpoint with ID '{endpoint_id}' not found",
        )

    _save_endpoints(updated)


@router.post("/{endpoint_id}/test", response_model=ModelEndpointTestResponse)
async def test_endpoint(endpoint_id: str) -> ModelEndpointTestResponse:
    """Test connection to a model endpoint."""
    endpoints = _load_endpoints()
    endpoint = next((ep for ep in endpoints if ep.get("id") == endpoint_id), None)

    if not endpoint:
        raise HTTPException(
            status_code=404,
            detail=f"Model endpoint with ID '{endpoint_id}' not found",
        )

    provider = endpoint.get("provider", "")
    model = endpoint.get("model", "")
    base_url = endpoint.get("base_url")
    api_key_env = endpoint.get("api_key_env")

    # Resolve URL — ensure /v1 suffix for OpenAI-compatible providers
    url = base_url
    if not url:
        if provider == "openai":
            url = "https://api.openai.com/v1"
        elif provider == "anthropic":
            url = "https://api.anthropic.com/v1"
        elif provider in ("lm_studio", "openai_compatible"):
            url = "http://localhost:1234/v1"
        else:
            return ModelEndpointTestResponse(success=False, message=f"Unknown provider '{provider}'")
    else:
        # Strip trailing slash, then ensure /v1 for non-anthropic providers
        url = url.rstrip("/")
        if provider != "anthropic" and not url.endswith("/v1"):
            # Don't double-append if user already included /v1
            if not url.rstrip("/").endswith("/v1"):
                url = f"{url}/v1"

    # Resolve API Key
    api_key = ""
    if api_key_env:
        api_key = os.getenv(api_key_env, "")

    if not api_key:
        if provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
        elif provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY", "")

    # Local providers don't need real keys
    if not api_key and provider in ("lm_studio", "openai_compatible"):
        api_key = "lm-studio"

    headers = {}
    if provider == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    else:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if provider == "anthropic":
                payload = {
                    "model": model or "claude-3-5-sonnet-20241022",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                }
                resp = await client.post(f"{url}/messages", json=payload, headers=headers)
            else:
                # Try a tiny completions request
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                }
                resp = await client.post(f"{url}/chat/completions", json=payload, headers=headers)

                # Fallback check of /models if chat completion returned 404 or 400
                if resp.status_code in (400, 404):
                    models_resp = await client.get(f"{url}/models", headers=headers)
                    if models_resp.status_code == 200:
                        models_data = models_resp.json()
                        available_models = [m.get("id") for m in models_data.get("data", [])]
                        if model in available_models:
                            return ModelEndpointTestResponse(
                                success=True,
                                message=f"Connection successful. Model '{model}' is available."
                            )
                        else:
                            return ModelEndpointTestResponse(
                                success=True,
                                message=(
                                    f"Connection successful, but model '{model}' was not found "
                                    f"in available models: {available_models}"
                                )
                            )

            if 200 <= resp.status_code < 300:
                return ModelEndpointTestResponse(
                    success=True,
                    message=f"Connection successful. Model '{model}' responded."
                )
            else:
                return ModelEndpointTestResponse(
                    success=False,
                    message=f"Server responded with status {resp.status_code}: {resp.text}"
                )
        except httpx.RequestError as exc:
            return ModelEndpointTestResponse(
                success=False,
                message=f"HTTP request failed: {exc}"
            )
        except Exception as exc:
            return ModelEndpointTestResponse(
                success=False,
                message=f"Error: {exc}"
            )
