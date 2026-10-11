# mysite/views/auth.py
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import logout

from mysite.models import Client, CustomerProfile


def client_login(request, client_code):
    get_object_or_404(Client, client_code=client_code)
    request.session['client_code'] = client_code
    request.session['user_type'] = 'customer'
    request.session['login_redirect'] = reverse(
        'client_page', kwargs={'client_code': client_code}
    )
    if request.user.is_authenticated:
        return redirect('client_page', client_code=client_code)
    return redirect('account_login')


def client_signup(request, client_code):
    client = get_object_or_404(Client, client_code=client_code)
    request.session['client_code'] = client_code
    request.session['user_type'] = 'customer'
    if request.user.is_authenticated:
        profile, created = CustomerProfile.objects.get_or_create(
            user=request.user,
            client=client,
        )
        if created:
            request.session['onboarding_client_code'] = client_code
            return redirect('customer_onboarding', client_code=client_code)
        return redirect('client_page', client_code=client_code)
    return redirect('account_signup')


def client_logout(request, client_code):
    get_object_or_404(Client, client_code=client_code)
    if request.method == 'POST':
        request.session.pop('user_type', None)
        request.session.pop('onboarding_client_code', None)
        logout(request)
        request.session['client_code'] = client_code  # restore after logout flushes session
    return redirect('client_page', client_code=client_code)