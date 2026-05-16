# middleware/feature_control.py

from django.shortcuts import render

from utils.feature_control import is_feature_disabled


class ClientFeatureControlMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        client = getattr(request, 'client', None)

        path = request.path.lower()

        feature = None

        if '/catalogue/' in path:
            feature = 'catalogue'

        elif '/cart/' in path or '/checkout/' in path:
            feature = 'ecommerce'

        if client and feature:

            result = is_feature_disabled(
                client,
                feature,
            )

            if result["disabled"]:

                return render(
                    request,
                    'system/feature_disabled.html',
                    {
                        'feature': feature,
                        'message': result["message"],
                    },
                    status=503,
                )

        return self.get_response(request)