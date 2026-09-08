"""
Doppler -> os.environ bootstrap. Imported FIRST in main.py, before any
other module that reads os.environ at import time (config.py reads
secrets eagerly via pydantic Settings, etc.).

Goal: pull secrets stored only in Doppler into the runtime env so we
don't have to manually mirror everything into Replit Secrets. The
inverse case -- secrets only in Replit Secrets -- also still works
because Replit-injected env vars take precedence by default (we only
fill in MISSING keys; never overwrite).

Override list (opt-in escape hatch): `DOPPLER_OVERRIDE_KEYS` --
comma-separated list of env-var names whose Doppler value should WIN
over any pre-existing os.environ value. Default is empty (no overrides
-> existing behaviour). The list can be set in Replit Secrets (highest
priority, useful for emergency disable) or in the Doppler config itself.

Failure mode: soft. If DOPPLER_TOKEN is unset, Doppler is unreachable,
the response is malformed, or the request times out, we log a warning
and continue with whatever env the runtime already has. The server
still boots; only Doppler-only secrets are missing.

Stdlib-only (urllib.request, os, json) on purpose -- this module must
import cleanly before any third-party deps are guaranteed to be loaded,
and it's a side-effect module so we don't want to widen the dependency
surface.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


def _bootstrap() -> None:
    token = os.environ.get("DOPPLER_TOKEN")
    if not token:
        print("[doppler-bootstrap] DOPPLER_TOKEN not set - skipping")
        return

    project = os.environ.get("DOPPLER_PROJECT") or "intellcluster"
    config = os.environ.get("DOPPLER_CONFIG") or "prd"
    qs = urllib.parse.urlencode({
        "project": project,
        "config": config,
        "include_dynamic_secrets": "false",
        "include_managed_secrets": "false",
    })
    url = f"https://api.doppler.com/v3/configs/config/secrets?{qs}"

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as err:
        msg = str(err).splitlines()[0] if str(err) else type(err).__name__
        print(f"[doppler-bootstrap] fetch failed ({msg}) - proceeding without Doppler")
        return
    except Exception as err:  # noqa: BLE001 - soft-fail is mandatory; never raise out of bootstrap
        msg = str(err).splitlines()[0] if str(err) else type(err).__name__
        print(f"[doppler-bootstrap] unexpected fetch error ({msg}) - proceeding without Doppler")
        return

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        print("[doppler-bootstrap] response was not valid JSON - proceeding without Doppler")
        return

    secrets = payload.get("secrets") if isinstance(payload, dict) else None
    if not isinstance(secrets, dict):
        print("[doppler-bootstrap] response had no secrets map - proceeding without Doppler")
        return

    # Override list: Replit-Secret value takes precedence (emergency-disable
    # path), else fall back to Doppler-stored value. Empty list = no overrides
    # (current behaviour preserved).
    def _val(entry: object) -> str:
        if not isinstance(entry, dict):
            return ""
        computed = entry.get("computed")
        if isinstance(computed, str) and computed:
            return computed
        rawv = entry.get("raw")
        if isinstance(rawv, str) and rawv:
            return rawv
        return ""

    override_raw = (
        os.environ.get("DOPPLER_OVERRIDE_KEYS")
        or _val(secrets.get("DOPPLER_OVERRIDE_KEYS"))
        or ""
    )
    override_keys = {
        s.strip() for s in override_raw.split(",") if s.strip()
    }

    applied = 0
    skipped_existing = 0
    skipped_empty = 0
    overrode = 0
    overrode_names = []

    for key, value in secrets.items():
        # Doppler bookkeeping vars -- never inject these into the app
        if key.startswith("DOPPLER_") or key == "NAME":
            continue

        force = key in override_keys
        current = os.environ.get(key)
        has_runtime = current is not None and current != ""

        # Default rule: Replit / runtime env wins. Override list flips that for
        # listed keys only.
        if has_runtime and not force:
            skipped_existing += 1
            continue

        v = _val(value)
        if v:
            if force and has_runtime and current != v:
                overrode += 1
                overrode_names.append(key)
            os.environ[key] = v
            applied += 1
        else:
            skipped_empty += 1

    suffix = f" ({','.join(overrode_names)})" if overrode_names else ""
    print(
        f"[doppler-bootstrap] project={project} config={config} "
        f"fetched={len(secrets)} applied={applied} "
        f"kept-from-runtime={skipped_existing} empty={skipped_empty} "
        f"override={overrode}{suffix}"
    )


try:
    _bootstrap()
except Exception as err:  # noqa: BLE001 - last-line defence; bootstrap must never break boot
    print(f"[doppler-bootstrap] unexpected error ({err!r}) - proceeding without Doppler")
