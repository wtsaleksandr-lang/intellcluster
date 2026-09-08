from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends

from intelligence.data_quality import data_quality_report
from intelligence.post_ingest_readiness import post_ingest_readiness
from shared.admin import require_admin

router = APIRouter(prefix="/api/intelligence/admin", tags=["intelligence-admin"])

_SECRET_MARKERS = (
    "change-me",
    "change-this",
    "default",
    "secret-key",
    "admin123",
    "password",
)
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _enabled(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().casefold()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def _unsafe_secret(value: str, *, minimum: int) -> bool:
    if len(value) < minimum:
        return True
    lowered = value.casefold()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def production_environment_report(*, production: bool = True) -> dict[str, Any]:
    """Validate launch-sensitive environment configuration without exposing secrets.

    No network or database calls are made here. Values that can spend money,
    weaken authentication, expose debug behavior, or route production to a local
    database are treated as blockers in production mode.
    """

    blockers: list[str] = []
    warnings: list[str] = []

    database_url = os.environ.get("DATABASE_URL", "").strip()
    public_base_url = (
        os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("SITE_URL")
        or ""
    ).strip().rstrip("/")
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    admin_secret = os.environ.get("ADMIN_SECRET_KEY", "")
    admin_username = os.environ.get("ADMIN_USERNAME", "admin").strip()
    importyeti_live = _enabled("IMPORTYETI_ALLOW_LIVE", default=False)
    rate_limit_enabled = _enabled("RATE_LIMIT_ENABLED", default=True)
    debug_enabled = _enabled("DEBUG", default=False)

    if production:
        if not database_url:
            blockers.append("DATABASE_URL is missing; production must use the persistent PostgreSQL database.")
        elif database_url.casefold().startswith("sqlite"):
            blockers.append("DATABASE_URL points to SQLite; production launch requires the persistent PostgreSQL database.")

        parsed = urlparse(public_base_url) if public_base_url else None
        if not public_base_url:
            blockers.append("PUBLIC_BASE_URL is missing.")
        elif parsed is None or parsed.scheme != "https" or not parsed.netloc:
            blockers.append("PUBLIC_BASE_URL must be an absolute HTTPS URL.")
        elif (parsed.hostname or "").casefold() in {"localhost", "127.0.0.1", "0.0.0.0"}:
            blockers.append("PUBLIC_BASE_URL points to a local host instead of the public site.")

        if _unsafe_secret(admin_secret, minimum=24):
            blockers.append("ADMIN_SECRET_KEY is missing, too short, or looks like a placeholder.")
        if _unsafe_secret(admin_password, minimum=12):
            blockers.append("ADMIN_PASSWORD is missing, too short, or looks like a placeholder.")
        if importyeti_live:
            blockers.append("IMPORTYETI_ALLOW_LIVE is enabled; launch with paid ImportYeti acquisition disabled by default.")
        if not rate_limit_enabled:
            blockers.append("RATE_LIMIT_ENABLED is disabled; public API cost/abuse protection must be enabled at launch.")
        if debug_enabled:
            blockers.append("DEBUG is enabled; disable debug mode for public launch.")
    else:
        if importyeti_live:
            warnings.append("IMPORTYETI_ALLOW_LIVE is enabled in this environment.")
        if not rate_limit_enabled:
            warnings.append("RATE_LIMIT_ENABLED is disabled in this environment.")
        if debug_enabled:
            warnings.append("DEBUG is enabled in this environment.")

    if admin_username.casefold() == "admin":
        warnings.append("ADMIN_USERNAME is the default 'admin'; a non-default username is preferable.")
    if not os.environ.get("SEC_EDGAR_USER_AGENT", "").strip():
        warnings.append("SEC_EDGAR_USER_AGENT is not set; configure a descriptive contact User-Agent before live SEC refreshes.")
    if not os.environ.get("PLAUSIBLE_DOMAIN", "").strip():
        warnings.append("PLAUSIBLE_DOMAIN is not set; launch analytics will be unavailable until configured.")

    return {
        "production_mode": production,
        "healthy": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "checks": {
            "database_url_configured": bool(database_url),
            "public_base_url": public_base_url or None,
            "admin_username_nondefault": admin_username.casefold() != "admin",
            "admin_password_configured": bool(admin_password),
            "admin_secret_configured": bool(admin_secret),
            "importyeti_live_enabled": importyeti_live,
            "rate_limit_enabled": rate_limit_enabled,
            "debug_enabled": debug_enabled,
            "sec_user_agent_configured": bool(os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()),
            "analytics_configured": bool(os.environ.get("PLAUSIBLE_DOMAIN", "").strip()),
        },
        "network_calls": 0,
        "paid_sources_called": False,
    }


def launch_gate_report(*, production: bool = False) -> dict[str, Any]:
    """Combine ingestion, integrity and environment checks into one launch verdict."""

    readiness = post_ingest_readiness()
    quality = data_quality_report()
    environment = production_environment_report(production=production)

    blockers = [f"ingestion: {item}" for item in readiness.get("blockers", [])]
    blockers.extend(f"data: {item}" for item in quality.get("blockers", []))
    blockers.extend(f"environment: {item}" for item in environment.get("blockers", []))

    warnings = [f"ingestion: {item}" for item in readiness.get("warnings", [])]
    warnings.extend(f"data: {item}" for item in quality.get("warnings", []))
    warnings.extend(f"environment: {item}" for item in environment.get("warnings", []))

    ready = (
        bool(readiness.get("deployment_safe"))
        and bool(quality.get("healthy"))
        and bool(environment.get("healthy"))
    )

    return {
        "ready_to_launch": ready,
        "production_mode": production,
        "blockers": blockers,
        "warnings": warnings,
        "ingestion": readiness,
        "data_quality": quality,
        "environment": environment,
        "next_action": (
            "Proceed with deployment smoke checks and cached supplier backfill."
            if ready
            else "Resolve every blocker before public launch."
        ),
        "network_calls": 0,
        "paid_sources_called": False,
    }


@router.get("/launch-gate")
async def admin_launch_gate(
    production: bool = True,
    _admin: bool = Depends(require_admin),
) -> dict[str, Any]:
    return launch_gate_report(production=production)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="No-network IntellCluster production launch gate"
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Require production database, HTTPS URL, strong admin credentials, rate limiting, and paid-data safety defaults",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 2 when any launch blocker remains",
    )
    args = parser.parse_args()
    report = launch_gate_report(production=args.production)
    print(json.dumps(report, indent=2, default=str))
    if args.strict and not report["ready_to_launch"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
