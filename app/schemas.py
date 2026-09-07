from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LeadBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    company: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=320)
    phone: str = Field(min_length=1, max_length=64)
    country: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=50)
    owner: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class LeadCreate(LeadBase):
    created_at: datetime
    updated_at: datetime | None = None
    original_source: str | None = Field(default=None, max_length=255)
    form_metadata: dict[str, Any] | None = None


class LeadUpdate(BaseModel):
    status: str | None = Field(default=None, min_length=1, max_length=50)
    owner: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class LeadRead(LeadBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime | None
    original_source: str | None
    source_channel: str | None
    source_detail: str | None
    form_metadata: dict[str, Any] | None = Field(
        validation_alias="form_data"
    )


class HealthResponse(BaseModel):
    status: str
    lead_count: int

