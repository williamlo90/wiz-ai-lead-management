from datetime import datetime
from typing import Any, Literal

from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.normalization import (
    as_utc,
    clean_text,
    normalize_phone,
    normalize_status,
    optional_free_text,
    optional_text,
)


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeadBase(StrictSchema):
    name: str = Field(min_length=1, max_length=255)
    company: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=320)
    phone: str = Field(min_length=1, max_length=64)
    country: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=50)
    owner: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class LeadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(default=None, min_length=1, max_length=50)
    owner: str | None = Field(default=None, max_length=255)
    notes: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("status must be a non-null string")
        return normalize_status(value)

    @field_validator("owner", mode="before")
    @classmethod
    def normalize_owner(cls, value: object) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ValueError("owner must be a string or null")
        return optional_text(value)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: object) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ValueError("notes must be a string or null")
        return optional_free_text(value)

    @model_validator(mode="after")
    def require_update(self) -> "LeadUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


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

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def restore_utc(cls, value: datetime | None) -> datetime | None:
        return as_utc(value)

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_utc(self, value: datetime | None) -> str | None:
        utc_value = as_utc(value)
        return utc_value.isoformat().replace("+00:00", "Z") if utc_value else None


class LeadListResponse(StrictSchema):
    items: list[LeadRead]
    total: int
    limit: int
    offset: int


class WebsiteSubmission(StrictSchema):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=320)
    phone: str = Field(min_length=1, max_length=64)
    company: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=1, max_length=100)
    form_id: str = Field(min_length=1, max_length=255)
    form_name: str = Field(min_length=1, max_length=255)
    page_url: str = Field(min_length=1, max_length=2048)
    submitted_at: datetime
    message: str | None = None

    @field_validator(
        "name",
        "email",
        "phone",
        "company",
        "country",
        "form_id",
        "form_name",
        "page_url",
        mode="before",
    )
    @classmethod
    def normalize_required_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        cleaned = clean_text(value)
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("email must not contain whitespace")
        if value.count("@") != 1:
            raise ValueError("email must contain one @ separator")
        local, domain = value.split("@")
        domain_labels = domain.split(".")
        if not local or len(domain_labels) < 2 or any(not label for label in domain_labels):
            raise ValueError("email must have a valid address shape")
        return value

    @field_validator("phone")
    @classmethod
    def validate_phone_digits(cls, value: str) -> str:
        if not normalize_phone(value):
            raise ValueError("phone must contain at least one digit")
        return value

    @field_validator("page_url")
    @classmethod
    def validate_page_url(cls, value: str) -> str:
        if value.startswith("/") and not value.startswith("//"):
            return value
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
        raise ValueError("page_url must be relative or an absolute HTTP(S) URL")

    @field_validator("submitted_at")
    @classmethod
    def validate_submitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("submitted_at must include a timezone offset")
        return as_utc(value)  # type: ignore[return-value]

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: object) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ValueError("message must be a string or null")
        return optional_free_text(value)


class DedupeRequest(StrictSchema):
    min_score: float = Field(default=0.75, ge=0.75, le=1.0)
    limit: int = Field(default=100, ge=1, le=500)


class DedupeCandidate(StrictSchema):
    lead_ids: tuple[int, int]
    score: float
    confidence: Literal["clear", "likely"]
    reasons: list[str]


class DedupeResponse(StrictSchema):
    candidates: list[DedupeCandidate]
    candidate_pairs_evaluated: int
    total_matches: int


class IngestResponse(StrictSchema):
    action: Literal["created", "updated"]
    lead: LeadRead


SourceChannel = Literal[
    "Website",
    "Event",
    "LinkedIn",
    "Organic Search",
    "Referral",
    "Manual/Sales",
    "Other",
]


class SourceExtractionRequest(StrictSchema):
    text: str


class SourceExtractionResponse(StrictSchema):
    channel: SourceChannel
    detail: str = Field(max_length=500)


class DashboardResponse(StrictSchema):
    total: int
    by_status: dict[str, int]
    by_source_channel: dict[str, int]


class HealthResponse(BaseModel):
    status: str
    lead_count: int
