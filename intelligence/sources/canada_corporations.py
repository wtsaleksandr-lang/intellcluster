from __future__ import annotations

import csv
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from intelligence.models import SourceRecord
from intelligence.sources.base import SourceAdapter


class CorporationsCanadaAdapter(SourceAdapter):
    key = "corporations_canada"
    display_name = "Corporations Canada"
    license_name = "Open Government Licence - Canada"
    attribution = "Innovation, Science and Economic Development Canada"

    DATASETS = {
        "active_business": "https://d4bf66bykfyaf.cloudfront.net/corporations-active-cbca-en.csv",
        "active_other": "https://d4bf66bykfyaf.cloudfront.net/corporations-active-non-cbca-en.csv",
        "inactive_business": "https://d4bf66bykfyaf.cloudfront.net/corporations-inactive-or-dissolved-cbca-en.csv",
        "inactive_other": "https://d4bf66bykfyaf.cloudfront.net/corporations-inactive-or-dissolved-non-cbca-en.csv",
    }

    async def fetch(self, cache_dir: Path) -> list[Path]:
        target_dir = cache_dir / self.key
        target_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            for name, url in self.DATASETS.items():
                path = target_dir / f"{name}.csv"
                response = await client.get(url)
                response.raise_for_status()
                path.write_bytes(response.content)
                paths.append(path)
        return paths

    async def iter_records(self, paths: list[Path]) -> AsyncIterator[SourceRecord]:
        for path in paths:
            status = "active" if path.name.startswith("active") else "inactive"
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    normalized = {self._norm(k): (v or "").strip() for k, v in row.items()}
                    name = self._pick(normalized, "corporationname", "name", "corporatename")
                    number = self._pick(normalized, "corporationnumber", "businessnumber", "number")
                    if not name:
                        continue
                    record_id = number or f"{path.stem}:{name}"
                    yield SourceRecord(
                        source=self.key,
                        source_record_id=record_id,
                        entity_type="company",
                        name=name,
                        country="CA",
                        region=self._pick(normalized, "province", "provinceterritory"),
                        city=self._pick(normalized, "city", "municipality"),
                        postal_code=self._pick(normalized, "postalcode"),
                        address=self._pick(normalized, "registeredofficeaddress", "address"),
                        source_url="https://open.canada.ca/data/en/dataset/0032ce54-c5dd-4b66-99a0-320a7b5e99f2",
                        attributes={
                            "status": status,
                            "corporation_number": number,
                            "dataset": path.stem,
                            "raw": normalized,
                        },
                    )

    @staticmethod
    def _norm(value: str | None) -> str:
        return "".join(ch.lower() for ch in (value or "") if ch.isalnum())

    @staticmethod
    def _pick(row: dict[str, str], *keys: str) -> str | None:
        for key in keys:
            value = row.get(key)
            if value:
                return value
        return None
