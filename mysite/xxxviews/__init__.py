# ── Main views (previously in views.py) ──────────────────────────────
from .main import (
    ClientPageView,
    set_theme,
)

# ── Customer views ────────────────────────────────────────────────────

from .customer import (
    client_login,
    client_signup,
    client_logout,
    customer_onboarding,
    customer_profile,
    customer_addresses,
    add_address,
    set_default_address,
    delete_address,
)