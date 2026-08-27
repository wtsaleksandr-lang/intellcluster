from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import and_, exists, func, insert, or_, select, update
from sqlalchemy.engine import Connection

from intelligence.database import (
    entities,
    importer_relationships,
    json_safe,
    normalize_name,
    slugify,
    source_records,
)
from intelligence.models import SourceRecord


def _raw_year(record: SourceRecord) -> int | None:
    raw = record.attributes.get("raw") if isinstance(record.attributes, dict) else None
    if not isinstance(raw, dict):
        return None
    for key, value in raw.items():
        compact = "".join(ch.lower() for ch in str(key) if ch.isalnum())
        if compact in {"dateofincorporation", "incorporationdate", "registrationdate", "dateincorporated"}:
            text = str(value or "")
            for token in text.replace("/", "-").split("-"):
                if token.isdigit() and len(token) == 4 and 1800 <= int(token) <= 2100:
                    return int(token)
    return None


def _find_entity(conn: Connection, record: SourceRecord) -> int | None:
    existing_source = conn.execute(
        select(source_records.c.entity_id).where(
            and_(source_records.c.source == record.source, source_records.c.source_record_id == record.source_record_id)
        )
    ).scalar_one_or_none()
    if existing_source is not None:
        return int(existing_source)

    corporation_number = record.attributes.get("corporation_number") if isinstance(record.attributes, dict) else None
    if corporation_number:
        entity_id = conn.execute(
            select(entities.c.id).where(entities.c.corporation_number == str(corporation_number))
        ).scalar_one_or_none()
        if entity_id is not None:
            return int(entity_id)

    normalized = normalize_name(record.name)
    candidates = conn.execute(
        select(entities.c.id, entities.c.region, entities.c.city, entities.c.postal_code)
        .where(and_(entities.c.name_normalized == normalized, entities.c.country == (record.country or "CA")))
        .limit(10)
    ).mappings().all()
    if not candidates:
        return None
    if len(candidates) == 1:
        return int(candidates[0]["id"])

    for candidate in candidates:
        city_ok = not record.city or not candidate["city"] or record.city.casefold() == candidate["city"].casefold()
        region_ok = not record.region or not candidate["region"] or record.region.casefold() == candidate["region"].casefold()
        postal_ok = (
            not record.postal_code
            or not candidate["postal_code"]
            or record.postal_code.replace(" ", "").casefold() == candidate["postal_code"].replace(" ", "").casefold()
        )
        if city_ok and region_ok and postal_ok:
            return int(candidate["id"])
    return None


def _unique_slug(conn: Connection, record: SourceRecord) -> str:
    suffix = str(record.attributes.get("corporation_number") or "") or None
    base = slugify(record.name, suffix)
    if conn.execute(select(entities.c.id).where(entities.c.slug == base)).first() is None:
        return base
    for idx in range(2, 1000):
        candidate = f"{base[:210]}-{idx}"
        if conn.execute(select(entities.c.id).where(entities.c.slug == candidate)).first() is None:
            return candidate
    raise RuntimeError(f"Could not allocate slug for {record.name}")


