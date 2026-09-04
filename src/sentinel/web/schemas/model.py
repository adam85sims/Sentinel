"""Pydantic models for the Model Endpoints API.

Covers creation, listing, detail, and testing of LLM provider endpoints.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelEndpointCreate(BaseModel):
    """Request body for creating/adding a new model endpoint."""

    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None


class ModelEndpointResponse(BaseModel):
    """Returned when exposing configured model endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None


class ModelEndpointListResponse(BaseModel):
    """List of all configured model endpoints."""

    endpoints: list[ModelEndpointResponse] = Field(default_factory=list)
    total: int = 0


class ModelEndpointTestResponse(BaseModel):
    """Outcome of testing connectivity to a model endpoint."""

    success: bool
    message: str
