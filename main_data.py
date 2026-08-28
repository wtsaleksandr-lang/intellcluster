"""IntellCluster data application entrypoint.

The original data app and response polish live in ``main_data_core``.  This thin
layer mounts search-engine discovery endpoints and structured metadata without
coupling SEO work to ingestion or the core directory UI.
"""

from main_data_core import app
from intelligence.seo import install_seo_middleware, router as seo_router

app.include_router(seo_router)
install_seo_middleware(app)
