from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

_USPTO_PROFILE_UI = r'''
<style id="intellcluster-uspto-profile-style">
body[data-intell-profile] .ic-uspto{margin:18px 0;border:1px solid #d9e0e4;border-radius:8px;background:#fff;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.025)}
body[data-intell-profile] .ic-uspto-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:13px 15px;background:#f8fafb;border-bottom:1px solid #e1e6e9}
body[data-intell-profile] .ic-uspto-kicker{font-size:7px;font-weight:800;letter-spacing:.65px;text-transform:uppercase;color:#5f6f78}
body[data-intell-profile] .ic-uspto-head h2{margin:4px 0 0;font-size:15px;color:#1f343e}
body[data-intell-profile] .ic-uspto-head p{margin:4px 0 0;color:#79878e;font-size:8px;line-height:1.45;max-width:680px}
body[data-intell-profile] .ic-uspto-actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
body[data-intell-profile] .ic-uspto-source,body[data-intell-profile] .ic-uspto-export{display:inline-flex;align-items:center;border:1px solid #d8e0e4;border-radius:999px;background:#fff;padding:4px 7px;color:#596a72;font-size:7px;font-weight:750;white-space:nowrap}
body[data-intell-profile] .ic-uspto-export{border-radius:5px;color:#365b6c}
body[data-intell-profile] .ic-uspto-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;padding:12px 14px}
body[data-intell-profile] .ic-uspto-kpi{border:1px solid #e0e5e8;border-radius:6px;padding:9px 10px;background:#fff;min-height:68px}
body[data-intell-profile] .ic-uspto-kpi small{display:block;color:#7d898f;font-size:7px;text-transform:uppercase;letter-spacing:.35px}
body[data-intell-profile] .ic-uspto-kpi strong{display:block;color:#243c47;font-size:15px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body[data-intell-profile] .ic-uspto-kpi span{display:block;color:#909a9f;font-size:7px;margin-top:3px;line-height:1.3}
body[data-intell-profile] .ic-uspto-table-wrap{margin:0 14px 13px;max-height:320px;overflow:auto;border:1px solid #e0e5e8;border-radius:6px}
body[data-intell-profile] .ic-uspto-table{width:100%;border-collapse:collapse;font-size:8px}
body[data-intell-profile] .ic-uspto-table th{position:sticky;top:0;background:#f3f6f7;color:#6f7e85;text-align:left;font-size:7px;padding:7px 8px;border-bottom:1px solid #dfe5e8}
body[data-intell-profile] .ic-uspto-table td{padding:8px;border-bottom:1px solid #edf0f2;color:#40545d;vertical-align:top}
body[data-intell-profile] .ic-uspto-table tbody tr:nth-child(even){background:#fbfcfc}
body[data-intell-profile] .ic-uspto-note{padding:8px 14px;border-top:1px solid #e7ebed;background:#fcfcfd;color:#858f94;font-size:7px;line-height:1.45}
@media(max-width:600px){body[data-intell-profile] .ic-uspto-head{flex-direction:column}body[data-intell-profile] .ic-uspto-actions{justify-content:flex-start}}
</style>
<script id="intellcluster-uspto-profile-ui">
(() => {
  const match=location.pathname.match(/^\/data\/company\/([^/]+)\/?$/);if(!match)return;
  const slug=match[1];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const mount=company=>{
    const data=company?.enrichment?.uspto_patents;if(!data||typeof data!=='object')return;
    document.getElementById('uspto-patent-intelligence')?.remove();
    const section=document.createElement('section');section.id='uspto-patent-intelligence';section.className='ic-uspto profile-anchor';
    const cached=data._cachedAt?String(data._cachedAt).slice(0,10):'';
    section.innerHTML=`<div class="ic-uspto-head"><div><div class="ic-uspto-kicker">INTELLECTUAL PROPERTY</div><h2>USPTO Patent Intelligence</h2><p>Granted-patent evidence matched from the official USPTO PatentsView annualized bulk dataset. Profile views use only the stored cache and make no USPTO network request.</p></div><div class="ic-uspto-actions"><span class="ic-uspto-source">USPTO PatentsView${cached?' · '+esc(cached):''}</span><a class="ic-uspto-export" href="/data/company/${encodeURIComponent(slug)}/uspto-patents.csv" download>⇩ Export patent CSV</a></div></div>`;
    const tech=(data.technology_sections||[]).slice(0,4).map(x=>`${esc(x.code)} · ${esc(x.count)}`).join(' &nbsp; ')||'—';
    const grid=document.createElement('div');grid.className='ic-uspto-grid';grid.innerHTML=`<div class="ic-uspto-kpi"><small>Granted Patents</small><strong>${Number(data.total_patents||0).toLocaleString()}</strong><span>matched cached grants</span></div><div class="ic-uspto-kpi"><small>Latest Grant</small><strong>${esc(data.latest_grant_date||'—')}</strong><span>latest date in cached snapshot</span></div><div class="ic-uspto-kpi"><small>Matched Assignee</small><strong>${esc(data.matched_assignee||'—')}</strong><span>conservative canonical-name match</span></div><div class="ic-uspto-kpi"><small>Technology Sections</small><strong>${(data.technology_sections||[]).length||0}</strong><span>${tech}</span></div>`;section.appendChild(grid);
    const rows=Array.isArray(data.patents)?data.patents.slice(0,25):[];
    if(rows.length){const wrap=document.createElement('div');wrap.className='ic-uspto-table-wrap';wrap.innerHTML=`<table class="ic-uspto-table"><thead><tr><th>Grant Date</th><th>Patent</th><th>Title</th><th>CPC</th></tr></thead><tbody>${rows.map(p=>`<tr><td>${esc(p.grant_date||'—')}</td><td><strong>${esc(p.patent_id||'—')}</strong></td><td>${esc(p.title||'—')}</td><td>${esc(p.cpc_section||'—')}</td></tr>`).join('')}</tbody></table>`;section.appendChild(wrap);}
    const note=document.createElement('div');note.className='ic-uspto-note';note.textContent='PatentsView is research-grade USPTO data and does not constitute the official patent record. Company linkage is conservative assignee-name/location matching and should be treated as evidence, not a legal ownership determination.';section.appendChild(note);
    const sec=document.getElementById('sec-edgar-intelligence');const compliance=document.getElementById('us-compliance-intelligence');const caps=document.querySelector('.ic-capability-wrap');if(sec)sec.insertAdjacentElement('afterend',section);else if(compliance)compliance.insertAdjacentElement('beforebegin',section);else if(caps)caps.insertAdjacentElement('afterend',section);else document.querySelector('.profile-box')?.insertAdjacentElement('afterend',section);
    const source=document.querySelector('.source-line');if(source&&![...source.querySelectorAll('.ic-source-badge')].some(x=>/USPTO/i.test(x.textContent||''))){const badge=document.createElement('span');badge.className='ic-source-badge';badge.innerHTML='<i class="ic-source-dot"></i>USPTO PatentsView';source.appendChild(badge);}
  };
  fetch(`/api/intelligence/company/${encodeURIComponent(slug)}`).then(r=>r.ok?r.json():null).then(payload=>{if(payload?.company)mount(payload.company)}).catch(()=>{});
})();
</script>
'''


def install_uspto_profile_ui(app) -> None:
    if getattr(app.state, "intellcluster_uspto_profile_ui_installed", False):
        return
    app.state.intellcluster_uspto_profile_ui_installed = True

    @app.middleware("http")
    async def uspto_profile_ui(request: Request, call_next):
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
        text = text.replace("</body>", _USPTO_PROFILE_UI + "</body>")
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
