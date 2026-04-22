from django.views.generic import TemplateView
from django.shortcuts import render, redirect
from django.http import Http404
from django.views.decorators.http import require_POST
from django.conf import settings

from utils.common_functions import fetch_clientstatic


class ClientPageView(TemplateView):
    template_name = 'base.html'

    def get(self, request, *args, **kwargs):
        client_obj = request.client  # set by middleware
        if not client_obj:
            raise Http404("Client not found.")

        page_id = kwargs.get('page', 'home')

        # fetch_clientstatic is cached — calling it here and in the
        # context processor costs nothing on the second call
        client_dict = fetch_clientstatic(lv_client_id=client_obj.client_id)

        page_dict = next(
            (p for p in client_dict.get('pages', [])
             if p.get('page_id') == page_id),
            None
        )

        if not page_dict:
            raise Http404(f"Page '{page_id}' not found.")

        return super().get(request, *args, **kwargs)


def landing_page(request):
    """
    Root URL — no client context.
    Shows a platform-level landing page.
    """
    return render(request, 'landing.html', {})


@require_POST
def set_theme(request, client_id):
    selected = request.POST.get('theme')
    request.session['active_theme_id'] = selected
    return redirect(request.META.get('HTTP_REFERER', '/'))


# ── Error handlers ────────────────────────────────────────────────────
# Registered in mydj/urls.py as handler404 and handler500.

def custom_404(request, exception=None):
    # client and theme available via context processors if request.client
    # was resolved by middleware — so the 404 template can show client branding
    return render(request, '404.html', status=404)


def custom_500(request):
    # context processors do NOT run on 500 — keep 500.html self-contained
    return render(request, '500.html', status=500)

