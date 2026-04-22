
# Create your views here.
from django.shortcuts import render, redirect, get_object_or_404, reverse
from django.views.generic import TemplateView
from django.conf import settings
from django.views.decorators.http import require_POST
from django.contrib.auth import logout

from utils.common_functions import fetch_clientstatic
project_base_language = settings.LANGUAGE_CODE   # 'en'
#import json # this is just for debugging the json outputs of client/ pages...

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Client, CustomerProfile, CustomerAddress
from .forms import CustomerProfileForm, CustomerAddressForm
"""
get_context_data() runs first    ← context['client'] is {} here
        ↓
View returns response  - so it is not able to process any data within client
        ↓
Context processors run           ← context['client'] gets populated here
        ↓
Template renders                 ← client is available here
"""


# Assuming url of form path("<str:client_id>/<str:page>/", ClientPageView.as_view(), name="client_page")
class ClientPageView(TemplateView):
    template_name = 'base.html'
    """     
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add any common context data here that all views need
        lv_client_id = self.kwargs.get("client_id", '')   # <-- get it from URL
        lv_page_id = self.kwargs.get('page', 'home')

        # client and theme already in context via context_processor
        # Just add page-specific data
        client_dict = context.get('client', {})
        context['page'] = next(
            (p for p in client_dict.get('pages', [])
             if p.get('page_id') == lv_page_id),
            {}
        )
        context['jsonclient'] = json.dumps(client_dict)
        return context
    """
    """
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

    
    #sample output of theme
    #{'primary': '#661ae6', 'secondary': '#d926aa', 'accent': '#1fb2a6', 'neutral': '#191d24', 'primary_content': '#ffffff', 'secondary_content': '#ffffff', 'accent_content': '#ffffff', 'neutral_content': '#a6adbb', 'base_100': '#2a303c', 'base_200': '#242933', 'base_300': '#1d232a', 'base_content': '#a6adbb', 'success': '#36d399', 'warning': '#fbbd23', 'error': '#f87272', 'info': '#3abff8', 'success_content': '#000000', 'warning_content': '#000000', 'error_content': '#000000', 'info_content': '#000000', 'font_body': '', 'font_heading': '', 'base_font_size': '16px', 'scale_ratio': 1.2, 'section_gap': '4rem', 'container_padding': '1rem', 'radius_btn': '0.5rem', 'radius_card': '1rem', 'radius_input': '0.5rem', 'shadow_sm': '0 1px 2px 0 rgb(0 0 0 / 0.05)', 'shadow_md': '0 4px 6px -1px rgb(0 0 0 / 0.1)', 'shadow_lg': '0 10px 15px -3px rgb(0 0 0 / 0.1)'}

    
    context["jsonclient"] = json.dumps(client_dict)
    return context
    """

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


def landing_page(request):
    """
    Root URL — no client context.
    Show a landing page or redirect to a known client.
    """
    # Option 1: redirect to a default client from settings
    #default_client = getattr(settings, 'DEFAULT_CLIENT_ID', None)
    #if default_client:
    #    return redirect('client_page', client_id=default_client)

    # Option 2: show a simple landing page
    return render(request, 'landing.html', {})

# ── Auth entry points ─────────────────────────────────────────────────

def client_login(request, client_id):
    get_object_or_404(Client, client_id=client_id)
    request.session['client_id']      = client_id
    request.session['user_type']      = 'customer'
    request.session['login_redirect'] = reverse(
        'client_page', kwargs={'client_id': client_id}
    )
    if request.user.is_authenticated:
        return redirect('client_page', client_id=client_id)
    return redirect('account_login')


def client_signup(request, client_id):
    client = get_object_or_404(Client, client_id=client_id)
    request.session['client_id'] = client_id
    request.session['user_type'] = 'customer'
    if request.user.is_authenticated:
        profile, created = CustomerProfile.objects.get_or_create(
            user=request.user,
            client=client,
        )
        if created:
            request.session['onboarding_client_id'] = client_id
            return redirect('customer_onboarding', client_id=client_id)
        return redirect('client_page', client_id=client_id)
    return redirect('account_signup')


