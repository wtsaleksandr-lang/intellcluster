from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

import httpx
from openpyxl import load_workbook

from intelligence.models import SourceRecord
from intelligence.sources.base import SourceAdapter

logger = logging.getLogger(__name__)


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

    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
        ),
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
        "Referer": "https://open.canada.ca/",
    }

    async def fetch(self, cache_dir: Path) -> list[Path]:
        target_dir = cache_dir / self.key
        target_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        failures: list[str] = []
        timeout = httpx.Timeout(180.0, connect=30.0)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=self.REQUEST_HEADERS,
        ) as client:
            for name, url in self.DATASETS.items():
                path = target_dir / f"{name}.xlsx"
                payload: bytes | None = None
                last_problem = "unknown response"

                # A previously cached valid workbook is better than failing the whole
                # source sync because one ISED endpoint temporarily returns zero bytes.
                if path.exists():
                    cached = path.read_bytes()
                    if self._is_valid_xlsx(cached):
                        paths.append(path)
                        continue

                for attempt in range(4):
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                    except httpx.HTTPError as exc:
                        last_problem = f"request error: {exc}"
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue

                    candidate = response.content
                    content_type = response.headers.get("content-type", "")
                    if self._is_valid_xlsx(candidate):
                        payload = candidate
                        break
                    snippet = candidate[:300].decode("utf-8", errors="replace").replace("\n", " ")
                    last_problem = (
                        f"HTTP {response.status_code}, content-type={content_type!r}, "
                        f"bytes={len(candidate)}, first bytes={snippet[:180]!r}"
                    )
                    await asyncio.sleep(1.5 * (attempt + 1))

                if payload is None:
                    failures.append(f"{name}: {last_problem}")
                    logger.warning("Skipping unavailable ISED workbook %s (%s)", name, last_problem)
                    continue

                path.write_bytes(payload)
                paths.append(path)

        if not paths:
            detail = "; ".join(failures) or "no workbook paths were produced"
            raise RuntimeError(f"No usable Canadian Importers workbooks could be downloaded. Details: {detail}")

        if failures:
            logger.warning(
                "Canadian Importers sync is continuing with %s usable workbook(s); %s workbook(s) were unavailable.",
                len(paths),
                len(failures),
            )
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
            if not self._is_valid_xlsx(path.read_bytes()):
                logger.warning("Skipping invalid cached importer workbook: %s", path)
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
    def _is_valid_xlsx(payload: bytes) -> bool:
        if len(payload) < 4 or not payload.startswith(b"PK"):
            return False
        try:
            from io import BytesIO

            with ZipFile(BytesIO(payload)) as archive:
                names = set(archive.namelist())
                return "[Content_Types].xml" in names and "xl/workbook.xml" in names
        except BadZipFile:
            return False

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
