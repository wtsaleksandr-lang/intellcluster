"""IntellCluster data application entrypoint.

The original data app and response polish live in ``main_data_core``. This thin
layer mounts discovery-focused directory routes and structured metadata without
coupling SEO work to ingestion or the core directory UI.
"""

from main_data_core import app
from intelligence.company_directory import router as company_directory_router
from intelligence.compliance_export import router as compliance_export_router
from intelligence.seo import install_seo_middleware, router as seo_router

app.include_router(company_directory_router)
app.include_router(compliance_export_router)
app.include_router(seo_router)
install_seo_middleware(app)
