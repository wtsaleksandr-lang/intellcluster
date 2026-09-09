from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import func, select

from intelligence.database import (
    connect,
    entities,
    importer_relationships,
    source_records,
    supplier_relationships,
)


def _script_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, default=str)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _human_source(value: str) -> str:
    labels = {
        "corporations_canada": "Corporations Canada",
        "canadian_importers": "Canadian Importers",
        "major_importers_hs10": "Canadian Importers — HS10",
        "importyeti": "ImportYeti",
    }
    return labels.get(value, value.replace("_", " ").strip().title())


def _profile_payload(slug: str) -> dict[str, Any] | None:
    with connect() as conn:
        company = conn.execute(
            select(
                entities.c.id,
                entities.c.canonical_name,
                entities.c.buyer_score,
                entities.c.enrichment,
                entities.c.corporate_status,
                entities.c.incorporated_year,
            ).where(entities.c.slug == slug)
        ).mappings().first()
        if not company:
            return None

        enrichment = company["enrichment"] if isinstance(company["enrichment"], dict) else {}
        # Full ImportYeti/BOL profiles already receive the richer shipment UI from
        # company_core.html. This layer is specifically the honest fallback for
        # public-source profiles that would otherwise look unfinished.
        if isinstance(enrichment.get("importyeti"), dict) and enrichment.get("importyeti"):
            return None

        entity_id = int(company["id"])
        relationships = conn.execute(
            select(
                importer_relationships.c.activity_year,
                importer_relationships.c.hs6,
                importer_relationships.c.hs10,
                importer_relationships.c.product_description,
                importer_relationships.c.origin_country,
                importer_relationships.c.dataset,
            )
            .where(importer_relationships.c.entity_id == entity_id)
            .order_by(importer_relationships.c.activity_year.desc().nullslast(), importer_relationships.c.id.desc())
            .limit(500)
        ).mappings().all()
        if not relationships:
            return None

        source_rows = conn.execute(
            select(source_records.c.source, func.count(source_records.c.id).label("count"))
            .where(source_records.c.entity_id == entity_id)
            .group_by(source_records.c.source)
            .order_by(func.count(source_records.c.id).desc())
        ).mappings().all()
        supplier_count = int(
            conn.execute(
                select(func.count())
                .select_from(supplier_relationships)
                .where(supplier_relationships.c.importer_entity_id == entity_id)
            ).scalar_one()
            or 0
        )

    rows = [dict(row) for row in relationships]
    year_counts: Counter[str] = Counter()
    hs_counts: Counter[str] = Counter()
    origin_counts: Counter[str] = Counter()
    dataset_counts: Counter[str] = Counter()
    product_by_hs: dict[str, str] = {}

    for row in rows:
        if row.get("activity_year"):
            year_counts[str(row["activity_year"])] += 1
        code = str(row.get("hs10") or row.get("hs6") or "").strip()
        if code:
            hs_counts[code] += 1
            description = str(row.get("product_description") or "").strip()
            if description:
                product_by_hs.setdefault(code, description)
        origin = str(row.get("origin_country") or "").strip()
        if origin:
            origin_counts[origin] += 1
        dataset = str(row.get("dataset") or "").strip()
        if dataset:
            dataset_counts[dataset] += 1

    relationship_count = len(rows)
    top_hs_count = max(hs_counts.values(), default=0)
    top_hs_share = round((top_hs_count * 100 / relationship_count), 1) if relationship_count else 0.0
    latest_year = max((int(y) for y in year_counts if y.isdigit()), default=None)
    earliest_year = min((int(y) for y in year_counts if y.isdigit()), default=None)
    intelligence = enrichment.get("intelligence") if isinstance(enrichment.get("intelligence"), dict) else {}

    source_breakdown = [
        {"name": _human_source(str(row["source"])), "count": int(row["count"] or 0)}
        for row in source_rows
    ]
    source_record_count = sum(row["count"] for row in source_breakdown)

    recent = []
    for row in rows[:12]:
        recent.append(
            {
                "year": row.get("activity_year"),
                "hs": str(row.get("hs10") or row.get("hs6") or ""),
                "product": str(row.get("product_description") or ""),
                "origin": str(row.get("origin_country") or ""),
                "dataset": _human_source(str(row.get("dataset") or "")),
            }
        )

    return {
        "company": str(company["canonical_name"]),
        "buyer_score": int(company["buyer_score"] or intelligence.get("buyer_score") or 0),
        "evidence_score": int(intelligence.get("evidence_score") or 0),
        "corporate_status": str(company["corporate_status"] or ""),
        "incorporated_year": company["incorporated_year"],
        "relationship_count": relationship_count,
        "hs_count": len(hs_counts),
        "origin_count": len(origin_counts),
        "year_count": len(year_counts),
        "supplier_count": supplier_count,
        "source_count": len(source_breakdown),
        "source_record_count": source_record_count,
        "top_hs_share": top_hs_share,
        "latest_year": latest_year,
        "earliest_year": earliest_year,
        "years": [{"label": year, "count": count} for year, count in sorted(year_counts.items())],
        "products": [
            {
                "hs": code,
                "count": count,
                "share": round(count * 100 / relationship_count, 1),
                "description": product_by_hs.get(code, ""),
            }
            for code, count in hs_counts.most_common(8)
        ],
        "origins": [
            {"name": name, "count": count, "share": round(count * 100 / relationship_count, 1)}
            for name, count in origin_counts.most_common(8)
        ],
        "datasets": [
            {"name": _human_source(name), "count": count}
            for name, count in dataset_counts.most_common(8)
        ],
        "sources": source_breakdown,
        "recent": recent,
    }