def client_logout(request, client_id):
    get_object_or_404(Client, client_id=client_id)
    if request.method == 'POST':
        request.session.pop('user_type', None)
        request.session.pop('onboarding_client_id', None)
        logout(request)
        request.session['client_id'] = client_id   # restore after logout flushes session
    return redirect('client_page', client_id=client_id)


# ── Onboarding ────────────────────────────────────────────────────────

@login_required
def customer_onboarding(request, client_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile    = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )
    if request.method == 'POST':
        profile_form = CustomerProfileForm(
            request.POST, instance=profile, client=client_obj
        )
        address_form = CustomerAddressForm(request.POST)
        if profile_form.is_valid() and address_form.is_valid():
            profile_form.save()
            address            = address_form.save(commit=False)
            address.customer   = profile
            address.is_default = True
            address.save()
            profile.default_address = address
            profile.save(update_fields=['default_address'])
            messages.success(request, 'Welcome! Your profile is set up.')
            return redirect('client_page', client_id=client_id)
    else:
        profile_form = CustomerProfileForm(instance=profile, client=client_obj)
        address_form = CustomerAddressForm()

    return render(request, 'customer/onboarding.html', {
        'profile_form': profile_form,
        'address_form': address_form,
        # 'client' and 'theme' come from context_processor
    })


# ── Profile ───────────────────────────────────────────────────────────

@login_required
def customer_profile(request, client_id):
    # client_obj from middleware — no DB hit needed
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile    = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )

    if request.method == 'POST':
        form = CustomerProfileForm(
            request.POST, instance=profile, client=client_obj
        )
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('customer_profile', client_id=client_id)
    else:
        form = CustomerProfileForm(instance=profile, client=client_obj)

    # No client_dict needed — context_processor provides it
    return render(request, 'customer/profile.html', {
        'form':      form,
        'profile':   profile,
        'addresses': profile.addresses.all(),
        # 'client' and 'theme' come from context_processor automatically
    })


# ── Addresses ─────────────────────────────────────────────────────────

@login_required
def customer_addresses(request, client_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile    = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )
    return render(request, 'customer/addresses.html', {
        'addresses': profile.addresses.all(),
        'form':      CustomerAddressForm(),
        'profile':   profile,
        # 'client' and 'theme' come from context_processor
    })

@login_required
def add_address(request, client_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile    = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )
    if request.method == 'POST':
        form = CustomerAddressForm(request.POST)
        if form.is_valid():
            address            = form.save(commit=False)
            address.customer   = profile
            address.is_default = not profile.addresses.exists()
            address.save()
            messages.success(request, 'Address added.')
            return redirect('customer_addresses', client_id=client_id)
        else:
            return render(request, 'customer/addresses.html', {
                'addresses': profile.addresses.all(),
                'form':      form,
                'profile':   profile,
            })
    return redirect('customer_addresses', client_id=client_id)


