from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from intelligence.database import connect, sync_checkpoints, sync_runs
from intelligence.sync_observability import sync_status_snapshot
from main_data import app
from shared.admin import ADMIN_COOKIE, create_admin_token

SOURCE = "sync-observability-test"


def _cleanup() -> None:
    with connect() as conn:
        conn.execute(sync_checkpoints.delete().where(sync_checkpoints.c.source == SOURCE))
        conn.execute(sync_runs.delete().where(sync_runs.c.source == SOURCE))


def run() -> int:
    _cleanup()
    now = datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc)
    try:
        with connect() as conn:
            conn.execute(
                sync_runs.insert().values(
                    source=SOURCE,
                    status="running",
                    records_seen=200,
                    records_written=0,
                    message="Resume from 200 via checkpoint",
                    started_at=now - timedelta(minutes=10),
                )
            )
            conn.execute(
                sync_checkpoints.insert().values(
                    source=SOURCE,
                    position=500,
                    status="running",
                    message="Committed through source position 500",
                    updated_at=now,
                )
            )

        snapshot = sync_status_snapshot(expected_totals={SOURCE: 1000}, now=now)
        row = next(item for item in snapshot["sources"] if item["source"] == SOURCE)
        assert row["checkpoint_position"] == 500
        assert row["expected_total_hint"] == 1000
        assert row["progress_percent"] == 50.0
        assert row["remaining_records_estimate"] == 500
        assert row["current_run_written_estimate"] == 300
        assert row["writes_per_second_estimate"] == 0.5
        assert row["writes_per_hour_estimate"] == 1800
        assert row["eta_seconds_estimate"] == 1000
        assert row["eta_label"] == "16m 40s"
        assert snapshot["supplier_index"]["backfill_network_calls"] is False
        assert "cached ImportYeti" in snapshot["supplier_index"]["population_rule"]

        anonymous = TestClient(app).get("/api/intelligence/admin/sync-status")
        assert anonymous.status_code == 401

        admin = TestClient(app)
        admin.cookies.set(
            ADMIN_COOKIE,
            create_admin_token(os.environ["ADMIN_USERNAME"]),
        )
        response = admin.get("/api/intelligence/admin/sync-status")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "sources" in payload
        assert payload["supplier_index"]["backfill_network_calls"] is False

        print("Sync observability checks OK")
        return 0
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(run())