def _profile_ui(payload: dict[str, Any]) -> str:
    data = _script_json(payload)
    return f'''
<style id="intellcluster-low-data-profile-style">
.ic-analytics{{margin:20px 0 28px;color:#202124}}
.ic-analytics *{{box-sizing:border-box}}
.ic-analytics-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:12px}}
.ic-analytics-head h2{{margin:0;color:#173f4b;font-size:18px;letter-spacing:-.2px}}
.ic-analytics-head p{{margin:5px 0 0;max-width:760px;font-size:9px;line-height:1.55;color:#74787d}}
.ic-data-badge{{display:inline-flex;align-items:center;border:1px solid #d7dde0;border-radius:999px;background:#fafbfb;padding:5px 8px;font-size:8px;color:#687178;white-space:nowrap}}
.ic-kpi-grid{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin-bottom:12px}}
.ic-kpi{{border:1px solid #dce1e4;border-radius:7px;background:#fff;padding:12px 11px;min-height:78px}}
.ic-kpi strong{{display:block;font-size:21px;line-height:1;color:#073f50;font-weight:760}}
.ic-kpi span{{display:block;margin-top:7px;font-size:8px;text-transform:uppercase;letter-spacing:.45px;color:#70777c}}
.ic-kpi small{{display:block;margin-top:4px;font-size:7px;color:#9a9fa3;line-height:1.35}}
.ic-chart-grid{{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr);gap:12px;margin-bottom:12px}}
.ic-panel{{border:1px solid #dce1e4;border-radius:8px;background:#fff;overflow:hidden}}
.ic-panel-head{{padding:12px 14px;border-bottom:1px solid #e4e7e9;background:#fafbfb}}
.ic-panel-head strong{{display:block;color:#173f4b;font-size:12px}}
.ic-panel-head span{{display:block;margin-top:3px;color:#858a8e;font-size:8px}}
.ic-panel-body{{padding:14px}}
.ic-year-chart{{height:190px;display:flex;align-items:flex-end;gap:8px;border-bottom:1px solid #d6dde0;padding:12px 8px 0;background:linear-gradient(to bottom,transparent 49%,#eef1f2 50%,transparent 50.7%)}}
.ic-year-col{{flex:1;min-width:30px;max-width:72px;text-align:center;align-self:stretch;display:flex;flex-direction:column;justify-content:flex-end}}
.ic-year-value{{font-size:8px;color:#58636a;margin-bottom:4px}}
.ic-year-bar{{width:100%;min-height:8px;border-radius:4px 4px 0 0;background:#0a6075}}
.ic-year-label{{font-size:8px;color:#747a7f;padding-top:6px;white-space:nowrap}}
.ic-mix-row{{display:grid;grid-template-columns:70px minmax(0,1fr) 38px;gap:8px;align-items:center;margin-bottom:10px}}
.ic-mix-row:last-child{{margin-bottom:0}}
.ic-mix-code{{font-size:8px;font-weight:700;color:#365d6b;overflow:hidden;text-overflow:ellipsis}}
.ic-mix-track{{height:10px;border-radius:999px;background:#eef1f2;overflow:hidden}}
.ic-mix-fill{{height:100%;border-radius:999px;background:#0a6075}}
.ic-mix-share{{font-size:8px;color:#646b70;text-align:right}}
.ic-mix-desc{{grid-column:2 / 4;font-size:7px;color:#92979b;margin-top:-5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.ic-signal-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}}
.ic-signal{{border:1px solid #e0e4e6;border-radius:7px;padding:11px 12px;background:#fbfcfc}}
.ic-signal b{{display:block;font-size:9px;color:#2e4d57}}
.ic-signal span{{display:block;margin-top:5px;font-size:8px;line-height:1.45;color:#757c81}}
.ic-evidence-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}}
.ic-source-list{{display:flex;flex-wrap:wrap;gap:6px}}
.ic-source-chip{{border:1px solid #dbe0e3;border-radius:999px;background:#fff;padding:6px 8px;font-size:8px;color:#5e686e}}
.ic-empty-state{{border:1px dashed #cfd7db;border-radius:7px;background:#fafbfb;padding:13px}}
.ic-empty-state b{{display:block;color:#455b65;font-size:9px}}
.ic-empty-state span{{display:block;margin-top:5px;color:#82888d;font-size:8px;line-height:1.5}}
.ic-origin-list{{display:grid;gap:7px}}
.ic-origin-row{{display:grid;grid-template-columns:120px minmax(0,1fr) 40px;gap:7px;align-items:center;font-size:8px}}
.ic-origin-track{{height:8px;border-radius:999px;background:#eef1f2;overflow:hidden}}
.ic-origin-fill{{height:100%;background:#547f8c;border-radius:999px}}
.ic-records-wrap{{overflow:auto;max-height:340px}}
.ic-records{{width:100%;border-collapse:collapse;font-size:8px}}
.ic-records th{{position:sticky;top:0;background:#f2f5f6;text-align:left;color:#617078;font-size:7px;text-transform:uppercase;letter-spacing:.4px;padding:8px;border-bottom:1px solid #d8dfe2}}
.ic-records td{{padding:9px 8px;border-bottom:1px solid #e8ebed;vertical-align:top;color:#4f5b61}}
.ic-records tr:last-child td{{border-bottom:0}}
.ic-records .ic-product{{min-width:260px;line-height:1.4}}
.ic-data-note{{margin-top:10px;border-left:3px solid #9aa7ad;background:#f7f8f8;padding:9px 11px;color:#7b8185;font-size:8px;line-height:1.55}}
@media(max-width:900px){{.ic-kpi-grid{{grid-template-columns:repeat(3,1fr)}}.ic-chart-grid,.ic-evidence-grid{{grid-template-columns:1fr}}}}
@media(max-width:560px){{.ic-kpi-grid{{grid-template-columns:repeat(2,1fr)}}.ic-signal-grid{{grid-template-columns:1fr}}.ic-analytics-head{{display:block}}.ic-data-badge{{margin-top:8px}}}}
</style>
<script id="intellcluster-low-data-profile-ui">
(() => {{
 const data={data};
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
 const num=v=>Number(v||0).toLocaleString();
 const pct=v=>`${{Number(v||0).toFixed(Number(v||0)%1?1:0)}}%`;
 const mount=()=>{{
   if(document.getElementById('ic-low-data-analytics'))return;
   const anchor=document.querySelector('.intel-summary')||document.querySelector('.trade-wrap')||document.querySelector('main');
   if(!anchor)return;
   const years=data.years||[], products=data.products||[], origins=data.origins||[], sources=data.sources||[], recent=data.recent||[];
   const maxYear=Math.max(1,...years.map(x=>Number(x.count||0)));
   const yearChart=years.length?years.map(x=>`<div class="ic-year-col"><span class="ic-year-value">${{num(x.count)}}</span><div class="ic-year-bar" style="height:${{Math.max(8,Math.round(Number(x.count||0)*145/maxYear))}}px"></div><span class="ic-year-label">${{esc(x.label)}}</span></div>`).join(''):`<div class="ic-empty-state"><b>No dated trade observations</b><span>The current public source does not provide a usable activity year for this entity.</span></div>`;
   const productMix=products.length?products.map(x=>`<div class="ic-mix-row"><div class="ic-mix-code">HS ${{esc(x.hs)}}</div><div class="ic-mix-track"><div class="ic-mix-fill" style="width:${{Math.max(3,Number(x.share||0))}}%"></div></div><div class="ic-mix-share">${{pct(x.share)}}</div>${{x.description?`<div class="ic-mix-desc" title="${{esc(x.description)}}">${{esc(x.description)}}</div>`:''}}</div>`).join(''):`<div class="ic-empty-state"><b>No HS mix available</b><span>No product-code distribution is available from the current evidence.</span></div>`;
   const originBody=origins.length?`<div class="ic-origin-list">${{origins.map(x=>`<div class="ic-origin-row"><span>${{esc(x.name)}}</span><div class="ic-origin-track"><div class="ic-origin-fill" style="width:${{Math.max(3,Number(x.share||0))}}%"></div></div><strong>${{pct(x.share)}}</strong></div>`).join('')}}</div>`:`<div class="ic-empty-state"><b>Origin country not disclosed</b><span>This Canadian public record identifies the importer and product code but does not disclose a supplier/origin country. We keep this unknown rather than infer it.</span></div>`;
   const sourceBody=sources.length?`<div class="ic-source-list">${{sources.map(x=>`<span class="ic-source-chip">${{esc(x.name)}} · ${{num(x.count)}} record${{Number(x.count)===1?'':'s'}}</span>`).join('')}}</div>`:`<div class="ic-empty-state"><b>Source provenance unavailable</b><span>No source breakdown was returned for this entity.</span></div>`;
   const recentRows=recent.map(x=>`<tr><td>${{esc(x.year||'—')}}</td><td><b>HS ${{esc(x.hs||'—')}}</b></td><td class="ic-product">${{esc(x.product||'No product description')}}</td><td>${{esc(x.origin||'Not disclosed')}}</td><td>${{esc(x.dataset||'Public source')}}</td></tr>`).join('');
   const focused=Number(data.top_hs_share||0)>=80;
   const latest=data.latest_year?String(data.latest_year):'Unknown';
   const el=document.createElement('section');el.id='ic-low-data-analytics';el.className='ic-analytics profile-anchor';
   el.innerHTML=`
     <div class="ic-analytics-head"><div><h2>Trade Intelligence</h2><p>A complete low-data view built from the evidence we actually have. Public Canadian importer records are analyzed as trade observations; they are not presented as individual bills of lading.</p></div><span class="ic-data-badge">Public-source analytics</span></div>
     <div class="ic-kpi-grid">
       <div class="ic-kpi"><strong>${{num(data.relationship_count)}}</strong><span>Observed trade records</span><small>Indexed public importer relationships</small></div>
       <div class="ic-kpi"><strong>${{num(data.hs_count)}}</strong><span>HS codes</span><small>Distinct product classifications</small></div>
       <div class="ic-kpi"><strong>${{num(data.year_count)}}</strong><span>Observed years</span><small>${{data.earliest_year&&data.latest_year?`${{data.earliest_year}}–${{data.latest_year}}`:'Dated evidence only'}}</small></div>
       <div class="ic-kpi"><strong>${{num(data.origin_count)}}</strong><span>Origin markets</span><small>${{data.origin_count?'Disclosed in source':'Not disclosed in source'}}</small></div>
       <div class="ic-kpi"><strong>${{pct(data.top_hs_share)}}</strong><span>Top product share</span><small>Concentration of observed records</small></div>
       <div class="ic-kpi"><strong>${{num(data.buyer_score)}}/100</strong><span>Buyer score</span><small>Evidence-weighted IntellCluster signal</small></div>
     </div>
     <div class="ic-chart-grid">
       <div class="ic-panel"><div class="ic-panel-head"><strong>Observed trade activity over time</strong><span>Count of indexed public trade records by year</span></div><div class="ic-panel-body"><div class="ic-year-chart">${{yearChart}}</div></div></div>
       <div class="ic-panel"><div class="ic-panel-head"><strong>Product / HS concentration</strong><span>Share of observed trade records by product code</span></div><div class="ic-panel-body">${{productMix}}</div></div>
     </div>
     <div class="ic-signal-grid">
       <div class="ic-signal"><b>${{focused?'Focused product footprint':'Diversified product footprint'}}</b><span>${{focused?`${{pct(data.top_hs_share)}} of observed records fall under the leading HS code.`:`The leading HS code represents ${{pct(data.top_hs_share)}} of observed records.`}}</span></div>
       <div class="ic-signal"><b>Latest observed trade year: ${{esc(latest)}}</b><span>This is the latest dated public trade evidence currently linked to the company; it is not a claim about its latest physical shipment.</span></div>
       <div class="ic-signal"><b>${{num(data.source_count)}} matched dataset${{Number(data.source_count)===1?'':'s'}}</b><span>${{num(data.source_record_count)}} source record${{Number(data.source_record_count)===1?'':'s'}} support the canonical company identity and trade profile.</span></div>
     </div>
     <div class="ic-evidence-grid">
       <div class="ic-panel"><div class="ic-panel-head"><strong>Origin / geography evidence</strong><span>Only source-disclosed origins are counted</span></div><div class="ic-panel-body">${{originBody}}</div></div>
       <div class="ic-panel"><div class="ic-panel-head"><strong>Evidence & provenance</strong><span>Sources supporting this company profile</span></div><div class="ic-panel-body">${{sourceBody}}<div style="height:9px"></div>${{Number(data.supplier_count)>0?`<div class="ic-source-chip">${{num(data.supplier_count)}} linked supplier${{Number(data.supplier_count)===1?'':'s'}}</div>`:`<div class="ic-empty-state"><b>Supplier names not available in this source</b><span>Supplier/BOL sections appear when shipment-level enrichment provides defensible supplier evidence. We do not manufacture supplier names from product codes.</span></div>`}}</div></div>
     </div>
     <div class="ic-panel"><div class="ic-panel-head"><strong>Observed trade records</strong><span>The underlying evidence behind the analytics above</span></div><div class="ic-records-wrap"><table class="ic-records"><thead><tr><th>Year</th><th>HS code</th><th>Product</th><th>Origin</th><th>Dataset</th></tr></thead><tbody>${{recentRows}}</tbody></table></div></div>
     <div class="ic-data-note"><b>Data interpretation:</b> Canadian Importers records identify public importer/product relationships. They do not provide the same bill-of-lading detail as U.S. Customs shipment records. Shipment counts, TEU, estimated freight spend, supplier names and monthly shipment-frequency charts are therefore shown only when a shipment-level source supports them.</div>`;
   anchor.insertAdjacentElement('afterend',el);
 }};
 mount();setTimeout(mount,180);setTimeout(mount,900);
}})();
</script>
'''


def install_low_data_profile_ui(app) -> None:
    if getattr(app.state, "intellcluster_low_data_profile_ui_installed", False):
        return
    app.state.intellcluster_low_data_profile_ui_installed = True

    @app.middleware("http")
    async def low_data_profile_ui(request: Request, call_next):
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
