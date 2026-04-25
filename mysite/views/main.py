from django.views.generic import TemplateView
from django.shortcuts import render, redirect
from django.http import Http404
from django.views.decorators.http import require_POST
from django.utils.translation import get_language
from django.conf import settings
from mysite.models import PageContent
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

        #return super().get(request, *args, **kwargs)
        # ── Track A: check for raw HTML content first ─────────────
        active_lang = get_language() or settings.LANGUAGE_CODE
        raw_html = self._resolve_page_content(
            client_obj, page_id, active_lang
        )

        if raw_html is not None:
            # Render raw HTML directly — bypass cotton component tree
            return render(request, 'page_content.html', {
                'raw_html': raw_html,
                # 'client', 'theme', 'page_dict' still come from context processor
            })

        # ── Track B: component tree (cotton templates) ────────────
        return super().get(request, *args, **kwargs)

    def _resolve_page_content(self, client_obj, page_id, active_lang):
        """
        Returns the HTML string for the best available language match,
        or None if no PageContent exists for this page.
        Priority: active_lang → 'en' → first available row
        """
        from mysite.models import Page, PageContent

        try:
            page_obj = Page.objects.get(
                client=client_obj,
                page_id=page_id
            )
        except Page.DoesNotExist:
            return None

        contents = list(
            PageContent.objects
            .filter(page=page_obj)
            .values('language_code', 'html')
        )

        if not contents:
            return None

        # Build lookup dict
        content_map = {c['language_code']: c['html'] for c in contents}

        # Priority fallback
        return (
            content_map.get(active_lang)
            or content_map.get('en')
            or contents[0]['html']   # first available
        )        


def landing_page(request):
    """
    Root URL — no client context.
    Shows a platform-level landing page.
    """
    return render(request, 'landing.html', {})

@require_POST
def set_theme(request):
    selected = request.POST.get("theme")
    request.session["active_theme_id"] = selected
    return redirect(request.META.get("HTTP_REFERER", "/"))


# ── Error handlers ────────────────────────────────────────────────────
# Registered in mydj/urls.py as handler404 and handler500.

def custom_404(request, exception=None):
    # client and theme available via context processors if request.client
    # was resolved by middleware — so the 404 template can show client branding
    return render(request, '404.html', status=404)


def custom_500(request):
    # context processors do NOT run on 500 — keep 500.html self-contained
    return render(request, '500.html', status=500)

