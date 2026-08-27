from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


EntityType = Literal[
    "company",
    "facility",
    "aircraft",
    "government_supplier",
    "patent_assignee",
    "other",
]


class SourceRecord(BaseModel):
    """Raw-but-structured record emitted by one source adapter."""

    source: str
    source_record_id: str
    entity_type: EntityType = "company"
    name: str
    country: str | None = None
    region: str | None = None
    city: str | None = None
    postal_code: str | None = None
    address: str | None = None
    website: str | None = None
    source_url: str | None = None
    source_updated_at: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class EntityRecord(BaseModel):
    """Canonical entity assembled from one or more public source records."""

    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None
    region: str | None = None
    city: str | None = None
    postal_code: str | None = None
    address: str | None = None
    website: str | None = None
    industries: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    summary: str | None = None
    source_records: list[SourceRecord] = Field(default_factory=list)
    enrichment: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)
