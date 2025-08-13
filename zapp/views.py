from django.shortcuts import render

# Create your views here.
# Create your views here.
from django.shortcuts import render # new
from django.views.generic import TemplateView
from django.utils.timezone import localtime, now
from django.utils.translation import get_language
from django.conf import settings

project_base_language = settings.LANGUAGE_CODE   # 'en'

def build_nested_hierarchy(flat_list):
    # Create a dictionary for quick lookup of items by their ID
    item_map = {item['id']: item for item in flat_list}

    # Initialize a list to store the top-level items (roots)
    nested_list = []

    # Iterate through each item to build the hierarchy
    for item in flat_list:
        parent_id = item.get('parent_id')

        # If the item has a parent, add it to the parent's children list
        if parent_id is not None and parent_id in item_map:
            parent_item = item_map[parent_id]
            if 'children' not in parent_item:
                parent_item['children'] = []
            parent_item['children'].append(item)
        # If the item has no parent, it's a top-level item
        else:
            nested_list.append(item)

    return nested_list

nb_items = settings.PC_NAVBAR_ITEMS

items_nested = build_nested_hierarchy(nb_items)

allowed_themes = settings.PC_THEMES

allowed_languages = settings.PC_LANGUAGES

nb = {}
nb['items_nested']=items_nested
nb['logo']="mylogo" 
nb['title']="My Django Core Lite"

zroot = {}
zclient = {}

#zroot['current_language'] = get_language()
zroot['counts'] = [1,4]
zroot['current_time'] = localtime(now())

zclient['allowed_themes']=allowed_themes
zclient['allowed_languages']=allowed_languages

class HomeZappView(TemplateView):
    template_name = 'zapp/homezappv2.html'
# for adding some additional context
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['nb'] = nb
        context['zroot'] = zroot
        context['zclient'] = zclient
        return context

def home_zapp_fbv(request): # new
    context = {}
    context['nb'] = nb
    context['zroot'] = zroot
    context['zclient'] = zclient

    return render(request, 'zapp/homezapp.html', context)