def upsert_source_record(conn: Connection, record: SourceRecord) -> tuple[int, bool]:
    entity_id = _find_entity(conn, record)
    created = entity_id is None
    attrs = record.attributes if isinstance(record.attributes, dict) else {}
    is_importer = record.source == "canadian_importers"

    if created:
        corporation_number = attrs.get("corporation_number")
        corporate_status = attrs.get("status") if record.source == "corporations_canada" else None
        result = conn.execute(
            insert(entities).values(
                slug=_unique_slug(conn, record),
                entity_type=record.entity_type,
                canonical_name=record.name,
                name_normalized=normalize_name(record.name),
                country=record.country,
                region=record.region,
                city=record.city,
                postal_code=record.postal_code,
                address=record.address,
                website=record.website,
                corporation_number=str(corporation_number) if corporation_number else None,
                corporate_status=str(corporate_status) if corporate_status else None,
                incorporated_year=_raw_year(record),
                is_importer=is_importer,
                enrichment={},
            )
        )
        entity_id = int(result.inserted_primary_key[0])
    else:
        values: dict[str, Any] = {"updated_at": func.now()}
        if is_importer:
            values["is_importer"] = True
        if record.website:
            values["website"] = record.website
        if record.source == "corporations_canada":
            values.update(
                corporation_number=str(attrs.get("corporation_number") or "") or None,
                corporate_status=str(attrs.get("status") or "") or None,
            )
            year = _raw_year(record)
            if year:
                values["incorporated_year"] = year
        for key in ("region", "city", "postal_code", "address"):
            value = getattr(record, key)
            if value:
                values[key] = value
        conn.execute(update(entities).where(entities.c.id == entity_id).values(**values))

    source_exists = conn.execute(
        select(source_records.c.id).where(
            and_(source_records.c.source == record.source, source_records.c.source_record_id == record.source_record_id)
        )
    ).scalar_one_or_none()
    if source_exists is None:
        conn.execute(
            insert(source_records).values(
                entity_id=entity_id,
                source=record.source,
                source_record_id=record.source_record_id,
                source_url=record.source_url,
                attributes=json_safe(attrs),
                source_updated_at=record.source_updated_at,
            )
        )

    if is_importer:
        hs6 = attrs.get("hs6")
        hs10 = attrs.get("hs10")
        origin = attrs.get("origin_country")
        dataset = attrs.get("dataset")
        description = attrs.get("product_description")
        duplicate = conn.execute(
            select(importer_relationships.c.id).where(
                and_(
                    importer_relationships.c.entity_id == entity_id,
                    importer_relationships.c.hs6 == hs6,
                    importer_relationships.c.hs10 == hs10,
                    importer_relationships.c.origin_country == origin,
                    importer_relationships.c.dataset == dataset,
                )
            ).limit(1)
        ).scalar_one_or_none()
        if duplicate is None:
            conn.execute(
                insert(importer_relationships).values(
                    entity_id=entity_id,
                    activity_year=attrs.get("activity_year"),
                    hs6=hs6,
                    hs10=hs10,
                    product_description=description,
                    origin_country=origin,
                    dataset=dataset,
                )
            )
        elif description:
            conn.execute(
                update(importer_relationships)
                .where(importer_relationships.c.id == duplicate)
                .values(product_description=description)
            )
    return entity_id, created


