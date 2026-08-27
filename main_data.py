"""IntellCluster application entrypoint with the business-intelligence layer enabled.

This imports the existing application unchanged, then mounts the new data API and
minimalist directory UI. Keeping this as a thin entrypoint makes the rollout
reversible while the intelligence product is still being built.
"""

from main import app
from intelligence.api import router as intelligence_api_router
from intelligence.ui import router as intelligence_ui_router

app.include_router(intelligence_api_router)
app.include_router(intelligence_ui_router)
