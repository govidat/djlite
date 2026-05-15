# middleware/client_block.py

from django.db.models import Q
from django.shortcuts import render
from django.core.cache import cache
from django.utils import timezone

from mysite.models import ClientBlock


class ClientBlockMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        path = request.path

        EXCLUDED_PREFIXES = (
            '/admin/',
            '/static/',
            '/media/',
            '/favicon.ico',
        )

        if path.startswith(EXCLUDED_PREFIXES):
            return self.get_response(request)

        client = getattr(request, 'client', None)

        # Cache key
        # client=None means anonymous/global
        client_key = client.id if client else 'global'

        cache_key = f"client_blocked:{client_key}"

        blocked = cache.get(cache_key)

        if blocked is None:

            now = timezone.now()

            query = ClientBlock.objects.filter(
                is_active=True,
                from_date__lte=now,
                to_date__gte=now,
            )

            # GLOBAL BLOCK
            # OR CLIENT BLOCK
            if client:
                query = query.filter(
                    Q(client__isnull=True) |
                    Q(client=client)
                )
            else:
                query = query.filter(
                    client__isnull=True
                )

            blocked = query.exists()

            # longer cache if blocked
            timeout = 300 #if blocked else 60

            cache.set(cache_key, blocked, timeout)

        if blocked:

            return render(
                request,
                'system/client_blocked.html',
                status=503,
            )

        return self.get_response(request)