def search_entities(
    conn: Connection,
    *,
    q: str | None = None,
    company_type: str | None = None,
    province: str | None = None,
    origin: str | None = None,
    hs: str | None = None,
    status: str | None = None,
    sort: str = "relevance",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = select(entities)
    conditions = []
    if q:
        term = f"%{q.casefold()}%"
        rel_text = exists(
            select(importer_relationships.c.id).where(
                and_(
                    importer_relationships.c.entity_id == entities.c.id,
                    func.lower(func.coalesce(importer_relationships.c.product_description, "")).like(term),
                )
            )
        )
        conditions.append(or_(func.lower(entities.c.canonical_name).like(term), rel_text))
    if province:
        conditions.append(func.lower(entities.c.region) == province.casefold())
    if company_type:
        if company_type.casefold() == "importer":
            conditions.append(entities.c.is_importer.is_(True))
        elif company_type.casefold() == "company":
            conditions.append(entities.c.entity_type == "company")
    if status:
        conditions.append(func.lower(entities.c.corporate_status) == status.casefold())
    if origin:
        conditions.append(
            exists(
                select(importer_relationships.c.id).where(
                    and_(
                        importer_relationships.c.entity_id == entities.c.id,
                        func.lower(importer_relationships.c.origin_country).like(f"%{origin.casefold()}%"),
                    )
                )
            )
        )
    if hs:
        digits = "".join(ch for ch in hs if ch.isdigit())
        if digits:
            conditions.append(
                exists(
                    select(importer_relationships.c.id).where(
                        and_(
                            importer_relationships.c.entity_id == entities.c.id,
                            or_(
                                importer_relationships.c.hs6.like(f"{digits}%"),
                                importer_relationships.c.hs10.like(f"{digits}%"),
                            ),
                        )
                    )
                )
            )
    if conditions:
        stmt = stmt.where(and_(*conditions))
    if sort == "buyer_score":
        stmt = stmt.order_by(entities.c.buyer_score.desc().nullslast(), entities.c.canonical_name)
    elif sort == "name":
        stmt = stmt.order_by(entities.c.canonical_name)
    else:
        stmt = stmt.order_by(entities.c.is_importer.desc(), entities.c.canonical_name)
    rows = conn.execute(stmt.limit(limit).offset(offset)).mappings().all()
    return [_decorate_company(conn, dict(row)) for row in rows]


def get_entity_by_slug(conn: Connection, slug: str) -> dict[str, Any] | None:
    row = conn.execute(select(entities).where(entities.c.slug == slug)).mappings().first()
    return _decorate_company(conn, dict(row), full=True) if row else None


def _percentage_rows(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    total = sum(counter.values()) or 1
    return [
        {"label": label, "count": count, "percent": round(count * 100 / total, 1)}
        for label, count in counter.most_common(limit)
    ]


def _decorate_company(conn: Connection, company: dict[str, Any], full: bool = False) -> dict[str, Any]:
    entity_id = company["id"]
    relationships = conn.execute(
        select(importer_relationships)
        .where(importer_relationships.c.entity_id == entity_id)
        .limit(1000 if full else 120)
    ).mappings().all()

    hs_codes = sorted({str(r["hs10"] or r["hs6"]) for r in relationships if r["hs10"] or r["hs6"]})
    origins = sorted({str(r["origin_country"]) for r in relationships if r["origin_country"]})
    products = sorted({str(r["product_description"]) for r in relationships if r["product_description"]})

    hs_counter: Counter[str] = Counter()
    origin_counter: Counter[str] = Counter()
    dataset_counter: Counter[str] = Counter()
    description_by_hs: dict[str, str] = {}
    for row in relationships:
        code = str(row["hs10"] or row["hs6"] or "").strip()
        if code:
            hs_counter[code] += 1
            if row["product_description"]:
                description_by_hs.setdefault(code, str(row["product_description"]))
        if row["origin_country"]:
            origin_counter[str(row["origin_country"])] += 1
        if row["dataset"]:
            dataset_counter[str(row["dataset"])] += 1

    hs_breakdown = []
    for item in _percentage_rows(hs_counter, 12):
        item["description"] = description_by_hs.get(item["label"], "")
        hs_breakdown.append(item)

    source_count = conn.execute(
        select(func.count(func.distinct(source_records.c.source))).where(source_records.c.entity_id == entity_id)
    ).scalar_one()
    source_records_count = conn.execute(
        select(func.count(source_records.c.id)).where(source_records.c.entity_id == entity_id)
    ).scalar_one()

    company.update(
        name=company.pop("canonical_name"),
        kind="Importer" if company.get("is_importer") else "Company",
        province=company.get("region") or "",
        status=(company.get("corporate_status") or "Unknown").title(),
        incorporated=str(company.get("incorporated_year") or ""),
        hs_codes=hs_codes,
        origins=origins,
        products=products,
        source_count=int(source_count or 0),
        source_records_count=int(source_records_count or 0),
        relationship_count=len(relationships),
        buyer_score=int(company.get("buyer_score") or 0),
        hs_breakdown=hs_breakdown,
        origin_breakdown=_percentage_rows(origin_counter, 12),
        dataset_breakdown=_percentage_rows(dataset_counter, 10),
    )
    return company
