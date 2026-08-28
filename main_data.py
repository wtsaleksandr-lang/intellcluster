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
from intelligence.supplier_explorer import router as intelligence_supplier_router
from intelligence.ui import router as intelligence_ui_router

app.include_router(intelligence_api_router)
app.include_router(intelligence_ui_router)
app.include_router(intelligence_hs_router)
app.include_router(intelligence_origin_router)
app.include_router(intelligence_location_router)
app.include_router(intelligence_supplier_router)


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
@media(max-width:600px){body[data-intell-profile] .profile-actions{width:100%}body[data-intell-profile] .profile-actions .small-btn,body[data-intell-profile] .ic-export-link{flex:1;justify-content:center}}
</style>
<script id="intellcluster-profile-enhancer">
(()=>{
  const profileMatch=location.pathname.match(/^\/data\/company\/([^/]+)\/?$/);
  const searchPage=location.pathname==='/data/search';
  if(!profileMatch&&!searchPage)return;

  const upgradeHs=(root=document)=>root.querySelectorAll('a[href^="/data/search?hs="]').forEach(a=>{
    try{
      const u=new URL(a.getAttribute('href'),location.origin);
      const code=(u.searchParams.get('hs')||'').replace(/\D/g,'').slice(0,10);
      if(code.length>=2){a.href=`/data/hs/${code}`;a.title=a.title||`Explore HS ${code}`;}
    }catch{}
  });
  const upgradeOrigins=(root=document)=>root.querySelectorAll('a[href*="/data/search?origin="]').forEach(a=>{
    try{
      const u=new URL(a.getAttribute('href'),location.origin);
      const country=(u.searchParams.get('origin')||'').trim();
      if(country){a.href=`/data/origin/${encodeURIComponent(country)}`;a.title=a.title||`Explore sourcing from ${country}`;}
    }catch{}
  });
  const upgradeLocations=(root=document)=>root.querySelectorAll('a.location-link[href^="/data/search?"]').forEach(a=>{
    try{
      const u=new URL(a.getAttribute('href'),location.origin);
      const province=(u.searchParams.get('province')||'').trim();
      const city=(u.searchParams.get('city')||'').trim();
      if(province){a.href=city?`/data/location/${encodeURIComponent(province)}/${encodeURIComponent(city)}`:`/data/location/${encodeURIComponent(province)}`;a.title=a.title||`Explore ${city?city+', ':''}${province}`;}
    }catch{}
  });

  upgradeHs();upgradeOrigins();upgradeLocations();
  if(searchPage)return;

  document.body.dataset.intellProfile='1';
  const slug=profileMatch[1];

  const actions=document.querySelector('.profile-actions');
  if(actions){
    [...actions.querySelectorAll('.small-btn')].forEach(btn=>{
      if(/export/i.test(btn.textContent||'')){
        const a=document.createElement('a');
        a.className='small-btn ic-export-link';
        a.href=`/data/company/${encodeURIComponent(slug)}/export.csv`;
        a.setAttribute('download','');
        a.innerHTML='⇩&nbsp; Export CSV';
        btn.replaceWith(a);
      }
    });
  }

  document.querySelectorAll('a.supplier-link').forEach(a=>{
    const supplier=(a.textContent||'').trim();
    if(supplier&&supplier!=='—'){a.href=`/data/supplier/${encodeURIComponent(supplier)}`;a.title=`Open cached supplier intelligence for ${supplier}`;}
  });
  document.addEventListener('click',event=>{
    const node=event.target.closest?.('g.rel-node.supplier');
    if(!node)return;
    const supplier=(node.querySelector('text')?.textContent||'').replace(/…$/,'').trim();
    if(!supplier)return;
    event.preventDefault();event.stopImmediatePropagation();
    location.href=`/data/supplier/${encodeURIComponent(supplier)}`;
  },true);

  const source=document.querySelector('.source-line');
  if(source){
    const hasIy=!!document.getElementById('iy-profile');
    source.textContent='Evidence sources:';
    const add=(label)=>{const b=document.createElement('span');b.className='ic-source-badge';b.innerHTML=`<i class="ic-source-dot"></i>${label}`;source.appendChild(b)};
    add('Canadian public datasets');
    if(hasIy)add('ImportYeti shipment intelligence');
    const records=[...document.querySelectorAll('.metric')].find(x=>/source records/i.test(x.textContent||''))?.querySelector('.metric-value')?.textContent?.trim();
    if(records)add(`${records} matched records`);
  }

  const supplierTitle=document.querySelector('#suppliers h2');
  const supplierRows=document.querySelectorAll('#supplierTable tbody tr').length;
  if(supplierTitle&&supplierRows){const s=document.createElement('span');s.className='ic-section-count';s.textContent=supplierRows;s.title='suppliers shown';supplierTitle.appendChild(s)}
  const bolTitle=document.querySelector('#recent-bols h2');
  const bolRows=document.querySelectorAll('#bolTable tbody tr').length;
  if(bolTitle&&bolRows){const s=document.createElement('span');s.className='ic-section-count';s.textContent=bolRows;s.title='recent shipments shown';bolTitle.appendChild(s)}

  const links=[...document.querySelectorAll('.profile-jump a[href^="#"]')];
  const sections=links.map(a=>document.querySelector(a.getAttribute('href'))).filter(Boolean);
  if('IntersectionObserver' in window&&sections.length){
    const obs=new IntersectionObserver(entries=>{
      const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];
      if(!visible)return;
      links.forEach(a=>a.classList.toggle('ic-active',a.getAttribute('href')===`#${visible.target.id}`));
    },{rootMargin:'-70px 0px -62% 0px',threshold:[0,.15,.4,.7]});
    sections.forEach(s=>obs.observe(s));
  }

  document.addEventListener('keydown',e=>{
    if(e.key==='/'&&!/input|textarea|select/i.test(document.activeElement?.tagName||'')){e.preventDefault();document.querySelector('.nav-search input')?.focus()}
    if(e.key==='Escape'){const f=document.getElementById('supplierFilter');if(f&&f===document.activeElement){f.value='';f.dispatchEvent(new Event('input'));f.blur()}}
  });
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
            # Supplier indexing is a derived-cache optimization and must never
            # make a company profile unavailable if indexing encounters bad data.
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
