from __future__ import annotations

from intelligence.sources.base import SourceAdapter
from intelligence.sources.canada_corporations import CorporationsCanadaAdapter
from intelligence.sources.canada_importers import CanadianImportersAdapter


SOURCE_REGISTRY: dict[str, type[SourceAdapter]] = {
    CorporationsCanadaAdapter.key: CorporationsCanadaAdapter,
    CanadianImportersAdapter.key: CanadianImportersAdapter,
}


def get_source(key: str) -> SourceAdapter:
    try:
        adapter_cls = SOURCE_REGISTRY[key]
    except KeyError as exc:
        available = ", ".join(sorted(SOURCE_REGISTRY))
        raise KeyError(f"Unknown source '{key}'. Available: {available}") from exc
    return adapter_cls()


def list_sources() -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for key, adapter_cls in sorted(SOURCE_REGISTRY.items()):
        adapter = adapter_cls()
        rows.append(
            {
                "key": key,
                "name": adapter.display_name,
                "license": adapter.license_name,
                "attribution": adapter.attribution,
            }
        )
    return rows
