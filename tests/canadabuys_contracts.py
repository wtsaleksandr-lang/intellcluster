from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from intelligence.canadabuys_bulk import ingest_canadabuys_csv, read_canadabuys_csv
from intelligence.country_intelligence import profile_capabilities
from intelligence.database import connect, entities, source_records
from intelligence.models import SourceRecord
from intelligence.repository import get_entity_enrichment, upsert_source_record
from main_data import app

client = TestClient(app)

SOURCE = "canadabuys-contract-test"


def _seed_company() -> tuple[int, str]:
    record = SourceRecord(
        source=SOURCE,
        source_record_id="CA-CONTRACT-1",
        name="Canada Contract Signal Inc",
        entity_type="company",
        country="CA",
        region="ON",
        city="Toronto",
        postal_code="M5V 2T6",
        attributes={"dataset": SOURCE},
    )
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, record)
        slug = str(
            conn.execute(entities.select().where(entities.c.id == entity_id))
            .mappings()
            .one()["slug"]
        )
    return int(entity_id), slug


def _write_fixture(path: Path) -> None:
    fields = [
        "supplierLegalName-nomLegalFournisseur-eng",
        "contractNumber-numeroContrat",
        "referenceNumber-numeroReference",
        "title-titre-eng",
        "awardDescription-descriptionAttribution-eng",
        "contractAwardDate-dateAttributionContrat",
        "publicationDate-datePublication",
        "amendmentDate-dateModification",
        "contractStartDate-contratDateDebut",
        "contractEndDate-dateFinContrat",
        "contractAmount-montantContrat",
        "totalContractValue-valeurTotaleContrat",
        "contractCurrency-contratMonnaie",
        "contractingEntityName-nomEntitContractante-eng",
        "awardStatus-attributionStatut-eng",
        "instrumentType-typeInstrument-eng",
        "amendmentNumber-numeroModification",
        "amendmentType-typeModification-eng",
        "unspsc",
        "unspscDescription-eng",
        "noticeType-avisType-eng",
    ]
    rows = [
        {
            fields[0]: "Canada Contract Signal Inc",
            fields[1]: "CWTEST100",
            fields[2]: "CWTEST100",
            fields[3]: "Freight planning software",
            fields[4]: "Software for federal freight planning",
            fields[5]: "2025-01-15",
            fields[6]: "2025-01-16",
            fields[7]: "",
            fields[8]: "2025-02-01",
            fields[9]: "2027-01-31",
            fields[10]: "100000.00",
            fields[11]: "100000.00",
            fields[12]: "CAD",
            fields[13]: "Public Services and Procurement Canada",
            fields[14]: "Active",
            fields[15]: "Contract",
            fields[16]: "000",
            fields[17]: "Original",
            fields[18]: "*81112000",
            fields[19]: "Data services",
            fields[20]: "Request for Proposal",
        },
        {
            fields[0]: "Canada Contract Signal Inc",
            fields[1]: "CWTEST100",
            fields[2]: "CWTEST100",
            fields[3]: "Freight planning software",
            fields[4]: "Software for federal freight planning",
            fields[5]: "2025-01-15",
            fields[6]: "2026-03-02",
            fields[7]: "2026-03-01",
            fields[8]: "2025-02-01",
            fields[9]: "2027-12-31",
            fields[10]: "50000.00",
            fields[11]: "150000.00",
            fields[12]: "CAD",
            fields[13]: "Public Services and Procurement Canada",
            fields[14]: "Active",
            fields[15]: "Contract",
            fields[16]: "001",
            fields[17]: "Amendment",
            fields[18]: "*81112000",
            fields[19]: "Data services",
            fields[20]: "Request for Proposal",
        },
        {
            fields[0]: "Canada Contract Signal Inc",
            fields[1]: "CWTEST200",
            fields[2]: "CWTEST200",
            fields[3]: "Cargo analytics subscription",
            fields[4]: "Analytics subscription",
            fields[5]: "2026-05-10",
            fields[6]: "2026-05-11",
            fields[7]: "",
            fields[8]: "2026-05-10",
            fields[9]: "2027-05-09",
            fields[10]: "50000.00",
            fields[11]: "50000.00",
            fields[12]: "CAD",
            fields[13]: "Transport Canada",
            fields[14]: "Active",
            fields[15]: "Contract",
            fields[16]: "000",
            fields[17]: "Original",
            fields[18]: "*81112000\n*81112200",
            fields[19]: "Data and software services",
            fields[20]: "Directed Contract",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _cleanup(entity_id: int) -> None:
    with connect() as conn:
        conn.execute(source_records.delete().where(source_records.c.entity_id == entity_id))
        conn.execute(entities.delete().where(entities.c.id == entity_id))


def run() -> int:
    entity_id, slug = _seed_company()
    try:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "contractHistoryComplete-test.csv"
            _write_fixture(fixture)
            rows = read_canadabuys_csv(fixture)
            assert len(rows) == 3
            assert rows[0]["supplier_name"] == "Canada Contract Signal Inc"
            assert rows[1]["value"] == "150000.00"
            assert rows[1]["value_basis"] == "total_contract_value"

            dry = ingest_canadabuys_csv(fixture, dry_run=True)
            assert dry["entities_matched"] == 1
            assert dry["entities_updated"] == 0
            with connect() as conn:
                assert "canadabuys_contracts" not in get_entity_enrichment(conn, entity_id)

            stats = ingest_canadabuys_csv(fixture)
            assert stats == {
                "rows_read": 3,
                "suppliers_seen": 1,
                "entities_matched": 1,
                "entities_updated": 1,
                "ambiguous_or_unmatched": 0,
            }

        with connect() as conn:
            enrichment = get_entity_enrichment(conn, entity_id)
        contracts = enrichment["canadabuys_contracts"]
        assert contracts["network_calls"] is False
        assert contracts["contract_count"] == 2
        assert contracts["history_row_count"] == 3
        assert contracts["cad_value_shown"] == 200000.0
        assert contracts["contracts"][0]["contract_number"] == "CWTEST200"
        amended = next(row for row in contracts["contracts"] if row["contract_number"] == "CWTEST100")
        assert amended["value"] == "150000.00"
        assert amended["amendment_number"] == "001"

        capabilities = profile_capabilities(
            {"country": "CA", "enrichment": enrichment}, country="CA"
        )
        assert capabilities["sections"]["contracts"]["status"] == "cached"
        assert "CanadaBuys" in str(capabilities["sections"]["contracts"]["source"])

        export = client.get(f"/data/company/{slug}/canadabuys-contracts.csv")
        assert export.status_code == 200, export.text
        assert "CWTEST100" in export.text
        assert "CWTEST200" in export.text
        assert "Cargo analytics subscription" in export.text

        profile = client.get(f"/data/company/{slug}")
        assert profile.status_code == 200, profile.text
        assert "intellcluster-canadabuys-profile-ui" in profile.text
        assert "/canadabuys-contracts.csv" in profile.text

        print("CanadaBuys contract-history cache checks OK")
        return 0
    finally:
        _cleanup(entity_id)


if __name__ == "__main__":
    raise SystemExit(run())
