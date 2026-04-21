# middleware/customer_profile.py


from mysite.models import CustomerProfile, Client, ClientUserProfile
from django.shortcuts import get_object_or_404

"""
Request comes in
      ↓
Middleware runs first (before view)
      ↓
View runs (produces response)
      ↓
Context processor runs (adds to template context)
      ↓
Template renders

Runs on every request, before the view. Its job is to 
attach lightweight Python objects to request so views and templates can access them without hitting the DB again:

request.client          → Client model instance (for DB operations)
request.client_profile  → ClientUserProfile instance (staff)
request.customer_profile → CustomerProfile instance (customer)
request.active_role     → 'staff' / 'customer' / None

These are model instances — useful for DB operations in views but not directly usable in templates 
since templates expect dicts.
"""

class CustomerProfileMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # ── Defaults ─────────────────────────────────────────────
        request.client = None
        request.customer_profile = None
        request.client_profile = None
        request.active_role = None

        # ── Resolve client_id (URL → session fallback) ───────────
        client_id = None

        if hasattr(request, 'resolver_match') and request.resolver_match:
            client_id = request.resolver_match.kwargs.get('client_id')

        if not client_id:
            client_id = request.session.get('client_id')

        # ── Resolve Client object ────────────────────────────────
        if client_id:
            try:
                request.client = Client.objects.get(client_id=client_id)
                request.session['client_id'] = client_id  # keep session in sync
            except Client.DoesNotExist:
                request.client = None

        # ── Resolve profiles (ONLY if logged in) ─────────────────
        if request.user.is_authenticated and request.client:

            # ✅ Try staff profile FIRST (since it's exclusive)
            try:
                request.client_profile = request.user.client_profile
                if request.client_profile.client_id == request.client.id:
                    request.active_role = 'staff'
            except ClientUserProfile.DoesNotExist:
                pass

            # ✅ Try customer profile
            if not request.active_role:
                try:
                    request.customer_profile = CustomerProfile.objects.get(
                        user=request.user,
                        client=request.client,
                        is_active=True,
                    )
                    request.active_role = 'customer'
                except CustomerProfile.DoesNotExist:
                    pass

        return self.get_response(request)



"""
class CustomerProfileMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.customer_profile = None
        request.customer_client_id = None   # ← add this

        if request.user.is_authenticated and not request.user.is_staff:
            # Try URL kwargs first
            client_id = None
            if (hasattr(request, 'resolver_match')
                    and request.resolver_match):
                client_id = request.resolver_match.kwargs.get('client_id')

            # Fall back to session
            if not client_id:
                client_id = request.session.get('client_id')

            if client_id:
                request.customer_client_id = client_id   # ← store it
                try:
                    request.customer_profile = CustomerProfile.objects.get(
                        user=request.user,
                        client__client_id=client_id,
                        is_active=True,
                    )
                except CustomerProfile.DoesNotExist:
                    pass

        return self.get_response(request)
"""    

"""
class CustomerProfileMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        request.customer_profile = None

        if request.user.is_authenticated and hasattr(request, "client"):
            request.customer_profile = get_customer_profile(
                request.user,
                request.client
            )

        return self.get_response(request)
"""        