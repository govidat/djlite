#from django.shortcuts import render

# Create your views here.
from django.shortcuts import render # new
from django.views.generic import TemplateView
#from django.utils.timezone import localtime, now
#from django.utils.translation import get_language
from django.conf import settings
#from django.shortcuts import get_object_or_404

#from collections import defaultdict

from utils.common_functions import fetch_clientstatic
#, build_nested_hierarchy, build_layout_tree
# update_list_of_dictionaries, fetch_translations, build_nested_hierarchy, build_nested_hierarchy_v2
project_base_language = settings.LANGUAGE_CODE   # 'en'
from django.shortcuts import redirect  # this is for persisting theme selection
 
# Assuming url of form path("<int:pk>/<str:page>/", ClientPageView.as_view(), name="client_page")
class ClientPageView(TemplateView):
    template_name = 'base.html'
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add any common context data here that all views need
        lv_client_id = self.kwargs.get("pkey", 'bahushira')   # <-- get it from URL
        lv_page_id = self.kwargs.get('page', 'home')

        client_dict = fetch_clientstatic(lv_client_id=lv_client_id)

        client_dict.setdefault("pages", [])

        context["client"] = client_dict
        context["page"] = next(
            (p for p in client_dict["pages"] if p.get("page_id") == lv_page_id),
            {}
        )

        return context

"""
# this is for persisting theme selection 
def set_theme(request):
    if request.method == "POST":
        theme = request.POST.get("theme")
        if theme:
            request.session["theme"] = theme

    return redirect(request.META.get("HTTP_REFERER", "/"))
"""   
"""
The golden rule

select_related → OneToOneField, ForeignKey

prefetch_related → ForeignKey(many), reverse relations


"""