@login_required
def set_default_address(request, client_id, address_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile    = get_object_or_404(CustomerProfile, user=request.user, client=client_obj)
    address    = get_object_or_404(CustomerAddress, pk=address_id, customer=profile)
    if request.method == 'POST':
        profile.addresses.update(is_default=False)
        address.is_default = True
        address.save()
        profile.default_address = address
        profile.save(update_fields=['default_address'])
        messages.success(request, 'Default address updated.')
    return redirect('customer_addresses', client_id=client_id)



@login_required
def delete_address(request, client_id, address_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile    = get_object_or_404(CustomerProfile, user=request.user, client=client_obj)
    address    = get_object_or_404(CustomerAddress, pk=address_id, customer=profile)
    if request.method == 'POST':
        if profile.default_address_id == address.pk:
            profile.default_address = None
            profile.save(update_fields=['default_address'])
        address.delete()
        messages.success(request, 'Address deleted.')
    return redirect('customer_addresses', client_id=client_id)
"""

@login_required
def delete_address(request, client_id, address_id):
    client_obj = get_object_or_404(Client, client_id=client_id)
    profile    = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )
    address = get_object_or_404(
        CustomerAddress, pk=address_id, customer=profile
    )
    if request.method == 'POST':
        if profile.default_address_id == address.pk:
            profile.default_address = None
            profile.save(update_fields=['default_address'])
        address.delete()
        messages.success(request, 'Address deleted.')
    return redirect('customer_addresses', client_id=client_id)
"""
"""
@login_required
def customer_addresses(request, client_id):
    client    = get_object_or_404(Client, client_id=client_id)
    profile   = get_object_or_404(
        CustomerProfile, user=request.user, client=client
    )

    form = CustomerAddressForm()

    return render(request, 'customer/addresses.html', {
        'addresses': profile.addresses.all(),
        'form':      form,
        'profile':   profile,
        'client':    client,
    })


@login_required
def add_address(request, client_id):
    client  = get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client
    )

    if request.method == 'POST':
        form = CustomerAddressForm(request.POST)
        if form.is_valid():
            address          = form.save(commit=False)
            address.customer = profile
            address.save()
            messages.success(request, 'Address added.')
        else:
            # Return page with form errors
            return render(request, 'customer/addresses.html', {
                'addresses': profile.addresses.all(),
                'form':      form,
                'profile':   profile,
                'client':    client,
            })

    return redirect('customer_addresses', client_id=client_id)


@login_required
def set_default_address(request, client_id, address_id):
    client  = get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client
    )
    address = get_object_or_404(
        CustomerAddress, pk=address_id, customer=profile
    )

    if request.method == 'POST':
        # Clear all defaults for this customer
        profile.addresses.update(is_default=False)
        address.is_default = True
        address.save()
        profile.default_address = address
        profile.save(update_fields=['default_address'])
        messages.success(request, 'Default address updated.')

    return redirect('customer_addresses', client_id=client_id)


@login_required
def delete_address(request, client_id, address_id):
    client  = get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client
    )
    address = get_object_or_404(
        CustomerAddress, pk=address_id, customer=profile
    )

    if request.method == 'POST':
        if profile.default_address_id == address.pk:
            profile.default_address = None
            profile.save(update_fields=['default_address'])
        address.delete()
        messages.success(request, 'Address deleted.')

    return redirect('customer_addresses', client_id=client_id)
"""

""" below customer related content moved to views/customer.py
def client_signup(request, client_id):
    
    #Sets client context in session then redirects to allauth signup.
    #Type 2 customer signup entry point.
    
    client = get_object_or_404(Client, client_id=client_id)

    # Store in session so adapter can pick it up
    request.session['client_id']  = client_id
    request.session['user_type']  = 'customer'

    # If already logged in, just create profile and redirect
    if request.user.is_authenticated:
        CustomerProfile.objects.get_or_create(
            user=request.user,
            client=client,
        )
        return redirect('customer_profile', client_id=client_id)

    # Pass client to signup form for language choices
    form = CustomerSignupForm(client=client)
    return render(request, 'account/signup.html', {
        'form':   form,
        'client': client,
    })


def client_login(request, client_id):
    #Sets client context in session then redirects to allauth login.
    #client = get_object_or_404(Client, client_id=client_id)
    #request.session['client_id'] = client_id
    #request.session['user_type'] = 'customer'
    #return redirect('account_login')
    
    #Client-scoped login entry point.
    #Sets client context in session then delegates to allauth.
    
    client = get_object_or_404(Client, client_id=client_id)
    request.session['client_id'] = client_id
    request.session['user_type'] = 'customer'

    # Store where to redirect after login
    request.session['login_redirect'] = reverse(
        'client_home', kwargs={'client_id': client_id}
    )

    if request.user.is_authenticated:
        return redirect('client_home', client_id=client_id)

    return redirect('account_login')

@login_required
def customer_profile(request, client_id):
    client  = get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
        CustomerProfile,
        user=request.user,
        client=client
    )

    if request.method == 'POST':
        form = CustomerProfileForm(
            request.POST,
            instance=profile,
            client=client
        )
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('customer_profile', client_id=client_id)
    else:
        form = CustomerProfileForm(instance=profile, client=client)

    return render(request, 'customer/profile.html', {
        'form':    form,
        'profile': profile,
        'client':  client,
    })


@login_required
def customer_addresses(request, client_id):
    client  = get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
        CustomerProfile,
        user=request.user,
        client=client
    )
    addresses = profile.addresses.all()

    return render(request, 'customer/addresses.html', {
        'addresses': addresses,
        'client':    client,
    })


def client_logout(request, client_id):
    
    #Client-scoped logout.
    #Clears session and redirects to client home (not global allauth logout).
    
    client = get_object_or_404(Client, client_id=client_id)
    if request.method == 'POST':
        # Clear client session data
        request.session.pop('client_id', None)
        request.session.pop('user_type', None)
        logout(request)
        return redirect('home', client_id=client_id)
    # GET — show confirmation page or just redirect
    return redirect('home', client_id=client_id)

""" 

"""
@login_required
def customer_onboarding(request, client_id):
    client  = get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client
    )

    if request.method == 'POST':
        profile_form = CustomerProfileForm(
            request.POST, instance=profile, client=client
        )
        address_form = CustomerAddressForm(request.POST)

        if profile_form.is_valid() and address_form.is_valid():
            profile_form.save()
            address            = address_form.save(commit=False)
            address.customer   = profile
            address.is_default = True
            address.save()
            profile.default_address = address
            profile.save(update_fields=['default_address'])
            messages.success(request, 'Welcome! Your profile is set up.')
            return redirect('home', client_id=client_id)
    else:
        profile_form = CustomerProfileForm(instance=profile, client=client)
        address_form = CustomerAddressForm()

    return render(request, 'customer/onboarding.html', {
        'profile_form': profile_form,
        'address_form': address_form,
        'client':       client,
    })

"""

"""
@login_required
def customer_profile(request, client_id):
    client  = get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client
    )

    if request.method == 'POST':
        form = CustomerProfileForm(
            request.POST, instance=profile, client=client
        )
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('customer_profile', client_id=client_id)
    else:
        form = CustomerProfileForm(instance=profile, client=client)

    return render(request, 'customer/profile.html', {
        'form':      form,
        'profile':   profile,
        'client':    client,
        'addresses': profile.addresses.all(),
    })
"""
"""
def client_login(request, client_id):
    
    get_object_or_404(Client, client_id=client_id)
    request.session['client_id']      = client_id
    request.session['user_type']      = 'customer'
    request.session['login_redirect'] = reverse(
        'client_page', kwargs={'client_id': client_id}
    )
    if request.user.is_authenticated:
        return redirect('client_page', client_id=request.client.client_id)
    return redirect('account_login')


def client_signup(request, client_id):
    client = get_object_or_404(Client, client_id=client_id)
    request.session['client_id'] = client_id
    request.session['user_type'] = 'customer'

    if request.user.is_authenticated:
        profile, created = CustomerProfile.objects.get_or_create(
            user=request.user,
            client=client,
        )
        if created:
            request.session['onboarding_client_id'] = client_id
            return redirect('customer_onboarding', client_id=request.client.client_id)
        return redirect('client_page', client_id=request.client.client_id)

    return redirect('account_signup')


def client_logout(request, client_id):
    get_object_or_404(Client, client_id=client_id)
    if request.method == 'POST':

        # Keep client_id in session so navbar still works after logout
        # Only clear user-specific session data
        request.session.pop('user_type', None)
        request.session.pop('onboarding_client_id', None)
        logout(request)   # clears auth but we restore client_id below
        request.session['client_id'] = client_id   # ← restore after logout

        #request.session.pop('user_type', None)
        #logout(request)
    return redirect('client_page', client_id=request.client.client_id)
"""
"""
@login_required
def customer_onboarding(request, client_id):
    client_obj  = get_object_or_404(Client, client_id=client_id)
    client_dict = fetch_clientstatic(lv_client_id=client_id)
    client_dict.setdefault("pages", [])
    client_dict.setdefault("themes", [])
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )

    if request.method == 'POST':
        profile_form = CustomerProfileForm(
            request.POST, instance=profile, client=client_obj
        )
        address_form = CustomerAddressForm(request.POST)
        if profile_form.is_valid() and address_form.is_valid():
            profile_form.save()
            address            = address_form.save(commit=False)
            address.customer   = profile
            address.is_default = True
            address.save()
            profile.default_address = address
            profile.save(update_fields=['default_address'])
            messages.success(request, 'Welcome! Your profile is set up.')
            return redirect('client_page', client_id=client_id)
    else:
        profile_form = CustomerProfileForm(instance=profile, client=client_obj)
        address_form = CustomerAddressForm()

    return render(request, 'customer/onboarding.html', {
        'profile_form': profile_form,
        'address_form': address_form,
        'client':       client_dict,           # ← dict
    })
"""
"""
@login_required
def customer_profile(request, client_id):
    client_obj = get_object_or_404(Client, client_id=client_id)
    profile    = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )

    # Fetch client as dict — same as ClientPageView so templates work
    client_dict = fetch_clientstatic(lv_client_id=client_id)
    client_dict.setdefault("pages", [])
    client_dict.setdefault("themes", [])

    if request.method == 'POST':
        form = CustomerProfileForm(
            request.POST, instance=profile, client=client_obj
        )
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('customer_profile', client_id=client_id)
    else:
        form = CustomerProfileForm(instance=profile, client=client_obj)

    return render(request, 'customer/profile.html', {
        'form':      form,
        'profile':   profile,
        'client':    client_dict,              # ← dict, not model instance
        'addresses': profile.addresses.all(),
    })
"""
"""

@login_required
def customer_addresses(request, client_id):
    client_obj  = get_object_or_404(Client, client_id=client_id)
    client_dict = fetch_clientstatic(lv_client_id=client_id)
    client_dict.setdefault("pages", [])
    client_dict.setdefault("themes", [])
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )

    return render(request, 'customer/addresses.html', {
        'addresses': profile.addresses.all(),
        'form':      CustomerAddressForm(),
        'profile':   profile,
        'client':    client_dict,              # ← dict
    })
"""

"""
@login_required
def add_address(request, client_id):
    client_obj  = get_object_or_404(Client, client_id=client_id)
    client_dict = fetch_clientstatic(lv_client_id=client_id)
    client_dict.setdefault("pages", [])
    client_dict.setdefault("themes", [])
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )

    if request.method == 'POST':
        form = CustomerAddressForm(request.POST)
        if form.is_valid():
            address            = form.save(commit=False)
            address.customer   = profile
            # Set is_default — True if this is the first address
            address.is_default = not profile.addresses.exists()
            address.save()
            messages.success(request, 'Address added.')
            return redirect('customer_addresses', client_id=client_id)
        else:
            return render(request, 'customer/addresses.html', {
                'addresses': profile.addresses.all(),
                'form':      form,
                'profile':   profile,
                'client':    client_dict,
            })

    return redirect('customer_addresses', client_id=client_id)
"""
"""
@login_required
def set_default_address(request, client_id, address_id):
    client_obj = get_object_or_404(Client, client_id=client_id)
    profile    = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )
    address = get_object_or_404(
        CustomerAddress, pk=address_id, customer=profile
    )
    if request.method == 'POST':
        profile.addresses.update(is_default=False)
        address.is_default = True
        address.save()
        profile.default_address = address
        profile.save(update_fields=['default_address'])
        messages.success(request, 'Default address updated.')
    return redirect('customer_addresses', client_id=client_id)
"""
"""


The golden rule

select_related → OneToOneField, ForeignKey

prefetch_related → ForeignKey(many), reverse relations


"""