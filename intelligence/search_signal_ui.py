from __future__ import annotations

import json
import re
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import select

from intelligence.database import connect, entities


_PROFILE_LINK = re.compile(r'href=["\']/data/company/([^"\'/?#]+)')


def _money(value: object) -> str | None:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


def _number(value: object) -> int | None:
    try:
        return int(float(str(value))) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _signals(row: dict[str, Any]) -> list[dict[str, str]]:
    if str(row.get("country") or "").upper() != "US":
        return []
    enrichment = row.get("enrichment") if isinstance(row.get("enrichment"), dict) else {}
    signals: list[dict[str, str]] = []

    fmcsa = enrichment.get("fmcsa") if isinstance(enrichment.get("fmcsa"), dict) else None
    if fmcsa:
        dot = str(fmcsa.get("dot_number") or fmcsa.get("usdot_number") or "").strip()
        power_units = _number(fmcsa.get("power_units"))
        drivers = _number(fmcsa.get("total_drivers") or fmcsa.get("drivers"))
        if dot:
            signals.append(
                {
                    "label": "USDOT",
                    "value": dot,
                    "target": "us-public-intelligence",
                    "kind": "fleet",
                }
            )
        if power_units is not None:
            signals.append(
                {
                    "label": "Fleet",
                    "value": f"{power_units:,} power units",
                    "target": "us-public-intelligence",
                    "kind": "fleet",
                }
            )
        elif drivers is not None:
            signals.append(
                {
                    "label": "Drivers",
                    "value": f"{drivers:,}",
                    "target": "us-public-intelligence",
                    "kind": "fleet",
                }
            )

    spending = (
        enrichment.get("usaspending")
        if isinstance(enrichment.get("usaspending"), dict)
        else None
    )
    if spending:
        awards = _number(spending.get("contract_awards_shown"))
        award_value = _money(spending.get("contract_award_value_shown"))
        if award_value:
            signals.append(
                {
                    "label": "Federal Awards",
                    "value": award_value,
                    "target": "us-public-intelligence",
                    "kind": "contract",
                }
            )
        elif awards is not None:
            signals.append(
                {
                    "label": "Federal Awards",
                    "value": f"{awards:,} shown",
                    "target": "us-public-intelligence",
                    "kind": "contract",
                }
            )

    sec = enrichment.get("sec_edgar") if isinstance(enrichment.get("sec_edgar"), dict) else None
    if sec:
        ticker = str(sec.get("ticker") or "").strip()
        latest_form = str(sec.get("latest_filing_form") or "").strip()
        signals.append(
            {
                "label": "SEC EDGAR",
                "value": ticker or latest_form or "filer evidence",
                "target": "sec-edgar-intelligence",
                "kind": "filing",
            }
        )

    echo = enrichment.get("epa_echo") if isinstance(enrichment.get("epa_echo"), dict) else None
    if echo:
        facilities = _number(echo.get("facility_count"))
        if facilities is not None:
            signals.append(
                {
                    "label": "EPA Facilities",
                    "value": f"{facilities:,} cached",
                    "target": "us-compliance-intelligence",
                    "kind": "compliance",
                }
            )

    osha = enrichment.get("osha") if isinstance(enrichment.get("osha"), dict) else None
    if osha and not echo:
        inspections = _number(osha.get("inspection_count_shown"))
        if inspections is not None:
            signals.append(
                {
                    "label": "OSHA",
                    "value": f"{inspections:,} inspections",
                    "target": "us-compliance-intelligence",
                    "kind": "compliance",
                }
            )

    # Four concise, highest-signal facts keep cards scannable on mobile and desktop.
    return signals[:4]


def install_search_signal_ui(app) -> None:
    if getattr(app.state, "intellcluster_search_signal_ui_installed", False):
        return
    app.state.intellcluster_search_signal_ui_installed = True

    @app.middleware("http")
    async def search_signal_ui(request: Request, call_next):
        response = await call_next(request)
        if (
            request.method != "GET"
            or request.url.path != "/data/search"
            or response.status_code != 200
            or "text/html" not in response.headers.get("content-type", "")
        ):
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        slugs = sorted({match.group(1) for match in _PROFILE_LINK.finditer(text)})
        if not slugs:
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return Response(
                content=text,
                status_code=response.status_code,
                headers=headers,
                media_type="text/html",
            )

        with connect() as conn:
            rows = conn.execute(
                select(
                    entities.c.slug,
                    entities.c.country,
                    entities.c.enrichment,
                ).where(entities.c.slug.in_(slugs))
            ).mappings().all()

        payload = {
            str(row["slug"]): signals
            for row in rows
            if (signals := _signals(dict(row)))
        }
        if payload and "</body>" in text:
            encoded = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
            enhancer = f"""
<style id="intellcluster-us-search-signals">
body[data-intell-search] .ic-us-signal-row{{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}}
body[data-intell-search] .ic-us-signal{{display:inline-flex;align-items:center;gap:5px;min-height:23px;padding:3px 7px;border:1px solid #dce4e8;border-radius:5px;background:#f8fafb;color:#52646d;font-size:8px;line-height:1.2}}
body[data-intell-search] .ic-us-signal b{{font-size:7px;text-transform:uppercase;letter-spacing:.25px;color:#7b8990}}
body[data-intell-search] .ic-us-signal:hover{{border-color:#aebfc7;background:#fff;color:#173846}}
body[data-intell-search] .ic-us-signal[data-kind="fleet"]{{border-left:3px solid #4e879d}}
body[data-intell-search] .ic-us-signal[data-kind="contract"]{{border-left:3px solid #a48642}}
body[data-intell-search] .ic-us-signal[data-kind="filing"]{{border-left:3px solid #66798b}}
body[data-intell-search] .ic-us-signal[data-kind="compliance"]{{border-left:3px solid #758e78}}
</style>
<script id="intellcluster-us-search-signal-data">
(()=>{{
 const data={encoded};
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
 document.querySelectorAll('.card').forEach(card=>{{
   const profile=card.querySelector('a.card-title[href^="/data/company/"]');if(!profile)return;
   const slug=(profile.getAttribute('href')||'').split('/').filter(Boolean).pop();const signals=data[slug];if(!signals?.length)return;
   card.querySelector('.ic-us-signal-row')?.remove();const row=document.createElement('div');row.className='ic-us-signal-row';
   signals.forEach(signal=>{{const a=document.createElement('a');a.className='ic-us-signal';a.dataset.kind=signal.kind||'';a.href=`/data/company/${{encodeURIComponent(slug)}}#${{signal.target||''}}`;a.innerHTML=`<b>${{esc(signal.label)}}</b><span>${{esc(signal.value)}}</span>`;row.appendChild(a)}});
   const stats=card.querySelector('.stats-row');if(stats)stats.insertAdjacentElement('afterend',row);else card.querySelector('.card-body')?.appendChild(row);
 }});
}})();
</script>
"""
            text = text.replace("</body>", enhancer + "</body>")

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=text,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
