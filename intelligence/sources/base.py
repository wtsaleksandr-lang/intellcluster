from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path

from intelligence.models import SourceRecord


class SourceAdapter(ABC):
    """Contract for public/open dataset adapters.

    Adapters own downloading/parsing only. They should not perform paid
    enrichment or entity resolution. This keeps raw public provenance intact.
    """

    key: str
    display_name: str
    license_name: str | None = None
    attribution: str | None = None

    @abstractmethod
    async def fetch(self, cache_dir: Path) -> list[Path]:
        """Download/update source artifacts and return local paths."""

    @abstractmethod
    async def iter_records(self, paths: list[Path]) -> AsyncIterator[SourceRecord]:
        """Yield normalized records from downloaded artifacts."""
        if False:
            yield SourceRecord(source="", source_record_id="", name="")
