from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import and_, exists, func, insert, or_, select, update
from sqlalchemy.engine import Connection

from intelligence.database import entities, importer_relationships, json_safe, normalize_name, slugify, source_records
from intelligence.entity_resolution import score_company_match
from intelligence.models import SourceRecord


def _raw_year(record: SourceRecord) -> int | None:
    raw = record.attributes.get("raw") if isinstance(record.attributes, dict) else None
    if not isinstance(raw, dict): return None
    for key,value in raw.items():
        compact="".join(ch.lower() for ch in str(key) if ch.isalnum())
        if compact in {"dateofincorporation","incorporationdate","registrationdate","dateincorporated"}:
            for token in str(value or "").replace("/","-").split("-"):
                if token.isdigit() and len(token)==4 and 1800<=int(token)<=2100: return int(token)
    return None


def _candidate_record(candidate: dict[str, Any]) -> SourceRecord:
    return SourceRecord(source="canonical_entity",source_record_id=str(candidate["id"]),name=str(candidate["canonical_name"]),entity_type=str(candidate.get("entity_type") or "company"),country=candidate.get("country"),region=candidate.get("region"),city=candidate.get("city"),postal_code=candidate.get("postal_code"),address=candidate.get("address"),website=candidate.get("website"))


def _find_entity(conn: Connection, record: SourceRecord) -> int | None:
    existing_source=conn.execute(select(source_records.c.entity_id).where(and_(source_records.c.source==record.source,source_records.c.source_record_id==record.source_record_id))).scalar_one_or_none()
    if existing_source is not None: return int(existing_source)
    corporation_number=record.attributes.get("corporation_number") if isinstance(record.attributes,dict) else None
    if corporation_number:
        entity_id=conn.execute(select(entities.c.id).where(entities.c.corporation_number==str(corporation_number))).scalar_one_or_none()
        if entity_id is not None: return int(entity_id)

    normalized=normalize_name(record.name)
    # Fast path remains deliberately narrow: retrieve exact normalized names in
    # the same country, then let the auditable matcher decide whether evidence
    # is sufficient. A single same-name candidate is no longer auto-merged.
    candidates=conn.execute(select(entities.c.id,entities.c.entity_type,entities.c.canonical_name,entities.c.country,entities.c.region,entities.c.city,entities.c.postal_code,entities.c.address,entities.c.website).where(and_(entities.c.name_normalized==normalized,entities.c.country==(record.country or "CA"))).limit(25)).mappings().all()
    if not candidates: return None
    scored=[]
    for candidate in candidates:
        result=score_company_match(record,_candidate_record(dict(candidate)))
        if result.is_likely_match: scored.append((result.score,int(candidate["id"])))
    if not scored: return None
    scored.sort(reverse=True)
    # Do not guess when two canonical entities have equally strong evidence.
    if len(scored)>1 and scored[0][0]-scored[1][0]<0.05: return None
    return scored[0][1]


def _unique_slug(conn: Connection, record: SourceRecord) -> str:
    suffix=str(record.attributes.get("corporation_number") or "") or None;base=slugify(record.name,suffix)
    if conn.execute(select(entities.c.id).where(entities.c.slug==base)).first() is None:return base
    for idx in range(2,1000):
        candidate=f"{base[:210]}-{idx}"
        if conn.execute(select(entities.c.id).where(entities.c.slug==candidate)).first() is None:return candidate
    raise RuntimeError(f"Could not allocate slug for {record.name}")


def upsert_source_record(conn: Connection, record: SourceRecord) -> tuple[int,bool]:
    entity_id=_find_entity(conn,record);created=entity_id is None;attrs=record.attributes if isinstance(record.attributes,dict) else {};is_importer=record.source=="canadian_importers"
    if created:
        corporation_number=attrs.get("corporation_number");corporate_status=attrs.get("status") if record.source=="corporations_canada" else None
        result=conn.execute(insert(entities).values(slug=_unique_slug(conn,record),entity_type=record.entity_type,canonical_name=record.name,name_normalized=normalize_name(record.name),country=record.country,region=record.region,city=record.city,postal_code=record.postal_code,address=record.address,website=record.website,corporation_number=str(corporation_number) if corporation_number else None,corporate_status=str(corporate_status) if corporate_status else None,incorporated_year=_raw_year(record),is_importer=is_importer,enrichment={}))
        entity_id=int(result.inserted_primary_key[0])
    else:
        values:dict[str,Any]={"updated_at":func.now()}
        if is_importer:values["is_importer"]=True
        if record.website:values["website"]=record.website
        if record.source=="corporations_canada":
            values.update(corporation_number=str(attrs.get("corporation_number") or "") or None,corporate_status=str(attrs.get("status") or "") or None);year=_raw_year(record)
            if year:values["incorporated_year"]=year
        for key in ("region","city","postal_code","address"):
            value=getattr(record,key)
            if value:values[key]=value
        conn.execute(update(entities).where(entities.c.id==entity_id).values(**values))
    source_exists=conn.execute(select(source_records.c.id).where(and_(source_records.c.source==record.source,source_records.c.source_record_id==record.source_record_id))).scalar_one_or_none()
    if source_exists is None:conn.execute(insert(source_records).values(entity_id=entity_id,source=record.source,source_record_id=record.source_record_id,source_url=record.source_url,attributes=json_safe(attrs),source_updated_at=record.source_updated_at))
    if is_importer:
        hs6=attrs.get("hs6");hs10=attrs.get("hs10");origin=attrs.get("origin_country");dataset=attrs.get("dataset");description=attrs.get("product_description")
        duplicate=conn.execute(select(importer_relationships.c.id).where(and_(importer_relationships.c.entity_id==entity_id,importer_relationships.c.hs6==hs6,importer_relationships.c.hs10==hs10,importer_relationships.c.origin_country==origin,importer_relationships.c.dataset==dataset)).limit(1)).scalar_one_or_none()
        if duplicate is None:conn.execute(insert(importer_relationships).values(entity_id=entity_id,activity_year=attrs.get("activity_year"),hs6=hs6,hs10=hs10,product_description=description,origin_country=origin,dataset=dataset))
        elif description:conn.execute(update(importer_relationships).where(importer_relationships.c.id==duplicate).values(product_description=description))
    return entity_id,created


