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