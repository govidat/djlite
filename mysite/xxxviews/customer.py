from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from mysite.models import Client, CustomerProfile, CustomerAddress
from mysite.forms import (
    CustomerProfileForm,
    CustomerAddressForm,
)


# ── Auth entry points ─────────────────────────────────────────────────

def client_login(request, client_id):
    get_object_or_404(Client, client_id=client_id)
    request.session['client_id']      = client_id
    request.session['user_type']      = 'customer'
    request.session['login_redirect'] = reverse(
        'home', kwargs={'client_id': client_id}
    )
    if request.user.is_authenticated:
        return redirect('home', client_id=client_id)
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
        return redirect('home', client_id=client_id)

    return redirect('account_signup')


def client_logout(request, client_id):
    get_object_or_404(Client, client_id=client_id)
    if request.method == 'POST':
        request.session.pop('client_id', None)
        request.session.pop('user_type', None)
        logout(request)
    return redirect('home', client_id=client_id)


# ── Onboarding ────────────────────────────────────────────────────────

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


# ── Profile ───────────────────────────────────────────────────────────

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


# ── Addresses ─────────────────────────────────────────────────────────

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