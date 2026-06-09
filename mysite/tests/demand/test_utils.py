# mysite/tests/demand/test_utils.py  — NEW FILE

class TestClientMiddleware:
    """
    Test-only middleware. Sets request.client from the WSGI environ
    key _TEST_CLIENT_OBJ injected by InjectingAPIClient.
    """    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        client_obj = request.META.get('_TEST_CLIENT_OBJ')
        if client_obj is not None:
            request.client           = client_obj
            request.customer_profile = None
            request.client_profile   = None
            request.active_role      = None
        return self.get_response(request)

