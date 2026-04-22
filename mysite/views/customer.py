from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from mysite.models import Client, CustomerProfile, CustomerAddress
from mysite.forms import CustomerProfileForm, CustomerAddressForm


@login_required
def customer_onboarding(request, client_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
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
            address = address_form.save(commit=False)
            address.customer = profile
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
        # 'client' and 'theme' come from context processor
    })


@login_required
def customer_profile(request, client_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
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

    return render(request, 'customer/profile.html', {
        'form': form,
        'profile': profile,
        'addresses': profile.addresses.all(),
        # 'client' and 'theme' come from context processor
    })


@login_required
def customer_addresses(request, client_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )
    return render(request, 'customer/addresses.html', {
        'addresses': profile.addresses.all(),
        'form': CustomerAddressForm(),
        'profile': profile,
        # 'client' and 'theme' come from context processor
    })


@login_required
def add_address(request, client_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(
        CustomerProfile, user=request.user, client=client_obj
    )
    if request.method == 'POST':
        form = CustomerAddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.customer = profile
            address.is_default = not profile.addresses.exists()
            address.save()
            messages.success(request, 'Address added.')
            return redirect('customer_addresses', client_id=client_id)
        else:
            return render(request, 'customer/addresses.html', {
                'addresses': profile.addresses.all(),
                'form': form,
                'profile': profile,
            })
    return redirect('customer_addresses', client_id=client_id)


@login_required
def set_default_address(request, client_id, address_id):
    client_obj = request.client or get_object_or_404(Client, client_id=client_id)
    profile = get_object_or_404(CustomerProfile, user=request.user, client=client_obj)
    address = get_object_or_404(CustomerAddress, pk=address_id, customer=profile)
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
    profile = get_object_or_404(CustomerProfile, user=request.user, client=client_obj)
    address = get_object_or_404(CustomerAddress, pk=address_id, customer=profile)
    if request.method == 'POST':
        if profile.default_address_id == address.pk:
            profile.default_address = None
            profile.save(update_fields=['default_address'])
        address.delete()
        messages.success(request, 'Address deleted.')
    return redirect('customer_addresses', client_id=client_id)



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