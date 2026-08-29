from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from intelligence.database import connect, entities, source_records, supplier_relationships
from intelligence.enrichment.importyeti import ImportYetiClient
from intelligence.models import SourceRecord
from intelligence.repository import get_entity_by_slug, upsert_source_record
from main_data import app
from shared.admin import ADMIN_COOKIE, create_admin_token

client = TestClient(app)
SOURCE = "importyeti-cost-guard-test"


def _cleanup() -> None:
    with connect() as conn:
        entity_ids = conn.execute(
            select(source_records.c.entity_id).where(source_records.c.source == SOURCE)
        ).scalars().all()
        ids = {int(value) for value in entity_ids}
        for entity_id in ids:
            conn.execute(
                supplier_relationships.delete().where(
                    supplier_relationships.c.importer_entity_id == entity_id
                )
            )
        conn.execute(source_records.delete().where(source_records.c.source == SOURCE))
        for entity_id in ids:
            remaining = conn.execute(
                select(source_records.c.id)
                .where(source_records.c.entity_id == entity_id)
                .limit(1)
            ).scalar_one_or_none()
            if remaining is None:
                conn.execute(entities.delete().where(entities.c.id == entity_id))


def _seed(name: str, source_id: str) -> tuple[int, str]:
    record = SourceRecord(
        source=SOURCE,
        source_record_id=source_id,
        name=name,
        entity_type="company",
        country="US",
        region="CA",
        city="Long Beach",
        postal_code="90802",
        attributes={"dataset": SOURCE},
    )
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, record)
        slug = conn.execute(
            select(entities.c.slug).where(entities.c.id == entity_id)
        ).scalar_one()
    return int(entity_id), str(slug)


def run() -> int:
    _cleanup()
    keys = (
        "IMPORTYETI_ALLOW_LIVE",
        "IMPORTYETI_API_KEY",
        "IMPORTYETI_FIXTURE_PATH",
        "ADMIN_USERNAME",
        "ADMIN_SECRET_KEY",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in (
            "IMPORTYETI_ALLOW_LIVE",
            "IMPORTYETI_API_KEY",
            "IMPORTYETI_FIXTURE_PATH",
        ):
            os.environ.pop(key, None)
        os.environ["ADMIN_USERNAME"] = "cost-guard-admin"
        os.environ["ADMIN_SECRET_KEY"] = "c0stguard-2026-A7f9Q2m8L4p6X1z3"

        # A default client is always network-disabled, even when the environment
        # master switch and an API key exist. This protects incidental page views.
        default_client = ImportYetiClient()
        assert default_client.allow_live is False

        os.environ["IMPORTYETI_ALLOW_LIVE"] = "true"
        os.environ["IMPORTYETI_API_KEY"] = "test-key-never-sent"
        page_view_client = ImportYetiClient()
        assert page_view_client.allow_live is False
        try:
            asyncio.run(page_view_client.search_company("Must Not Reach Network LLC"))
        except RuntimeError as exc:
            assert "explicit ImportYetiClient(allow_live=True)" in str(exc)
        else:
            raise AssertionError(
                "Default ImportYeti client unexpectedly allowed network access"
            )

        explicit_client = ImportYetiClient(allow_live=True)
        assert explicit_client.allow_live is True

        os.environ["IMPORTYETI_ALLOW_LIVE"] = "false"
        master_blocked = ImportYetiClient(allow_live=True)
        assert master_blocked.allow_live is False

        fixture = Path(__file__).parent / "fixtures" / "importyeti_cached_company.json"
        os.environ["IMPORTYETI_FIXTURE_PATH"] = str(fixture)
        os.environ.pop("IMPORTYETI_API_KEY", None)
        fixture_client = ImportYetiClient()
        fixture_matches = asyncio.run(
            fixture_client.search_company("Cached ImportYeti Test Company")
        )
        assert len(fixture_matches) == 1
        assert fixture_matches[0].title == "Cached ImportYeti Test Company"

        _, fixture_slug = _seed(
            "Cached ImportYeti Test Company LLC",
            "IY-FIXTURE-1001",
        )
        acquired = client.post(
            f"/api/intelligence/company/{fixture_slug}/enrich/importyeti"
        )
        assert acquired.status_code == 200, acquired.text
        payload = acquired.json()
        assert payload.get("paid_sources_called") is False
        assert payload.get("lookup", {}).get("importyeti") == "matched"
        assert payload.get("acquisition", {}).get("mode") == "fixture"
        assert (
            payload.get("company", {}).get("importyeti", {}).get("total_shipments")
            == 248
        )

        # Cached intelligence remains reusable without admin authentication.
        cached = client.post(
            f"/api/intelligence/company/{fixture_slug}/enrich/importyeti"
        )
        assert cached.status_code == 200
        assert cached.json().get("lookup", {}).get("importyeti") == "cached"
        assert cached.json().get("paid_sources_called") is False

        os.environ.pop("IMPORTYETI_FIXTURE_PATH", None)
        os.environ["IMPORTYETI_ALLOW_LIVE"] = "false"
        os.environ["IMPORTYETI_API_KEY"] = "test-key-never-sent"
        _, guarded_slug = _seed(
            "Paid Network Guard Logistics LLC",
            "IY-GUARD-1002",
        )

        # A public caller cannot reach any network-capable paid path. The admin
        # session check happens before confirmation/master-switch/API-key checks.
        anonymous = client.post(
            f"/api/intelligence/company/{guarded_slug}/enrich/importyeti?confirm_paid=true"
        )
        assert anonymous.status_code == 401
        assert anonymous.json().get("detail") == "Admin access required"

        admin_client = TestClient(app)
        admin_client.cookies.set(
            ADMIN_COOKIE,
            create_admin_token(os.environ["ADMIN_USERNAME"]),
        )

        # Authorization alone is not enough: the caller must explicitly confirm
        # paid acquisition, and the server master switch must independently allow it.
        unconfirmed = admin_client.post(
            f"/api/intelligence/company/{guarded_slug}/enrich/importyeti"
        )
        assert unconfirmed.status_code == 409
        assert unconfirmed.json().get("paid_sources_called") is False

        master_disabled = admin_client.post(
            f"/api/intelligence/company/{guarded_slug}/enrich/importyeti?confirm_paid=true"
        )
        assert master_disabled.status_code == 409
        assert master_disabled.json().get("paid_sources_called") is False

        # Even if the master switch is enabled, legacy GET routes use the default
        # cached-only client and therefore cannot spend credits or fail on a BOL miss.
        os.environ["IMPORTYETI_ALLOW_LIVE"] = "true"
        profile = client.get(f"/data/company/{guarded_slug}")
        assert profile.status_code == 200
        bol = client.get(f"/data/company/{guarded_slug}/bol/TESTBOL999999")
        assert bol.status_code == 200
        assert "not cached" in bol.text.lower()
        with connect() as conn:
            guarded_company = get_entity_by_slug(conn, guarded_slug)
        assert guarded_company is not None
        assert not guarded_company.get("importyeti")

        print("ImportYeti cost-guard checks OK")
        return 0
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(run())
