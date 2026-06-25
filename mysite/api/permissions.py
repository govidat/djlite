# mysite/api/permissions.py
from rest_framework.permissions import BasePermission
from mysite.models import ClientUserProfile, CustomerProfile

class IsClientMember(BasePermission):
    """
    Ensures the authenticated user has a staff or customer profile
    for the client resolved from the URL (request.client).
    Re-checks here because DRF authentication runs after middleware,
    so request.active_role (set by CustomerProfileMiddleware) may be
    stale/unset for non-session auth (Basic, Token, etc.).
    """
    message = "You do not have access to this client."

    def has_permission(self, request, view):
        user = request.user
        client = getattr(request, 'client', None)

        if not client or not user or not user.is_authenticated:
            return False

        # Already resolved by middleware (session-based requests)
        if request.active_role in ('staff', 'customer'):
            return True

        # Re-check for non-session auth (Basic, Token) where
        # middleware ran before DRF authentication
        profile = getattr(user, 'client_profile', None)
        if profile and profile.client_id == client.id:
            request.active_role = 'staff'
            return True

        if CustomerProfile.objects.filter(
            user=user, client=client, is_active=True
        ).exists():
            request.active_role = 'customer'
            return True

        return False