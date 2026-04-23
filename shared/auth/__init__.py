"""Magic-link authentication — passwordless, email-based.

Public surface:
    current_user(request)   → user dict or None
    require_user(request)   → user dict or raises 401
    user_router             → APIRouter with /login, /auth/*, /account
    upsert_user(email)      → create-or-update the user ledger row
"""

from .magic import current_user, require_user
from .routes import user_router
from .users import upsert_user, get_user, list_users, update_user_plan

__all__ = [
    "current_user",
    "require_user",
    "user_router",
    "upsert_user",
    "get_user",
    "list_users",
    "update_user_plan",
]
