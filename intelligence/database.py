from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
)
from sqlalchemy.engine import Connection, Engine

metadata = MetaData()

entities = Table(
    "intel_entities",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("slug", String(220), nullable=False, unique=True),
    Column("entity_type", String(40), nullable=False, default="company"),
    Column("canonical_name", String(500), nullable=False),
    Column("name_normalized", String(500), nullable=False),
    Column("country", String(8)),
    Column("region", String(100)),
    Column("city", String(180)),
    Column("postal_code", String(40)),
    Column("address", Text),
    Column("website", Text),
    Column("corporation_number", String(80)),
    Column("corporate_status", String(40)),
    Column("incorporated_year", Integer),
    Column("is_importer", Boolean, nullable=False, default=False),
    Column("summary", Text),
    Column("buyer_score", Float),
    Column("enrichment", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)
Index("ix_intel_entities_name", entities.c.name_normalized)
Index("ix_intel_entities_country_name", entities.c.country, entities.c.name_normalized)
Index("ix_intel_entities_region_city", entities.c.region, entities.c.city)
Index("ix_intel_entities_importer", entities.c.is_importer)
Index("ix_intel_entities_corporation_number", entities.c.corporation_number)
Index("ix_intel_entities_status_year", entities.c.corporate_status, entities.c.incorporated_year)
Index("ix_intel_entities_year", entities.c.incorporated_year)

source_records = Table(
    "intel_source_records",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("entity_id", Integer, ForeignKey("intel_entities.id", ondelete="CASCADE"), nullable=False),
    Column("source", String(80), nullable=False),
    Column("source_record_id", String(700), nullable=False),
    Column("source_url", Text),
    Column("attributes", JSON, nullable=False, default=dict),
    Column("source_updated_at", DateTime(timezone=True)),
    Column("ingested_at", DateTime(timezone=True), server_default=func.now()),
)
Index("ux_intel_source_record", source_records.c.source, source_records.c.source_record_id, unique=True)
Index("ix_intel_source_entity", source_records.c.entity_id)

importer_relationships = Table(
    "intel_importer_relationships",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("entity_id", Integer, ForeignKey("intel_entities.id", ondelete="CASCADE"), nullable=False),
    Column("activity_year", Integer),
    Column("hs6", String(6)),
    Column("hs10", String(10)),
    Column("product_description", Text),
    Column("origin_country", String(180)),
    Column("dataset", String(120)),
)
Index("ix_intel_importer_entity", importer_relationships.c.entity_id)
Index("ix_intel_importer_hs6", importer_relationships.c.hs6)
Index("ix_intel_importer_hs10", importer_relationships.c.hs10)
Index("ix_intel_importer_origin", importer_relationships.c.origin_country)
Index("ix_intel_importer_entity_hs", importer_relationships.c.entity_id, importer_relationships.c.hs6, importer_relationships.c.hs10)
Index("ix_intel_importer_entity_origin", importer_relationships.c.entity_id, importer_relationships.c.origin_country)

sync_runs = Table(
    "intel_sync_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", String(80), nullable=False),
    Column("status", String(30), nullable=False),
    Column("records_seen", Integer, nullable=False, default=0),
    Column("records_written", Integer, nullable=False, default=0),
    Column("message", Text),
    Column("started_at", DateTime(timezone=True), server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
)


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    if url:
        return url
    path = Path(os.environ.get("INTELLIGENCE_DB_PATH", "data/intelligence.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_database_url(), pool_pre_ping=True, future=True)
    return _engine


def init_database() -> None:
    metadata.create_all(get_engine())


@contextmanager
def connect() -> Iterator[Connection]:
    init_database()
    with get_engine().begin() as conn:
        yield conn


def normalize_name(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"\b(incorporated|inc|corporation|corp|limited|ltd|llc|company|co)\b", " ", value)
    return " ".join(re.findall(r"[a-z0-9]+", value))


def slugify(value: str, suffix: str | None = None) -> str:
    slug = "-".join(re.findall(r"[a-z0-9]+", value.casefold())).strip("-")[:180] or "company"
    if suffix:
        clean = "".join(ch.lower() for ch in suffix if ch.isalnum())[:24]
        if clean:
            slug = f"{slug}-{clean}"
    return slug[:220]


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
