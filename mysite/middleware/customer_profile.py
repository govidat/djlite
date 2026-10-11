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

    def _get_url_client_code(self, request):
        """
        Extract client_code from the URL path directly.
        Handles paths of the form /{client_code}/ and /{client_code}/{anything}/
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
            #'api',       # ← ADD THIS — API routes are not client-scoped URLs
            #'demand',    # ← ADD THIS — safety net for any /demand/ prefixed routes            
        }
        if candidate == 'api':
            # /api/<client_code>/...
            if len(parts) > 1 and parts[1] not in RESERVED and parts[1]:
                return parts[1]
            return None

        if candidate in RESERVED:
            return None

        return candidate

    def __call__(self, request):

        # ── Defaults ─────────────────────────────────────────────
        request.client = None
        request.customer_profile = None
        request.client_profile = None
        request.active_role = None
        request.active_country_code = None

        # ── Resolve client_code (URL → session fallback) ───────────
        #── Resolve client_code ─────────────────────────────────────

        # ── Resolve client_code from URL path ───────────────────────
        url_client_code = self._get_url_client_code(request)

        if url_client_code:
            try:
                request.client = Client.objects.get(client_code=url_client_code)
                request.session['client_code'] = url_client_code
            except Client.DoesNotExist:
                raise Http404(f"Client '{url_client_code}' does not exist.")
        else:
            # No client_code in URL — try session (allauth pages, set-theme, etc.)
            session_client_code = request.session.get('client_code')
            if session_client_code:
                try:
                    request.client = Client.objects.get(client_code=session_client_code)
                except Client.DoesNotExist:
                    request.session.pop('client_code', None)

        # ── Resolve active country from session ──────────────────
        if request.client and request.client.is_country_enabled():
            session_country = request.session.get('active_country_code')
            allowed = request.client.get_allowed_country_codes()
            if session_country and session_country in allowed:
                request.active_country_code = session_country
            else:
                default = request.client.default_country_code or 'IN'
                request.active_country_code = default if default in allowed else next(iter(allowed), None)
                request.session['active_country_code'] = request.active_country_code
        # ── Geo-detect country on first visit after login ────────
        if (request.user.is_authenticated and
                request.client and
                request.client.is_country_enabled() and
                'active_country_code' not in request.session):
            detected = _geo_detect_country(request)
            if detected:
                allowed = request.client.get_allowed_country_codes()
                if detected in allowed:
                    request.session['active_country_code'] = detected
                    request.active_country_code = detected


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


def _geo_detect_country(request):
    """Best-effort geo-detect country from client IP. Returns ISO alpha-2 code or None."""
    try:
        from ipware import get_client_ip
        from django.contrib.gis.geoip2 import GeoIP2
        from django.conf import settings
        client_ip, _ = get_client_ip(request)
        if not client_ip or client_ip in ('127.0.0.1', '::1', 'localhost'):
            return None
        g = GeoIP2()
        cc = g.country_code(client_ip)
        return cc.upper() if cc else None
    except Exception:
        return None
