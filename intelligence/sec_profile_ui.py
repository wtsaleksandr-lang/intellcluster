from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response


_SEC_PROFILE_UI = r'''
<style id="intellcluster-sec-profile-style">
body[data-intell-profile] .ic-sec{margin:18px 0;border:1px solid #d9e0e4;border-radius:8px;background:#fff;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.025)}
body[data-intell-profile] .ic-sec-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:13px 15px;background:#f8fafb;border-bottom:1px solid #e1e6e9}
body[data-intell-profile] .ic-sec-kicker{font-size:7px;font-weight:800;letter-spacing:.65px;text-transform:uppercase;color:#5f6f78}
body[data-intell-profile] .ic-sec-head h2{margin:4px 0 0;font-size:15px;color:#1f343e}
body[data-intell-profile] .ic-sec-head p{margin:4px 0 0;color:#79878e;font-size:8px;line-height:1.45}
body[data-intell-profile] .ic-sec-head-actions{display:flex;align-items:center;justify-content:flex-end;gap:6px;flex-wrap:wrap}
body[data-intell-profile] .ic-sec-source{display:inline-flex;align-items:center;gap:5px;border:1px solid #d8e0e4;border-radius:999px;background:#fff;padding:4px 7px;color:#596a72;font-size:7px;font-weight:750;white-space:nowrap}
body[data-intell-profile] .ic-sec-source i{width:5px;height:5px;border-radius:50%;background:#557b91}
body[data-intell-profile] .ic-sec-export,body[data-intell-profile] .ic-sec-refresh{display:inline-flex;align-items:center;border:1px solid #ccd8de;border-radius:5px;background:#fff;padding:5px 7px;color:#365b6c;font-size:7px;font-weight:750;white-space:nowrap;cursor:pointer;font-family:inherit}
body[data-intell-profile] .ic-sec-export:hover,body[data-intell-profile] .ic-sec-refresh:hover{background:#f1f6f8;border-color:#aebfc7}
body[data-intell-profile] .ic-sec-refresh:disabled{opacity:.55;cursor:wait}
body[data-intell-profile] .ic-sec-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:8px;padding:12px 14px}
body[data-intell-profile] .ic-sec-kpi{border:1px solid #e0e5e8;border-radius:6px;padding:9px 10px;background:#fff;min-height:70px}
body[data-intell-profile] .ic-sec-kpi.financial{border-top:3px solid #6d8794;background:#fbfcfd}
body[data-intell-profile] .ic-sec-kpi small{display:block;color:#7d898f;font-size:7px;text-transform:uppercase;letter-spacing:.35px}
body[data-intell-profile] .ic-sec-kpi strong{display:block;color:#243c47;font-size:15px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body[data-intell-profile] .ic-sec-kpi span{display:block;color:#909a9f;font-size:7px;margin-top:3px;line-height:1.3}
body[data-intell-profile] .ic-sec-fin-note{margin:-3px 14px 12px;color:#87949a;font-size:7px;line-height:1.45}
body[data-intell-profile] .ic-sec-table-wrap{margin:0 14px 13px;max-height:330px;overflow:auto;border:1px solid #e0e5e8;border-radius:6px}
body[data-intell-profile] .ic-sec-table{width:100%;border-collapse:collapse;font-size:8px}
body[data-intell-profile] .ic-sec-table th{position:sticky;top:0;background:#f3f6f7;color:#6f7e85;text-align:left;font-size:7px;padding:7px 8px;border-bottom:1px solid #dfe5e8}
body[data-intell-profile] .ic-sec-table td{padding:8px;border-bottom:1px solid #edf0f2;color:#40545d;vertical-align:top}
body[data-intell-profile] .ic-sec-table tbody tr:nth-child(even){background:#fbfcfc}
body[data-intell-profile] .ic-sec-table tbody tr:hover{background:#f2f7f9}
body[data-intell-profile] .ic-sec-table tr:last-child td{border-bottom:0}
body[data-intell-profile] .ic-sec-link{color:#075f88;font-weight:750}
body[data-intell-profile] .ic-sec-empty{display:flex;align-items:center;justify-content:space-between;gap:14px;margin:13px 14px;padding:13px;border:1px dashed #bccbd2;border-radius:6px;background:#f9fbfc;color:#697b84;font-size:8px;line-height:1.5}
body[data-intell-profile] .ic-sec-empty strong{display:block;color:#334e5a;font-size:9px;margin-bottom:2px}
body[data-intell-profile] .ic-sec-empty small{display:block;margin-top:4px;color:#8b989e;font-size:7px}
body[data-intell-profile] .ic-sec-empty button{border:1px solid #355f73;background:#355f73;color:#fff;border-radius:5px;padding:8px 10px;font-size:8px;font-weight:750;cursor:pointer;white-space:nowrap}
body[data-intell-profile] .ic-sec-empty button:hover{background:#264c5e}
body[data-intell-profile] .ic-sec-empty button:disabled{opacity:.6;cursor:wait}
body[data-intell-profile] .ic-sec-note{padding:8px 14px;border-top:1px solid #e7ebed;background:#fcfcfd;color:#858f94;font-size:7px;line-height:1.45}
@media(max-width:600px){body[data-intell-profile] .ic-sec-head{flex-direction:column}body[data-intell-profile] .ic-sec-head-actions{justify-content:flex-start}body[data-intell-profile] .ic-sec-empty{align-items:flex-start;flex-direction:column}}
</style>
<script id="intellcluster-sec-profile-ui">
(() => {
  const match=location.pathname.match(/^\/data\/company\/([^/]+)\/?$/);if(!match)return;
  const slug=match[1];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const compactMoney=v=>{const n=Number(v);if(!Number.isFinite(n))return '—';const a=Math.abs(n),sign=n<0?'-':'';if(a>=1e12)return `${sign}$${(a/1e12).toFixed(1)}T`;if(a>=1e9)return `${sign}$${(a/1e9).toFixed(1)}B`;if(a>=1e6)return `${sign}$${(a/1e6).toFixed(1)}M`;if(a>=1e3)return `${sign}$${(a/1e3).toFixed(0)}K`;return `${sign}$${a.toLocaleString()}`};
  const factMeta=f=>[f?.form,f?.period_end].filter(Boolean).join(' · ')||'latest standardized fact';
  const addSourceBadge=()=>{const source=document.querySelector('.source-line');if(!source||[...source.querySelectorAll('.ic-source-badge')].some(x=>/SEC EDGAR/i.test(x.textContent||'')))return;const badge=document.createElement('span');badge.className='ic-source-badge';badge.innerHTML='<i class="ic-source-dot"></i>SEC EDGAR';source.appendChild(badge);};
  const statusCopy=status=>status==='no_confident_match'?'No confident ticker-associated SEC match found on the last check.':status==='ambiguous'?'Multiple possible SEC matches were found, so IntellCluster did not save an automatic entity link.':status==='unavailable'?'SEC EDGAR was temporarily unavailable on the last check.':'SEC filing evidence has not been cached for this profile.';
  const runLookup=async(button,refresh=false)=>{button.disabled=true;const original=button.textContent;button.textContent=refresh?'Refreshing SEC…':'Checking SEC…';try{const suffix=refresh?'?refresh=1':'';const response=await fetch(`/api/intelligence/company/${encodeURIComponent(slug)}/enrich/sec-edgar${suffix}`,{method:'POST'});const payload=await response.json();if(!response.ok)throw new Error(payload.detail||'SEC lookup failed');mount(payload.company||{});}catch(error){button.disabled=false;button.textContent=original||'Try Again';const strong=document.querySelector('#sec-edgar-intelligence .ic-sec-empty strong');if(strong)strong.textContent=error.message||'SEC lookup could not complete.';}};
  const mount=(company)=>{
    if(String(company?.country||'').toUpperCase()!=='US')return;
    document.getElementById('sec-edgar-intelligence')?.remove();
    const enrichment=company?.enrichment||{},edgar=enrichment.sec_edgar||null,lookup=enrichment.sec_edgar_lookup||null;
    const checked=lookup?.checked_at?String(lookup.checked_at).slice(0,10):'';
    const actions=edgar?`<div class="ic-sec-head-actions"><span class="ic-sec-source"><i></i> SEC EDGAR cached${checked?' · '+esc(checked):''}</span><button class="ic-sec-refresh" type="button" data-sec-refresh>↻ Refresh SEC</button><a class="ic-sec-export" href="/data/company/${encodeURIComponent(slug)}/sec-edgar.csv" download>⇩ Export SEC CSV</a></div>`:'';
    const section=document.createElement('section');section.id='sec-edgar-intelligence';section.className='ic-sec profile-anchor';
    section.innerHTML=`<div class="ic-sec-head"><div><div class="ic-sec-kicker">U.S. PUBLIC FILINGS</div><h2>SEC EDGAR Intelligence</h2><p>Public filing and standardized XBRL financial evidence cached from SEC EDGAR. Normal profile views never call the SEC network.</p></div>${actions}</div>`;
    if(edgar){
      const tickers=(edgar.tickers||[]).join(' · ')||edgar.ticker||'—';
      const exchanges=(edgar.exchanges||[]).join(' · ')||edgar.exchange||'—';
      const financials=edgar.financials||{};
      const grid=document.createElement('div');grid.className='ic-sec-grid';
      grid.innerHTML=`<div class="ic-sec-kpi"><small>CIK</small><strong>${esc(edgar.cik||'—')}</strong><span>SEC filer identifier</span></div><div class="ic-sec-kpi"><small>Ticker</small><strong>${esc(tickers)}</strong><span>${esc(exchanges)}</span></div><div class="ic-sec-kpi"><small>Latest Filing</small><strong>${esc(edgar.latest_filing_form||'—')}</strong><span>${esc(edgar.latest_filing_date||'No cached date')}</span></div><div class="ic-sec-kpi"><small>Filings Shown</small><strong>${esc(edgar.filing_count_shown??0)}</strong><span>recent cached EDGAR rows</span></div><div class="ic-sec-kpi"><small>SIC</small><strong>${esc(edgar.sic||'—')}</strong><span>${esc(edgar.sic_description||'Industry code')}</span></div>`;
      const financialDefs=[['revenue','Latest Revenue'],['net_income','Latest Net Income'],['assets','Assets'],['liabilities','Liabilities'],['cash','Cash']];financialDefs.forEach(([key,label])=>{const fact=financials[key];if(!fact)return;const card=document.createElement('div');card.className='ic-sec-kpi financial';card.innerHTML=`<small>${esc(label)}</small><strong>${fact.unit==='USD'?compactMoney(fact.value):esc(fact.value)}</strong><span>${esc(factMeta(fact))}</span>`;grid.appendChild(card)});section.appendChild(grid);
      if(Object.keys(financials).length){const note=document.createElement('div');note.className='ic-sec-fin-note';note.textContent='Financial values are the latest standardized SEC XBRL fact found for each concept. Periods can be quarterly, annual or year-to-date; compare the form and period before drawing trend conclusions.';section.appendChild(note);}
      if(Array.isArray(edgar.recent_filings)&&edgar.recent_filings.length){const wrap=document.createElement('div');wrap.className='ic-sec-table-wrap';const rows=edgar.recent_filings.slice(0,20).map(f=>`<tr><td>${esc(f.filingDate||'—')}</td><td><strong>${esc(f.form||'—')}</strong></td><td>${esc(f.reportDate||'—')}</td><td>${esc(f.primaryDocDescription||f.primaryDocument||'—')}</td><td>${f.filing_url?`<a class="ic-sec-link" href="${esc(f.filing_url)}" target="_blank" rel="noopener nofollow">Open filing ↗</a>`:'—'}</td></tr>`).join('');wrap.innerHTML=`<table class="ic-sec-table"><thead><tr><th>Filed</th><th>Form</th><th>Report Date</th><th>Document</th><th>SEC Record</th></tr></thead><tbody>${rows}</tbody></table>`;section.appendChild(wrap);}
      const refreshButton=section.querySelector('[data-sec-refresh]');if(refreshButton)refreshButton.addEventListener('click',()=>runLookup(refreshButton,true));
      addSourceBadge();
    }else{
      const empty=document.createElement('div');empty.className='ic-sec-empty';const status=String(lookup?.status||'');empty.innerHTML=`<div><strong>${esc(statusCopy(status))}</strong>The free check uses SEC ticker/CIK associations, submissions and standardized company facts. A missing match does not prove the company has no SEC filings.${checked?`<small>Last checked ${esc(checked)} · result: ${esc(status.replaceAll('_',' '))}</small>`:''}</div><button type="button">${lookup?'Recheck SEC EDGAR':'Check SEC EDGAR'}</button>`;const button=empty.querySelector('button');button.addEventListener('click',()=>runLookup(button,Boolean(lookup)));section.appendChild(empty);
    }
    const note=document.createElement('div');note.className='ic-sec-note';note.textContent='SEC ticker associations do not cover every EDGAR filer. Filings and XBRL facts are public regulatory evidence, not a statement that the entity is headquartered in the United States or that the canonical company match is legally dispositive.';section.appendChild(note);
    const place=()=>{const us=document.getElementById('us-public-intelligence');const compliance=document.getElementById('us-compliance-intelligence');const capabilities=document.querySelector('.ic-capability-wrap');if(us){us.insertAdjacentElement('afterend',section);}else if(compliance){compliance.insertAdjacentElement('beforebegin',section);}else if(capabilities){capabilities.insertAdjacentElement('afterend',section);}else{document.querySelector('.profile-box')?.insertAdjacentElement('afterend',section);}};
    setTimeout(place,60);
  };
  fetch(`/api/intelligence/company/${encodeURIComponent(slug)}`).then(r=>r.ok?r.json():null).then(payload=>{if(payload?.company)mount(payload.company)}).catch(()=>{});
})();
</script>
'''


def install_sec_profile_ui(app) -> None:
    if getattr(app.state, "intellcluster_sec_profile_ui_installed", False):
        return
    app.state.intellcluster_sec_profile_ui_installed = True

    @app.middleware("http")
    async def sec_profile_ui(request: Request, call_next):
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
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="text/html",
            )
        text = text.replace("</body>", _SEC_PROFILE_UI + "</body>")
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=text,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
