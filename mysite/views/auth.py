from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import logout

from mysite.models import Client, CustomerProfile


def client_login(request, client_id):
    get_object_or_404(Client, client_id=client_id)
    request.session['client_id'] = client_id
    request.session['user_type'] = 'customer'
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
        request.session['client_id'] = client_id  # restore after logout flushes session
    return redirect('client_page', client_id=client_id)