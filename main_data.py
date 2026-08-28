"""IntellCluster application entrypoint with the business-intelligence layer enabled.

This imports the existing application unchanged, then mounts the data API and
directory UI. A small response enhancer is kept here so company-profile polish can
be rolled out independently of the ingestion pipeline.
"""

from main import app
from intelligence.api import router as intelligence_api_router
from intelligence.hs import router as intelligence_hs_router
from intelligence.location_explorer import router as intelligence_location_router
from intelligence.origin_explorer import router as intelligence_origin_router
from intelligence.supplier_directory import router as intelligence_supplier_directory_router
from intelligence.supplier_explorer import router as intelligence_supplier_router
from intelligence.ui import router as intelligence_ui_router

app.include_router(intelligence_api_router)
app.include_router(intelligence_ui_router)
app.include_router(intelligence_hs_router)
app.include_router(intelligence_origin_router)
app.include_router(intelligence_location_router)
app.include_router(intelligence_supplier_router)
app.include_router(intelligence_supplier_directory_router)


_PROFILE_POLISH = r'''
<style id="intellcluster-profile-polish">
body[data-intell-profile] .profile-box,body[data-intell-profile] .metric,body[data-intell-profile] .panel,body[data-intell-profile] .trade-wrap{box-shadow:0 1px 2px rgba(0,0,0,.025)}
body[data-intell-profile] .profile-jump{box-shadow:0 7px 20px rgba(0,0,0,.035)}
body[data-intell-profile] .profile-jump a{position:relative;transition:color .15s ease}
body[data-intell-profile] .profile-jump a.ic-active{color:#202123!important;font-weight:750;border-bottom-color:#202123!important}
body[data-intell-profile] .profile-actions .small-btn{cursor:pointer;transition:background .15s,border-color .15s,box-shadow .15s,transform .15s}
body[data-intell-profile] .profile-actions .small-btn:hover{background:#f7f7f8;border-color:#b9b9be;box-shadow:0 4px 12px rgba(0,0,0,.055);transform:translateY(-1px)}
body[data-intell-profile] .source-line{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
body[data-intell-profile] .ic-source-badge{display:inline-flex;align-items:center;gap:5px;border:1px solid #dedee1;background:#f7f7f8;border-radius:999px;padding:4px 7px;color:#565861;font-size:8px;font-weight:700;letter-spacing:.15px}
body[data-intell-profile] .ic-source-dot{width:5px;height:5px;border-radius:50%;background:#343541}
body[data-intell-profile] .supplier-table tbody tr,body[data-intell-profile] .bol-table tbody tr,body[data-intell-profile] .lane-table tr{transition:background .12s ease}
body[data-intell-profile] .supplier-link,body[data-intell-profile] .country-link,body[data-intell-profile] .bol-link,body[data-intell-profile] .treemap-tile{transition:filter .12s ease,opacity .12s ease}
body[data-intell-profile] .supplier-link:hover,body[data-intell-profile] .country-link:hover,body[data-intell-profile] .bol-link:hover{opacity:.72}
body[data-intell-profile] .trade-kpi{transition:border-color .15s ease,box-shadow .15s ease,transform .15s ease}
body[data-intell-profile] .trade-kpi:hover{border-color:#bfc3c7;box-shadow:0 5px 15px rgba(0,0,0,.045);transform:translateY(-1px)}
body[data-intell-profile] .metric{transition:border-color .15s ease,box-shadow .15s ease}
body[data-intell-profile] .metric:hover{border-color:#c5c5c9;box-shadow:0 5px 16px rgba(0,0,0,.045)}
body[data-intell-profile] .ic-section-count{display:inline-flex;margin-left:6px;min-width:18px;height:18px;padding:0 6px;align-items:center;justify-content:center;border-radius:999px;background:#f0f0f1;color:#67676e;font-size:8px;font-weight:750;vertical-align:2px}
body[data-intell-profile] .ic-export-link{display:inline-flex;align-items:center;text-decoration:none}
body[data-intell-profile] .ic-capability-wrap{margin:14px 0 18px;border:1px solid #dce3e7;border-radius:7px;background:#fbfcfd;overflow:hidden}
body[data-intell-profile] .ic-capability-head{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 12px;border-bottom:1px solid #e5eaed;background:#fff;color:#5e6b73;font-size:9px}
body[data-intell-profile] .ic-capability-head strong{font-size:11px;color:#14242d;letter-spacing:-.01em}
body[data-intell-profile] .ic-market-label{display:inline-flex;align-items:center;gap:6px;font-weight:700;color:#29404c}
body[data-intell-profile] .ic-capability-strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:0}
body[data-intell-profile] .ic-capability{min-height:62px;padding:9px 10px;border-right:1px solid #e6ebee;border-bottom:1px solid #e6ebee;background:#fff}
body[data-intell-profile] .ic-capability:nth-child(6n){border-right:0}
body[data-intell-profile] .ic-capability-label{display:flex;align-items:center;gap:5px;color:#293942;font-size:9px;font-weight:700}
body[data-intell-profile] .ic-capability-dot{width:6px;height:6px;border-radius:50%;background:#aeb8be;flex:0 0 auto}
body[data-intell-profile] .ic-capability[data-state="available"] .ic-capability-dot,body[data-intell-profile] .ic-capability[data-state="cached"] .ic-capability-dot{background:#279a68}
body[data-intell-profile] .ic-capability[data-state="market_context"] .ic-capability-dot{background:#278eb9}
body[data-intell-profile] .ic-capability[data-state="unlockable"] .ic-capability-dot,body[data-intell-profile] .ic-capability[data-state="on_demand"] .ic-capability-dot{background:#bd8b23}
body[data-intell-profile] .ic-capability[data-state="not_available"] .ic-capability-dot{background:#c2c7ca}
body[data-intell-profile] .ic-capability-copy{margin-top:5px;color:#7a858b;font-size:7px;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* Premium search language: original, lightweight and inspired by modern logistics SaaS. */
body[data-intell-search]{font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;color:#14171a;font-feature-settings:"kern" 1,"tnum" 1;background:#fff}
body[data-intell-search] .page.wide{max-width:1220px}
body[data-intell-search] .subnav{border-bottom:1px solid #dce1e5;margin-bottom:16px;gap:28px}
body[data-intell-search] .subnav a{font-size:12px;letter-spacing:-.01em;color:#68747c;padding:13px 2px 12px}
body[data-intell-search] .subnav a.active{color:#101820;font-weight:700;border-bottom:2px solid #101820}
body[data-intell-search] .search-toolbar h1{font-size:21px!important;font-weight:650;letter-spacing:-.035em!important;color:#101820!important}
body[data-intell-search] .search-toolbar small{font-size:11px!important;color:#75818a!important;line-height:1.45}
body[data-intell-search] .filter-shell{border-color:#d9dfe3!important;border-radius:8px!important;box-shadow:0 2px 8px rgba(15,32,45,.035)!important;background:rgba(255,255,255,.985)!important}
body[data-intell-search] .filter-shell .filter,body[data-intell-search] .filter-shell .small-btn{min-height:38px;border-color:#d6dde2!important;border-radius:6px!important;font:500 11px/1.2 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important;color:#26323a}
body[data-intell-search] .filter-shell .filter:focus{outline:0;border-color:#3a91c4!important;box-shadow:0 0 0 3px rgba(39,150,204,.11)}
body[data-intell-search] .advanced-toggle{color:#0b5f87!important;font-weight:650!important}
body[data-intell-search] .result-meta{margin:14px 0 9px;color:#69767e;font-size:10px}
body[data-intell-search] .result-meta>span:first-child{font-variant-numeric:tabular-nums}
body[data-intell-search] .cards{gap:10px!important}
body[data-intell-search] .card{overflow:visible;border:1px solid #d7dfe4!important;border-radius:7px!important;background:#fff!important;box-shadow:0 1px 2px rgba(15,30,40,.025);transition:border-color .14s ease,box-shadow .14s ease,transform .14s ease!important}
body[data-intell-search] .card:hover{border-color:#aab9c3!important;box-shadow:0 7px 22px rgba(19,41,54,.075)!important;transform:translateY(-1px)!important}
body[data-intell-search] .card .card-accent{width:4px!important;background:#21a6d8!important;border-radius:7px 0 0 7px}
body[data-intell-search] .card.supplier .card-accent{background:#4b778a!important}
body[data-intell-search] .card-body{padding:15px 18px 14px!important}
body[data-intell-search] .card-title{display:inline-flex;align-items:center;flex-wrap:wrap;gap:6px;font-size:16px!important;font-weight:680!important;letter-spacing:-.025em!important;color:#0b66c3!important;line-height:1.2}
body[data-intell-search] .card-title:hover{color:#084d93!important;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}
body[data-intell-search] .badge{border:0!important;border-radius:4px!important;padding:3px 6px!important;font-size:8px!important;font-weight:750!important;letter-spacing:.015em;text-transform:none!important;background:#249fc5!important;color:#fff!important}
body[data-intell-search] .badge.dark{background:#346c7d!important}
body[data-intell-search] .badge.green{background:#68766e!important}
body[data-intell-search] .card-address{margin-top:7px!important;font-size:10px!important;color:#63717a!important;gap:6px!important}
body[data-intell-search] .ic-country-flag{display:inline-flex;align-items:center;font-size:15px;line-height:1;filter:saturate(.92);margin-right:1px;vertical-align:-1px}
body[data-intell-search] .source-pill{border:0!important;background:#f3f6f7!important;color:#68777f!important;border-radius:4px!important;padding:4px 6px!important;font-size:8px!important}
body[data-intell-search] .source-pill svg{stroke:#318db3!important}
body[data-intell-search] .stats-row{margin-top:12px!important;padding-top:11px!important;border-top:1px solid #edf0f2!important;gap:0!important}
body[data-intell-search] .mini-stat{padding:0 18px!important;margin:0!important;border-right:1px solid #dfe5e8!important;min-width:0}
body[data-intell-search] .mini-stat:first-child{padding-left:0!important}
body[data-intell-search] .mini-stat:last-child{border-right:0!important}
body[data-intell-search] .mini-label{display:flex;align-items:center;gap:5px;color:#7a8890!important;font-size:8px!important;font-weight:600!important;letter-spacing:.01em;margin-bottom:4px!important}
body[data-intell-search] .mini-value{font-size:11px!important;font-weight:650!important;color:#26343c!important;font-variant-numeric:tabular-nums}
body[data-intell-search] .score-dot.hot{background:#29a36a!important}
body[data-intell-search] .facet-row{padding-top:2px}
body[data-intell-search] .facet{min-height:25px!important;background:#f7f9fa!important;border-color:#dce3e7!important;border-radius:5px!important;color:#50616a!important;font-size:9px!important;font-weight:550}
body[data-intell-search] .facet:hover{background:#eef7fb!important;border-color:#90bfd4!important;color:#075b7e!important}
body[data-intell-search] .facet .ic-country-flag{font-size:14px;margin-right:1px}
body[data-intell-search] .ic-help{position:relative;display:inline-flex;align-items:center;justify-content:center;width:13px;height:13px;border-radius:50%;background:#1d94c1;color:#fff;font:750 9px/1 ui-sans-serif,sans-serif;cursor:help;outline:0;box-shadow:0 0 0 1px rgba(0,105,150,.08)}
body[data-intell-search] .ic-help::before{content:"";position:absolute;z-index:40;left:50%;bottom:calc(100% + 5px);width:9px;height:9px;background:#102a36;transform:translate(-50%,5px) rotate(45deg);opacity:0;pointer-events:none;transition:opacity .12s,transform .12s}
body[data-intell-search] .ic-help::after{content:attr(data-help);position:absolute;z-index:39;left:50%;bottom:calc(100% + 9px);width:240px;padding:9px 10px;border-radius:6px;background:#102a36;color:#fff;font:500 10px/1.45 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:0;box-shadow:0 8px 22px rgba(0,0,0,.18);opacity:0;pointer-events:none;transform:translate(-50%,5px);transition:opacity .12s,transform .12s;white-space:normal}
body[data-intell-search] .ic-help:hover::after,body[data-intell-search] .ic-help:hover::before,body[data-intell-search] .ic-help:focus::after,body[data-intell-search] .ic-help:focus::before{opacity:1;transform:translate(-50%,0) rotate(0)}
body[data-intell-search] .ic-help:hover::before,body[data-intell-search] .ic-help:focus::before{transform:translate(-50%,0) rotate(45deg)}
body[data-intell-search] .ic-coverage-help{display:inline-flex;align-items:center;gap:5px;color:#60717a;font-size:9px}
@media(max-width:900px){body[data-intell-profile] .ic-capability-strip{grid-template-columns:repeat(4,minmax(0,1fr))}body[data-intell-profile] .ic-capability:nth-child(6n){border-right:1px solid #e6ebee}body[data-intell-profile] .ic-capability:nth-child(4n){border-right:0}}
@media(max-width:700px){body[data-intell-search] .mini-stat{padding:0 8px!important;border-right:0!important}body[data-intell-search] .stats-row{gap:10px!important}body[data-intell-search] .ic-help::after{left:auto;right:-8px;transform:translateY(5px);width:210px}body[data-intell-search] .ic-help:hover::after,body[data-intell-search] .ic-help:focus::after{transform:translateY(0)}body[data-intell-profile] .ic-capability-strip{grid-template-columns:repeat(2,minmax(0,1fr))}body[data-intell-profile] .ic-capability:nth-child(4n){border-right:1px solid #e6ebee}body[data-intell-profile] .ic-capability:nth-child(2n){border-right:0}}
@media(max-width:600px){body[data-intell-profile] .profile-actions{width:100%}body[data-intell-profile] .profile-actions .small-btn,body[data-intell-profile] .ic-export-link{flex:1;justify-content:center}}
</style>
<script id="intellcluster-profile-enhancer">
(()=>{
  const profileMatch=location.pathname.match(/^\/data\/company\/([^/]+)\/?$/);
  const searchPage=location.pathname==='/data/search';
  if(!profileMatch&&!searchPage)return;

  const upgradeHs=(root=document)=>root.querySelectorAll('a[href^="/data/search?hs="]').forEach(a=>{
    try{const u=new URL(a.getAttribute('href'),location.origin);const code=(u.searchParams.get('hs')||'').replace(/\D/g,'').slice(0,10);if(code.length>=2){a.href=`/data/hs/${code}`;a.title=a.title||`Explore HS ${code}`;}}catch{}
  });
  const upgradeOrigins=(root=document)=>root.querySelectorAll('a[href*="/data/search?origin="]').forEach(a=>{
    try{const u=new URL(a.getAttribute('href'),location.origin);const country=(u.searchParams.get('origin')||'').trim();if(country){a.href=`/data/origin/${encodeURIComponent(country)}`;a.title=a.title||`Explore sourcing from ${country}`;}}catch{}
  });
  const upgradeLocations=(root=document)=>root.querySelectorAll('a.location-link[href^="/data/search?"]').forEach(a=>{
    try{const u=new URL(a.getAttribute('href'),location.origin);const province=(u.searchParams.get('province')||'').trim();const city=(u.searchParams.get('city')||'').trim();if(province){a.href=city?`/data/location/${encodeURIComponent(province)}/${encodeURIComponent(city)}`:`/data/location/${encodeURIComponent(province)}`;a.title=a.title||`Explore ${city?city+', ':''}${province}`;}}catch{}
  });

  upgradeHs();upgradeOrigins();upgradeLocations();
  if(searchPage){
    document.body.dataset.intellSearch='1';
    const countryCodes={'CA':'CA','Canada':'CA','United States':'US','USA':'US','U.S.':'US','China':'CN','Taiwan':'TW','Mexico':'MX','Germany':'DE','Japan':'JP','South Korea':'KR','Korea':'KR','India':'IN','Vietnam':'VN','Viet Nam':'VN','Italy':'IT','France':'FR','United Kingdom':'GB','UK':'GB','Spain':'ES','Netherlands':'NL','Belgium':'BE','Brazil':'BR','Thailand':'TH','Indonesia':'ID','Malaysia':'MY','Singapore':'SG','Turkey':'TR','Türkiye':'TR','Poland':'PL','Czech Republic':'CZ','Sweden':'SE','Denmark':'DK','Norway':'NO','Finland':'FI','Australia':'AU','New Zealand':'NZ','Hong Kong':'HK','Philippines':'PH','Bangladesh':'BD','Pakistan':'PK','Portugal':'PT','Austria':'AT','Switzerland':'CH','Romania':'RO','Hungary':'HU'};
    const flag=(label)=>{const code=countryCodes[String(label||'').trim()];return code?[...code].map(c=>String.fromCodePoint(127397+c.charCodeAt())).join(''):''};
    document.querySelectorAll('.card').forEach(card=>{
      const address=card.querySelector('.card-address');if(address){const nodes=[...address.querySelectorAll('span')];const countryNode=nodes.find(n=>countryCodes[(n.textContent||'').trim()]);if(countryNode&&!countryNode.querySelector('.ic-country-flag')){const f=document.createElement('span');f.className='ic-country-flag';f.textContent=flag(countryNode.textContent);f.setAttribute('aria-hidden','true');countryNode.prepend(f);}}
      card.querySelectorAll('a[href*="/data/origin/"]').forEach(a=>{const label=(a.textContent||'').trim();const f=flag(label);if(f&&!a.querySelector('.ic-country-flag')){a.querySelector('svg')?.remove();const span=document.createElement('span');span.className='ic-country-flag';span.textContent=f;span.setAttribute('aria-hidden','true');a.prepend(span);}});
      const helpText={'AI Buyer Score':'Internal ranking signal that helps prioritize potentially relevant buyers. It is a decision aid, not a credit or financial score.','HS Codes':'Number of distinct Harmonized System product codes connected to this company in the indexed public trade records.','Source Countries':'Number of distinct origin markets connected to this company in the indexed importer records.','Matched Sources':'Number of independent IntellCluster datasets currently linked to this canonical company profile.','Ocean Shipments':'Shipment records currently cached for this U.S. company from the trade-intelligence layer.','Suppliers':'Distinct supplier records currently available in the cached trade-intelligence response.','Fleet / Contracts':'A compact view of currently cached FMCSA fleet and USAspending federal-contract evidence.'};
      card.querySelectorAll('.mini-label').forEach(label=>{const key=(label.textContent||'').trim();const copy=helpText[key];if(!copy||label.querySelector('.ic-help'))return;const help=document.createElement('span');help.className='ic-help';help.tabIndex=0;help.textContent='?';help.dataset.help=copy;help.setAttribute('aria-label',`${key}: ${copy}`);label.appendChild(help);});
    });
    const meta=document.querySelector('.result-meta .hint');if(meta){meta.innerHTML='<span class="ic-coverage-help">Clickable intelligence facets <span class="ic-help" tabindex="0" data-help="HS codes, sourcing countries and locations open dedicated analytical drill-down pages instead of starting a new generic search.">?</span></span>';}
    return;
  }

  document.body.dataset.intellProfile='1';
  const slug=profileMatch[1];
  const actions=document.querySelector('.profile-actions');
  if(actions){[...actions.querySelectorAll('.small-btn')].forEach(btn=>{if(/export/i.test(btn.textContent||'')){const a=document.createElement('a');a.className='small-btn ic-export-link';a.href=`/data/company/${encodeURIComponent(slug)}/export.csv`;a.setAttribute('download','');a.innerHTML='⇩&nbsp; Export CSV';btn.replaceWith(a);}});}

  const supplierExplore=document.querySelector('#suppliers .data-action');if(supplierExplore){supplierExplore.href='/data/suppliers';supplierExplore.textContent='↗ Explore Suppliers';}
  document.querySelectorAll('a.supplier-link').forEach(a=>{const supplier=(a.textContent||'').trim();if(supplier&&supplier!=='—'){a.href=`/data/supplier/${encodeURIComponent(supplier)}`;a.title=`Open cached supplier intelligence for ${supplier}`;}});
  document.addEventListener('click',event=>{const node=event.target.closest?.('g.rel-node.supplier');if(!node)return;const supplier=(node.querySelector('text')?.textContent||'').replace(/…$/,'').trim();if(!supplier)return;event.preventDefault();event.stopImmediatePropagation();location.href=`/data/supplier/${encodeURIComponent(supplier)}`;},true);

  const source=document.querySelector('.source-line');
  const metrics=document.querySelector('.metric-grid');
  fetch(`/api/intelligence/company/${encodeURIComponent(slug)}`).then(r=>r.ok?r.json():null).then(payload=>{
    if(!payload)return;
    const company=payload.company||{};const caps=payload.capabilities||{};const market=caps.country||{};const sections=caps.sections||{};
    if(source){source.textContent='Evidence sources:';const add=(label)=>{const b=document.createElement('span');b.className='ic-source-badge';b.innerHTML=`<i class="ic-source-dot"></i>${label}`;source.appendChild(b)};add(`${market.flag||''} ${market.primary_registry||market.name||company.country||'Public records'}`.trim());if(company.importyeti)add('ImportYeti shipment intelligence');if(company.enrichment?.usaspending)add('USAspending.gov');if(company.enrichment?.fmcsa)add('FMCSA Company Census');if(company.source_records_count)add(`${company.source_records_count} matched records`);}
    if(metrics&&!document.querySelector('.ic-capability-wrap')){const order=caps.section_order||Object.keys(sections);const wrap=document.createElement('section');wrap.className='ic-capability-wrap';const head=document.createElement('div');head.className='ic-capability-head';head.innerHTML=`<strong>Intelligence Coverage</strong><span class="ic-market-label">${market.flag||''} ${market.name||company.country||''}</span>`;const strip=document.createElement('div');strip.className='ic-capability-strip';order.forEach(key=>{const s=sections[key];if(!s)return;const item=document.createElement('div');item.className='ic-capability';item.dataset.state=s.status||'pending';item.title=s.message||s.source||'';const copy=s.status==='cached'?'Cached':s.status==='market_context'?'Market context':s.status==='unlockable'?'Unlockable':s.status==='on_demand'?'On demand':s.status==='not_available'?'Not available':s.status==='available'?'Available':'Planned';item.innerHTML=`<div class="ic-capability-label"><i class="ic-capability-dot"></i>${s.label||key}</div><div class="ic-capability-copy">${copy}${s.source?' · '+s.source:''}</div>`;strip.appendChild(item);});wrap.append(head,strip);metrics.insertAdjacentElement('afterend',wrap);}
  }).catch(()=>{});

  const supplierTitle=document.querySelector('#suppliers h2');const supplierRows=document.querySelectorAll('#supplierTable tbody tr').length;if(supplierTitle&&supplierRows){const s=document.createElement('span');s.className='ic-section-count';s.textContent=supplierRows;s.title='suppliers shown';supplierTitle.appendChild(s)}
  const bolTitle=document.querySelector('#recent-bols h2');const bolRows=document.querySelectorAll('#bolTable tbody tr').length;if(bolTitle&&bolRows){const s=document.createElement('span');s.className='ic-section-count';s.textContent=bolRows;s.title='recent shipments shown';bolTitle.appendChild(s)}
  const links=[...document.querySelectorAll('.profile-jump a[href^="#"]')];const sections=links.map(a=>document.querySelector(a.getAttribute('href'))).filter(Boolean);if('IntersectionObserver' in window&&sections.length){const obs=new IntersectionObserver(entries=>{const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];if(!visible)return;links.forEach(a=>a.classList.toggle('ic-active',a.getAttribute('href')===`#${visible.target.id}`));},{rootMargin:'-70px 0px -62% 0px',threshold:[0,.15,.4,.7]});sections.forEach(s=>obs.observe(s));}
  document.addEventListener('keydown',e=>{if(e.key==='/'&&!/input|textarea|select/i.test(document.activeElement?.tagName||'')){e.preventDefault();document.querySelector('.nav-search input')?.focus()}if(e.key==='Escape'){const f=document.getElementById('supplierFilter');if(f&&f===document.activeElement){f.value='';f.dispatchEvent(new Event('input'));f.blur()}}});
})();
</script>
'''


@app.middleware("http")
async def enhance_intelligence_company_profiles(request, call_next):
    """Inject UI polish and keep the cached supplier index synchronized."""
    response = await call_next(request)
    path = request.url.path
    profile_match = path.startswith("/data/company/") and path.count("/") == 3

    if profile_match and response.status_code == 200:
        slug = path.rsplit("/", 1)[-1]
        try:
            from intelligence.database import connect
            from intelligence.repository import get_entity_by_slug
            from intelligence.supplier_explorer import sync_supplier_relationships

            with connect() as conn:
                company = get_entity_by_slug(conn, slug)
                profile = company.get("importyeti") if company and isinstance(company.get("importyeti"), dict) else None
                if company and profile:
                    sync_supplier_relationships(conn, int(company["id"]), profile)
        except Exception:
            pass

    should_enhance = profile_match or path == "/data/search"
    if not should_enhance:
        return response
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        return response
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode("utf-8")
    text = text.replace("</body>", _PROFILE_POLISH + "</body>")
    headers = dict(response.headers)
    headers.pop("content-length", None)
    from starlette.responses import Response
    return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
