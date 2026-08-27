from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from openpyxl import load_workbook

from intelligence.models import SourceRecord
from intelligence.sources.base import SourceAdapter


class CanadianImportersAdapter(SourceAdapter):
    key = "canadian_importers"
    display_name = "Canadian Importers Database"
    license_name = "Open Government Licence - Canada"
    attribution = "Innovation, Science and Economic Development Canada"

    # 2023 is the latest published importer activity dataset as of Aug 2026.
    DATASETS = {
        "major_importers_hs10": "https://ised-isde.canada.ca/site/ised/sites/default/files/documents/cid-bdic-majorimportersbyhs102023.xlsx",
        "major_importers_hs6": "https://ised-isde.canada.ca/site/ised/sites/default/files/documents/cid-bdic-majorimportersbyhs62023.xlsx",
        "major_importers_hs6_country": "https://ised-isde.canada.ca/site/ised/sites/default/files/documents/cid-bdic-majorimportersbyhs6bycountry2023.xlsx",
        "major_importers_city": "https://ised-isde.canada.ca/site/ised/sites/default/files/documents/cid-bdic-majorimportersbycity2023.xlsx",
        "major_importers_country": "https://ised-isde.canada.ca/site/ised/sites/default/files/documents/cid-bdic-majorimportersbycountry2023.xlsx",
        "hs10_descriptions": "https://ised-isde.canada.ca/site/ised/sites/default/files/documents/cid-bdic-hs10description2023.xlsx",
        "hs6_descriptions": "https://ised-isde.canada.ca/site/ised/sites/default/files/documents/cid-bdic-hs6description2023_0.xlsx",
    }

    async def fetch(self, cache_dir: Path) -> list[Path]:
        target_dir = cache_dir / self.key
        target_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            for name, url in self.DATASETS.items():
                path = target_dir / f"{name}.xlsx"
                response = await client.get(url)
                response.raise_for_status()
                path.write_bytes(response.content)
                paths.append(path)
        return paths

    async def iter_records(self, paths: list[Path]) -> AsyncIterator[SourceRecord]:
        """Yield importer/company records from the major-importer workbooks.

        The ISED workbooks have varied column labels across releases, so parsing
        uses normalized aliases and preserves the entire row in attributes.
        Description-only files are skipped here and will be used by a taxonomy
        loader later.
        """
        for path in paths:
            if "descriptions" in path.stem:
                continue
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                for sheet in workbook.worksheets:
                    rows = sheet.iter_rows(values_only=True)
                    try:
                        headers = next(rows)
                    except StopIteration:
                        continue
                    keys = [self._norm(v) for v in headers]
                    for values in rows:
                        row = {
                            keys[i]: self._string(values[i])
                            for i in range(min(len(keys), len(values)))
                            if keys[i]
                        }
                        name = self._pick(
                            row,
                            "companyname",
                            "importername",
                            "nameofimporter",
                            "company",
                            "importer",
                        )
                        if not name:
                            continue
                        hs10 = self._digits(self._pick(row, "hs10", "hscode10", "hs10code"), 10)
                        hs6 = self._digits(self._pick(row, "hs6", "hscode6", "hs6code"), 6)
                        city = self._pick(row, "city", "importercity")
                        province = self._pick(row, "province", "prov", "provincecode")
                        origin = self._pick(row, "country", "countryoforigin", "origincountry")
                        record_id = "|".join(
                            part for part in [path.stem, name, hs10 or hs6 or "", origin or "", city or ""] if part
                        )
                        yield SourceRecord(
                            source=self.key,
                            source_record_id=record_id,
                            entity_type="company",
                            name=name,
                            country="CA",
                            region=province,
                            city=city,
                            source_url="https://open.canada.ca/data/en/dataset/873cfcb0-1c9b-4a48-a366-076697069bb9",
                            attributes={
                                "activity_year": 2023,
                                "hs10": hs10,
                                "hs6": hs6,
                                "origin_country": origin,
                                "dataset": path.stem,
                                "raw": row,
                            },
                        )
            finally:
                workbook.close()

    @staticmethod
    def _norm(value: Any) -> str:
        return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())

    @staticmethod
    def _string(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    @staticmethod
    def _pick(row: dict[str, str], *keys: str) -> str | None:
        for key in keys:
            value = row.get(key)
            if value:
                return value
        return None

    @staticmethod
    def _digits(value: str | None, length: int) -> str | None:
        if not value:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        return digits.zfill(length)[:length] if digits else None
