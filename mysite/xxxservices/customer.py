# services/customer.py

from mysite.models import CustomerProfile

def get_customer_profile(user, client):
    """
    Reusable helper (NO request dependency).
    """
    if not user.is_authenticated or not client:
        return None

    try:
        return CustomerProfile.objects.get(
            user=user,
            client=client,
            is_active=True,
        )
    except CustomerProfile.DoesNotExist:
        return None