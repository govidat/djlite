#from django.shortcuts import render

# Create your views here.
from django.shortcuts import render # new
from django.views.generic import TemplateView
#from django.utils.timezone import localtime, now
#from django.utils.translation import get_language
from django.conf import settings
#from django.shortcuts import get_object_or_404
from django.shortcuts import redirect # for persisting theme
from django.views.decorators.http import require_POST
from django.shortcuts import render, HttpResponse
#from collections import defaultdict
#from datastar_py.django import DatastarResponse
from django.contrib.auth import logout

from utils.common_functions import fetch_clientstatic
#, build_nested_hierarchy, build_layout_tree
# update_list_of_dictionaries, fetch_translations, build_nested_hierarchy, build_nested_hierarchy_v2
project_base_language = settings.LANGUAGE_CODE   # 'en'
from django.shortcuts import redirect  # this is for persisting theme selection
import json # this is just for debugging the json outputs of client/ pages...

from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from mysite.models import Client
#from .forms import CustomerProfileForm, CustomerSignupForm, CustomerProfile, CustomerAddress

# Assuming url of form path("<str:client_id>/<str:page>/", ClientPageView.as_view(), name="client_page")
class ClientPageView(TemplateView):
    template_name = 'base.html'
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add any common context data here that all views need
        lv_client_id = self.kwargs.get("client_id", 'bahushira')   # <-- get it from URL
        lv_page_id = self.kwargs.get('page', 'home')

        client_dict = fetch_clientstatic(lv_client_id=lv_client_id)

        # to avoid one random error while execution
        client_dict.setdefault("pages", [])
        client_dict.setdefault("themes", [])

        context["client"] = client_dict
        context["page"] = next(
            (p for p in client_dict["pages"] if p.get("page_id") == lv_page_id),
            {}
        )

        # pass the value of theme tokens
        
        selected_theme_id = self.request.session.get("active_theme_id")

        selected_theme = next(
            (t for t in client_dict["themes"] if t["theme_id"] == selected_theme_id),
            None
        )
        
        #selected_theme = False
        # bring up the client default
        if not selected_theme:
            selected_theme = next(
                (t for t in client_dict["themes"] if t["is_default"]),
                None
            )

        resolved_theme = selected_theme["tokens"] if selected_theme else {}
        context["theme"] = resolved_theme

        """
        sample output of theme
        {'primary': '#661ae6', 'secondary': '#d926aa', 'accent': '#1fb2a6', 'neutral': '#191d24', 'primary_content': '#ffffff', 'secondary_content': '#ffffff', 'accent_content': '#ffffff', 'neutral_content': '#a6adbb', 'base_100': '#2a303c', 'base_200': '#242933', 'base_300': '#1d232a', 'base_content': '#a6adbb', 'success': '#36d399', 'warning': '#fbbd23', 'error': '#f87272', 'info': '#3abff8', 'success_content': '#000000', 'warning_content': '#000000', 'error_content': '#000000', 'info_content': '#000000', 'font_body': '', 'font_heading': '', 'base_font_size': '16px', 'scale_ratio': 1.2, 'section_gap': '4rem', 'container_padding': '1rem', 'radius_btn': '0.5rem', 'radius_card': '1rem', 'radius_input': '0.5rem', 'shadow_sm': '0 1px 2px 0 rgb(0 0 0 / 0.05)', 'shadow_md': '0 4px 6px -1px rgb(0 0 0 / 0.1)', 'shadow_lg': '0 10px 15px -3px rgb(0 0 0 / 0.1)'}

        """
        context["jsonclient"] = json.dumps(client_dict)
        return context


# this is for persisting theme selection 

@require_POST
def set_theme(request):
    #if request.method == "POST":
    selected = request.POST.get("theme")
    #before = request.session.get("active_theme_id")
    """
    # Validate against allowed themes
    client_static = fetch_clientstatic(
        lv_client_id=request.session.get("client_id")
    )

    valid_names = [t["name"] for t in client_static.get("themes", [])]
    
    if selected in valid_names:
    """
    request.session["active_theme_id"] = selected
    return redirect(request.META.get("HTTP_REFERER", "/"))
    """
    Datastar is not working
    # using data star
    #return redirect(request.META.get("HTTP_REFERER", "/"))
    client_dict = fetch_clientstatic(lv_client_id=request.session.get("client_id"),
                                     use_cache=False  # important for immediate refresh
                                     )
    selected_theme_id = selected
    selected_theme = next(
        (t for t in client_dict["themes"] if t["theme_id"] == selected_theme_id),
        None
    )  
    #selected_theme = False
    # bring up the client default
    if not selected_theme:
        selected_theme = next(
            (t for t in client_dict["themes"] if t["is_default"]),
            None
        )

    resolved_theme = selected_theme["tokens"] if selected_theme else {}

    return render(
        request,
        "partials/theme_vars.html",
        {"theme": resolved_theme}
    )
    """

""""
The golden rule

select_related → OneToOneField, ForeignKey

prefetch_related → ForeignKey(many), reverse relations


"""