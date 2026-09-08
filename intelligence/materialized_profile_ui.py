from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import select

from intelligence.database import connect, entities


def _script_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, default=str)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _profile_payload(slug: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            select(
                entities.c.summary,
                entities.c.buyer_score,
                entities.c.enrichment,
            ).where(entities.c.slug == slug)
        ).mappings().first()
    if not row:
        return None
    enrichment = row["enrichment"] if isinstance(row["enrichment"], dict) else {}
    intelligence = enrichment.get("intelligence")
    if not isinstance(intelligence, dict) or not intelligence.get("version"):
        return None
    return {
        "summary": str(row["summary"] or ""),
        "buyer_score": int(row["buyer_score"] or intelligence.get("buyer_score") or 0),
        "intelligence": intelligence,
    }


def _profile_ui(payload: dict[str, Any]) -> str:
    data = _script_json(payload)
    return f'''
<style id="intellcluster-materialized-profile-style">
.intel-summary[data-materialized="1"]{{background:#f8f8f9;border-color:#d9dade;box-shadow:none}}
.intel-summary[data-materialized="1"] h2{{color:#202123}}
.intel-summary[data-materialized="1"] .coverage-cell{{background:#fff;border-color:#dedee1;box-shadow:none}}
.intel-summary[data-materialized="1"] .coverage-cell strong{{color:#202123}}
.ic-intel-signal-row{{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}}
.ic-intel-signal{{display:inline-flex;align-items:center;gap:5px;border:1px solid #dedee1;border-radius:999px;background:#fff;padding:4px 7px;color:#686970;font-size:8px}}
.ic-intel-signal:before{{content:"";width:5px;height:5px;border-radius:50%;background:#7d7f85}}
@media(max-width:620px){{.intel-summary[data-materialized="1"] .coverage-strip{{grid-template-columns:repeat(2,1fr)}}}}
</style>
<script id="intellcluster-materialized-profile-ui">
(() => {{
  const data={data},intel=data.intelligence||{{}};
  const number=v=>Number(v||0).toLocaleString();
  const labels={{observed_importer:'Observed importer',import_history:'Import history',supplier_network:'Supplier network',multi_source_enrichment:'Multi-source enrichment',cross_source_identity:'Cross-source identity'}};
  const mount=()=>{{
    const snap=document.querySelector('.intel-summary');if(!snap||!intel.version)return;
    snap.dataset.materialized='1';
    const heading=snap.querySelector('h2');if(heading)heading.textContent='Intelligence Snapshot';
    const paragraph=snap.querySelector('p');if(paragraph&&data.summary)paragraph.textContent=data.summary;
    let strip=snap.querySelector('.coverage-strip');
    if(!strip){{strip=document.createElement('div');strip.className='coverage-strip';snap.appendChild(strip);}}
    const links=Number(intel.importer_relationship_count||0)+Number(intel.supplier_count||0);
    strip.innerHTML=`<div class="coverage-cell"><strong>${{number(data.buyer_score) || '0'}}/100</strong><span>Buyer score</span></div><div class="coverage-cell"><strong>${{number(intel.evidence_score)}}/100</strong><span>Evidence strength</span></div><div class="coverage-cell"><strong>${{number(intel.source_count)}}</strong><span>Matched datasets</span></div><div class="coverage-cell"><strong>${{number(links)}}</strong><span>Linked relationships</span></div>`;
    snap.querySelector('.ic-intel-signal-row')?.remove();
    const signals=(intel.signals||[]).filter(Boolean).slice(0,5);
    if(signals.length){{const row=document.createElement('div');row.className='ic-intel-signal-row';row.innerHTML=signals.map(signal=>`<span class="ic-intel-signal">${{labels[signal]||String(signal).replaceAll('_',' ')}}</span>`).join('');snap.appendChild(row);}}
  }};
  mount();setTimeout(mount,180);setTimeout(mount,850);
}})();
</script>
'''


def install_materialized_profile_ui(app) -> None:
    if getattr(app.state, "intellcluster_materialized_profile_ui_installed", False):
        return
    app.state.intellcluster_materialized_profile_ui_installed = True

    @app.middleware("http")
    async def materialized_profile_ui(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if (
            response.status_code != 200
            or not path.startswith("/data/company/")
            or path.count("/") != 3
            or "text/html" not in response.headers.get("content-type", "")
        ):
            return response

        slug = path.rstrip("/").rsplit("/", 1)[-1]
        payload = _profile_payload(slug)
        if payload is None:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        if "</body>" not in text:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="text/html",
            )
        text = text.replace("</body>", _profile_ui(payload) + "</body>")
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=text,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
