# mysite/views/__init__.py

from mysite.views.main import (
    ClientPageView,
    landing_page,
    set_theme,
    custom_404,
    custom_500,
)
from mysite.views.auth import (
    client_login,
    client_signup,
    client_logout,
)
from mysite.views.customer import (
    customer_onboarding,
    customer_profile,
    customer_addresses,
    add_address,
    set_default_address,
    delete_address,
)

from mysite.views.catalogue import (
    catalogue_page,
    catalogue_filter,
    item_detail,
)

from mysite.views.demand.forecast_htmx import (
    override_key_field,
    override_value_inputs,
    override_propagation,
    encode_override_key,
    # Sprint 3B.6 — add these when you implement that sprint
    approval_panel,
    approval_reject_form,
    approval_copy_form,    
)
from mysite.views.demand.forecast_grid import (
    forecast_grid
)
