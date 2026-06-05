# middleware/customer_profile.py


from mysite.models import CustomerProfile, Client, ClientUserProfile
from django.shortcuts import get_object_or_404
from django.http import Http404
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

    def _get_url_client_id(self, request):
        """
        Extract client_id from the URL path directly.
        Handles paths of the form /{client_id}/ and /{client_id}/{anything}/
        Does not rely on resolver_match which may not be populated yet.
        """
        # Strip leading slash, split on '/'
        # path = '/bahushira/home/' → parts = ['bahushira', 'home', '']
        parts = request.path.lstrip('/').split('/')
        if not parts or not parts[0]:
            return None

        candidate = parts[0]

        # Exclude known non-client path prefixes
        RESERVED = {
            'admin', 'accounts', '__debug__', 'i18n',
            'static', 'media', 'favicon.ico', 'set-theme', '_nested_admin',
            'api',       # ← ADD THIS — API routes are not client-scoped URLs
            'demand',    # ← ADD THIS — safety net for any /demand/ prefixed routes            
        }
        if candidate in RESERVED:
            return None

        return candidate

    def __call__(self, request):

        # ── Defaults ─────────────────────────────────────────────
        request.client = None
        request.customer_profile = None
        request.client_profile = None
        request.active_role = None

        # ── Resolve client_id (URL → session fallback) ───────────
        #── Resolve client_id ─────────────────────────────────────

        # ── Resolve client_id from URL path ───────────────────────
        url_client_id = self._get_url_client_id(request)

        if url_client_id:
            try:
                request.client = Client.objects.get(client_id=url_client_id)
                request.session['client_id'] = url_client_id
            except Client.DoesNotExist:
                raise Http404(f"Client '{url_client_id}' does not exist.")
        else:
            # No client_id in URL — try session (allauth pages, set-theme, etc.)
            session_client_id = request.session.get('client_id')
            if session_client_id:
                try:
                    request.client = Client.objects.get(client_id=session_client_id)
                except Client.DoesNotExist:
                    request.session.pop('client_id', None)



        # ── Resolve profiles (ONLY if logged in) ─────────────────
        user = getattr(request, "user", None)
        if (
            user
            and user.is_authenticated
            and request.client
        ):
        #if request.user.is_authenticated and request.client:

            # ✅ Try staff profile FIRST (since it's exclusive)
            # Staff profile
            request.client_profile = getattr(
                user,
                'client_profile',
                None
            )

            if (
                request.client_profile
                and request.client_profile.client_id == request.client.id
            ):
                request.active_role = 'staff'
            """
            try:
                request.client_profile = request.user.client_profile
                if request.client_profile.client_id == request.client.id:
                    request.active_role = 'staff'
            except ClientUserProfile.DoesNotExist:
                pass
            """
            # ✅ Try customer profile
            # Customer profile
            if not request.active_role:
                request.customer_profile = (
                    CustomerProfile.objects.filter(
                        user=user,
                        client=request.client,
                        is_active=True,
                    ).first()
                )

                if request.customer_profile:
                    request.active_role = 'customer'
            """
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
            """

        return self.get_response(request)



