from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

_CANADABUYS_PROFILE_UI = r'''
<style id="intellcluster-canadabuys-profile-style">
body[data-intell-profile] .ic-cb{margin:18px 0;border:1px solid #d9e0e4;border-radius:8px;background:#fff;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.025)}
body[data-intell-profile] .ic-cb-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:13px 15px;background:#f8fafb;border-bottom:1px solid #e1e6e9}
body[data-intell-profile] .ic-cb-kicker{font-size:7px;font-weight:800;letter-spacing:.65px;text-transform:uppercase;color:#5f6f78}
body[data-intell-profile] .ic-cb-head h2{margin:4px 0 0;font-size:15px;color:#1f343e}
body[data-intell-profile] .ic-cb-head p{margin:4px 0 0;color:#79878e;font-size:8px;line-height:1.45;max-width:680px}
body[data-intell-profile] .ic-cb-actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
body[data-intell-profile] .ic-cb-source,body[data-intell-profile] .ic-cb-export{display:inline-flex;align-items:center;border:1px solid #d8e0e4;border-radius:999px;background:#fff;padding:4px 7px;color:#596a72;font-size:7px;font-weight:750;white-space:nowrap}
body[data-intell-profile] .ic-cb-export{border-radius:5px;color:#365b6c}
body[data-intell-profile] .ic-cb-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;padding:12px 14px}
body[data-intell-profile] .ic-cb-kpi{border:1px solid #e0e5e8;border-radius:6px;padding:9px 10px;background:#fff;min-height:68px}
body[data-intell-profile] .ic-cb-kpi small{display:block;color:#7d898f;font-size:7px;text-transform:uppercase;letter-spacing:.35px}
body[data-intell-profile] .ic-cb-kpi strong{display:block;color:#243c47;font-size:15px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body[data-intell-profile] .ic-cb-kpi span{display:block;color:#909a9f;font-size:7px;margin-top:3px;line-height:1.3}
body[data-intell-profile] .ic-cb-table-wrap{margin:0 14px 13px;max-height:360px;overflow:auto;border:1px solid #e0e5e8;border-radius:6px}
body[data-intell-profile] .ic-cb-table{width:100%;border-collapse:collapse;font-size:8px;min-width:720px}
body[data-intell-profile] .ic-cb-table th{position:sticky;top:0;background:#f3f6f7;color:#6f7e85;text-align:left;font-size:7px;padding:7px 8px;border-bottom:1px solid #dfe5e8}
body[data-intell-profile] .ic-cb-table td{padding:8px;border-bottom:1px solid #edf0f2;color:#40545d;vertical-align:top}
body[data-intell-profile] .ic-cb-table tbody tr:nth-child(even){background:#fbfcfc}
body[data-intell-profile] .ic-cb-value{white-space:nowrap;font-weight:750;color:#365b49}
body[data-intell-profile] .ic-cb-note{padding:8px 14px;border-top:1px solid #e7ebed;background:#fcfcfd;color:#858f94;font-size:7px;line-height:1.45}
@media(max-width:600px){body[data-intell-profile] .ic-cb-head{flex-direction:column}body[data-intell-profile] .ic-cb-actions{justify-content:flex-start}}
</style>
<script id="intellcluster-canadabuys-profile-ui">
(() => {
  const match=location.pathname.match(/^\/data\/company\/([^/]+)\/?$/);if(!match)return;
  const slug=match[1];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=(v,c='CAD')=>{const n=Number(v||0);return Number.isFinite(n)&&n?`${esc(c)} ${n.toLocaleString(undefined,{maximumFractionDigits:0})}`:'—'};
  const mount=company=>{
    const data=company?.enrichment?.canadabuys_contracts;if(!data||typeof data!=='object')return;
    document.getElementById('canadabuys-contract-intelligence')?.remove();
    const section=document.createElement('section');section.id='canadabuys-contract-intelligence';section.className='ic-cb profile-anchor';
    const cached=data._cachedAt?String(data._cachedAt).slice(0,10):'';
    section.innerHTML=`<div class="ic-cb-head"><div><div class="ic-cb-kicker">GOVERNMENT BUSINESS</div><h2>CanadaBuys Contract Intelligence</h2><p>Federal contract-history evidence matched to this company from the official CanadaBuys open dataset. Profile views use the stored cache only.</p></div><div class="ic-cb-actions"><span class="ic-cb-source">CanadaBuys${cached?' · '+esc(cached):''}</span><a class="ic-cb-export" href="/data/company/${encodeURIComponent(slug)}/canadabuys-contracts.csv" download>⇩ Export contract CSV</a></div></div>`;
    const departments=Array.isArray(data.top_departments)?data.top_departments:[];
    const topDept=departments[0]?.name||'—';
    const rows=Array.isArray(data.contracts)?data.contracts:[];
    const latest=rows.map(r=>r.award_date||r.publication_date||r.amendment_date||'').filter(Boolean).sort().reverse()[0]||'—';
    const grid=document.createElement('div');grid.className='ic-cb-grid';grid.innerHTML=`<div class="ic-cb-kpi"><small>Federal Contracts</small><strong>${Number(data.contract_count||0).toLocaleString()}</strong><span>unique contracts in cached history</span></div><div class="ic-cb-kpi"><small>CAD Value Shown</small><strong>${money(data.cad_value_shown,'CAD')}</strong><span>${Number(data.cad_valued_contract_count||0).toLocaleString()} CAD-valued contracts</span></div><div class="ic-cb-kpi"><small>Latest Award</small><strong>${esc(latest)}</strong><span>latest cached contract date</span></div><div class="ic-cb-kpi"><small>Top Federal Buyer</small><strong>${esc(topDept)}</strong><span>${departments[0]?.count?Number(departments[0].count).toLocaleString()+' contracts':'cached relationship'}</span></div>`;section.appendChild(grid);
    if(rows.length){const wrap=document.createElement('div');wrap.className='ic-cb-table-wrap';wrap.innerHTML=`<table class="ic-cb-table"><thead><tr><th>Award</th><th>Contract</th><th>What it was for</th><th>Federal buyer</th><th>Value</th><th>Status</th></tr></thead><tbody>${rows.slice(0,30).map(r=>`<tr><td>${esc(r.award_date||r.publication_date||'—')}</td><td><strong>${esc(r.contract_number||r.reference_number||'—')}</strong></td><td>${esc(r.title||r.award_description||'—')}</td><td>${esc(r.contracting_entity||'—')}</td><td class="ic-cb-value">${money(r.value,r.currency||'CAD')}</td><td>${esc(r.status||r.instrument_type||'—')}</td></tr>`).join('')}</tbody></table>`;section.appendChild(wrap);}
    const note=document.createElement('div');note.className='ic-cb-note';note.textContent=data.value_note||'CanadaBuys contract history includes amendments. Values are analytical context and should not be interpreted as audited company revenue or government spend.';section.appendChild(note);
    const sec=document.getElementById('sec-edgar-intelligence');const patents=document.getElementById('uspto-patent-intelligence');const compliance=document.getElementById('us-compliance-intelligence');const caps=document.querySelector('.ic-capability-wrap');if(patents)patents.insertAdjacentElement('beforebegin',section);else if(sec)sec.insertAdjacentElement('afterend',section);else if(compliance)compliance.insertAdjacentElement('beforebegin',section);else if(caps)caps.insertAdjacentElement('afterend',section);else document.querySelector('.profile-box')?.insertAdjacentElement('afterend',section);
    const source=document.querySelector('.source-line');if(source&&![...source.querySelectorAll('.ic-source-badge')].some(x=>/CanadaBuys/i.test(x.textContent||''))){const badge=document.createElement('span');badge.className='ic-source-badge';badge.innerHTML='<i class="ic-source-dot"></i>CanadaBuys';source.appendChild(badge);}
  };
  fetch(`/api/intelligence/company/${encodeURIComponent(slug)}`).then(r=>r.ok?r.json():null).then(payload=>{if(payload?.company)mount(payload.company)}).catch(()=>{});
})();
</script>
'''


def install_canadabuys_profile_ui(app) -> None:
    if getattr(app.state, "intellcluster_canadabuys_profile_ui_installed", False):
        return
    app.state.intellcluster_canadabuys_profile_ui_installed = True

    @app.middleware("http")
    async def canadabuys_profile_ui(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if (
            response.status_code != 200
            or not path.startswith("/data/company/")
            or path.count("/") != 3
            or "text/html" not in response.headers.get("content-type", "")
        ):
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        if "</body>" not in text:
            return Response(content=body, status_code=response.status_code, headers=dict(response.headers), media_type="text/html")
        text = text.replace("</body>", _CANADABUYS_PROFILE_UI + "</body>")
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
