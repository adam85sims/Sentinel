"""Pydantic models for the Scenario API.

Covers creation, listing, and detail views of test scenarios
loaded from YAML/JSON files on disk.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScenarioCreate(BaseModel):
    """Request body for creating a new scenario via the API.

    Mirrors the fields found in a SentinelScenario YAML file so
    the frontend can POST new scenarios directly.
    """

    name: str
    description: str = ""
    task: str = ""
    env_config: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    timeout_seconds: int = 30
    chaos_config: dict = Field(default_factory=dict)


class ScenarioResponse(BaseModel):
    """A single scenario returned by the API.

    ``id`` is derived from the scenario's ``id`` field in YAML,
    falling back to the filename stem when absent.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    task: str = ""
    env_config: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    timeout_seconds: int = 30
    chaos_config: dict = Field(default_factory=dict)
    file_path: str = ""
    raw_yaml: str | None = None



class ScenarioListResponse(BaseModel):
    """Paginated list of scenarios."""

    scenarios: list[ScenarioResponse] = Field(default_factory=list)
    total: int = 0
