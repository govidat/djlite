from django.shortcuts import render

# Create your views here.
# Create your views here.
from django.shortcuts import render # new
from django.views.generic import TemplateView
from django.utils.timezone import localtime, now

class HomeZappView(TemplateView):
    template_name = 'zapp/homezapp.html'
# for adding some additional context
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['counts'] = [1,4]
        context['current_time'] = localtime(now())
        return context

def home_zapp_fbv(request): # new
    context = {}
    context['counts'] = [1,4]
    context['current_time'] = localtime(now())
    return render(request, 'zapp/homezapp.html', context)