# --- Search/read helpers below intentionally remain compact and query-driven. ---
def search_entities(conn: Connection, *, q:str|None=None,country:str|None=None,company_type:str|None=None,province:str|None=None,city:str|None=None,origin:str|None=None,hs:str|None=None,status:str|None=None,incorporated_from:int|None=None,incorporated_to:int|None=None,has_website:bool|None=None,sort:str="relevance",limit:int=50,offset:int=0)->list[dict[str,Any]]:
    stmt=select(entities);conditions=[]
    if q:
        term=f"%{q.casefold()}%";rel_text=exists(select(importer_relationships.c.id).where(and_(importer_relationships.c.entity_id==entities.c.id,func.lower(func.coalesce(importer_relationships.c.product_description," ")).like(term))));conditions.append(or_(func.lower(entities.c.canonical_name).like(term),rel_text))
    if country:
        normalized_country=country.strip().upper();aliases={"CANADA":"CA","CAN":"CA","USA":"US","UNITED STATES":"US","UNITED STATES OF AMERICA":"US"};conditions.append(func.upper(func.coalesce(entities.c.country,""))==aliases.get(normalized_country,normalized_country))
    if province:conditions.append(func.lower(entities.c.region)==province.casefold())
    if city:conditions.append(func.lower(func.coalesce(entities.c.city," ")).like(f"%{city.casefold()}%"))
    if company_type:
        if company_type.casefold()=="importer":conditions.append(entities.c.is_importer.is_(True))
        elif company_type.casefold()=="company":conditions.append(entities.c.entity_type=="company")
    if status:conditions.append(func.lower(entities.c.corporate_status)==status.casefold())
    if incorporated_from:conditions.append(entities.c.incorporated_year>=incorporated_from)
    if incorporated_to:conditions.append(entities.c.incorporated_year<=incorporated_to)
    if has_website is True:conditions.append(and_(entities.c.website.is_not(None),func.length(func.trim(entities.c.website))>0))
    elif has_website is False:conditions.append(or_(entities.c.website.is_(None),func.length(func.trim(func.coalesce(entities.c.website,"")))==0))
    if origin:conditions.append(exists(select(importer_relationships.c.id).where(and_(importer_relationships.c.entity_id==entities.c.id,func.lower(importer_relationships.c.origin_country).like(f"%{origin.casefold()}%")))))
    if hs:
        digits="".join(ch for ch in hs if ch.isdigit())
        if digits:conditions.append(exists(select(importer_relationships.c.id).where(and_(importer_relationships.c.entity_id==entities.c.id,or_(importer_relationships.c.hs6.like(f"{digits}%"),importer_relationships.c.hs10.like(f"{digits}%"))))))
    if conditions:stmt=stmt.where(and_(*conditions))
    if sort=="name_desc":stmt=stmt.order_by(entities.c.canonical_name.desc())
    elif sort=="newest":stmt=stmt.order_by(entities.c.incorporated_year.desc().nullslast(),entities.c.canonical_name.asc())
    else:stmt=stmt.order_by(entities.c.canonical_name.asc())
    rows=conn.execute(stmt.limit(limit).offset(offset)).mappings().all();return [dict(row) for row in rows]


def get_entity_by_slug(conn:Connection,slug:str)->dict[str,Any]|None:
    row=conn.execute(select(entities).where(entities.c.slug==slug)).mappings().first()
    if row is None:return None
    result=dict(row);result["name"]=result.get("canonical_name");result["province"]=result.get("region");result["enrichment"]=result.get("enrichment") if isinstance(result.get("enrichment"),dict) else {};return result


def get_entity_enrichment(conn:Connection,entity_id:int,key:str)->dict[str,Any]|None:
    value=conn.execute(select(entities.c.enrichment).where(entities.c.id==entity_id)).scalar_one_or_none()
    if not isinstance(value,dict):return None
    item=value.get(key);return item if isinstance(item,dict) else None


def set_entity_enrichment(conn:Connection,entity_id:int,key:str,payload:dict[str,Any])->None:
    current=conn.execute(select(entities.c.enrichment).where(entities.c.id==entity_id)).scalar_one_or_none();current=dict(current) if isinstance(current,dict) else {};current[key]=json_safe(payload);conn.execute(update(entities).where(entities.c.id==entity_id).values(enrichment=current,updated_at=func.now()));conn.commit()
