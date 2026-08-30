from __future__ import annotations

from intelligence.search_indexing import SEARCH_INDEXES, apply_search_indexes, search_index_status


def run() -> int:
    status = search_index_status()
    assert status["network_calls"] == 0
    assert status["paid_sources_called"] is False
    assert len(status["indexes"]) == 3
    assert {row["name"] for row in status["indexes"]} == {
        "ix_intel_entities_canonical_name_trgm",
        "ix_intel_importer_product_trgm",
        "ix_intel_importer_origin_trgm",
    }
    assert all("CONCURRENTLY" in str(row["sql"]) for row in SEARCH_INDEXES)

    try:
        apply_search_indexes(confirm=False)
    except RuntimeError as exc:
        assert "explicit confirmation" in str(exc)
    else:
        raise AssertionError("Search-index apply must require explicit confirmation")

    # CI/local preview uses SQLite: the maintenance command must be a no-op even
    # with confirmation rather than trying to execute PostgreSQL extension SQL.
    if status["dialect"] != "postgresql":
        assert status["supported"] is False
        result = apply_search_indexes(confirm=True)
        assert result["applied"] is False
        assert result["network_calls"] == 0

    print("Search indexing checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
