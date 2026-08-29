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
        headers = {
            "User-Agent": "Mozilla/5.0 IntellCluster/1.0",
            "Accept": "text/csv,text/plain,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=180, follow_redirects=True, headers=headers) as client:
            for name, url in self.DATASETS.items():
                path = target_dir / f"{name}.csv"
                response = await client.get(url)
                response.raise_for_status()
                if not response.content:
                    raise RuntimeError(f"Corporations Canada returned an empty CSV for {name}")
                path.write_bytes(response.content)
                paths.append(path)
        return paths

    async def iter_records(self, paths: list[Path]) -> AsyncIterator[SourceRecord]:
        """Parse the April-2026 four-file federal corporations schema.

        Current CSV columns include Corporate name - form 1/form 2, City/town,
        Province/territory, Street, Business number (BN), and director ranges.
        """
        for path in paths:
            file_status = "active" if path.name.startswith("active") else "inactive"
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                sample = handle.read(8192)
                handle.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(handle, dialect=dialect)
                for row in reader:
                    normalized = {self._norm(k): (v or "").strip() for k, v in row.items() if k is not None}
                    name = self._pick(
                        normalized,
                        "corporatenameform1",
                        "corporatenameform2",
                        "corporationname",
                        "corporatename",
                        "name",
                    )
                    number = self._pick(normalized, "corporationnumber", "number")
                    business_number = self._pick(normalized, "businessnumberbn", "businessnumber")
                    if not name:
                        continue

                    street = self._pick(normalized, "street")
                    street2 = self._pick(normalized, "street2")
                    address = ", ".join(part for part in [street, street2] if part) or None
                    status = self._pick(normalized, "status") or file_status
                    record_id = number or business_number or f"{path.stem}:{name}"

                    yield SourceRecord(
                        source=self.key,
                        source_record_id=record_id,
                        entity_type="company",
                        name=name,
                        country=self._pick(normalized, "country") or "CA",
                        region=self._pick(normalized, "provinceterritory", "province"),
                        city=self._pick(normalized, "citytown", "city", "municipality"),
                        postal_code=self._pick(normalized, "postalcode"),
                        address=address,
                        source_url="https://open.canada.ca/data/en/dataset/0032ce54-c5dd-4b66-99a0-320a7b5e99f2",
                        attributes={
                            "status": status,
                            "corporation_number": number,
                            "business_number": business_number,
                            "governing_legislation": self._pick(normalized, "governinglegislation"),
                            "anniversary_date": self._pick(normalized, "anniversarydate"),
                            "year_last_annual_filing": self._pick(normalized, "yearoflastannualfiling"),
                            "date_last_annual_meeting": self._pick(normalized, "dateoflastannualmeeting"),
                            "minimum_directors": self._pick(normalized, "minimumnumberofdirectors"),
                            "maximum_directors": self._pick(normalized, "maximumnumberofdirectors"),
                            "alternate_corporate_name": self._pick(normalized, "corporatenameform2"),
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
