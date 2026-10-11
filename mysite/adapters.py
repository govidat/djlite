# adapters.py

from allauth.account.adapter import DefaultAccountAdapter
from .models import CustomerProfile, ClientUserProfile, Client
from django.urls import reverse
from django.contrib import messages

class ClientAwareAccountAdapter(DefaultAccountAdapter):

    def save_user(self, request, user, form, commit=True):
        """Called on new user registration."""
        user = super().save_user(request, user, form, commit=False)
        if commit:
            user.save()

        client_code = request.session.get('client_code')
        user_type = request.session.get('user_type', 'customer')

        if client_code and not user.is_superuser:
            try:
                client = Client.objects.get(client_code=client_code)

                if user_type == 'customer':
                    # Type 2 — create CustomerProfile with extra fields from form
                    CustomerProfile.objects.get_or_create(
                        user=user,
                        client=client,
                        defaults={
                            'mobile':             form.cleaned_data.get('mobile', ''),
                            'preferred_language': form.cleaned_data.get(
                                'preferred_language',
                                client.language_list[0] if client.language_list else ''
                            ),
                        }
                    )

            except Client.DoesNotExist:
                pass

        return user

    def get_signup_redirect_url(self, request):
        #client_code = request.session.pop('onboarding_client_code', None)
        client_code = request.session.get('client_code')   # ✅ no pop
        if client_code:
            try:
                return reverse(
                    'customer_onboarding',
                    kwargs={'client_code': client_code}
                )
            except Exception:
                pass  # fallback safely

            #return reverse(
            #    'customer_onboarding',
            #    kwargs={'client_code': client_code}
            #)
        return super().get_signup_redirect_url(request)

    def get_login_redirect_url(self, request):
        client_code = request.session.pop('onboarding_client_code', None)
        if client_code:
            return reverse(
                'customer_onboarding',
                kwargs={'client_code': client_code}
            )
        redirect_url = request.session.pop('login_redirect', None)
        if redirect_url:
            return redirect_url
        client_code = request.session.get('client_code')
        if client_code:
            return reverse('client_home', kwargs={'client_code': client_code})
        return super().get_login_redirect_url(request)

    def pre_login(self, request, user, **kwargs):
        client_code = request.session.get('client_code')
        if client_code and not user.is_superuser:
            if not hasattr(user, 'client_profile'):
                try:
                    client = Client.objects.get(client_code=client_code)
                    profile, created = CustomerProfile.objects.get_or_create(
                        user=user,
                        client=client,
                    )
                    if created:
                        request.session['onboarding_client_code'] = client_code
                except Client.DoesNotExist:
                    pass
        return super().pre_login(request, user, **kwargs)
        
    def logout(self, request):
        response = super().logout(request)

        # 🔥 Clear messages
        storage = messages.get_messages(request)
        list(storage)

        return response