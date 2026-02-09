"""
Custom authentication for Django REST Framework.
Supports both Django session auth and API key auth.
"""

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class APIKeyAuthentication(BaseAuthentication):
    """
    API Key authentication.
    Clients pass the key in the Authorization header:
        Authorization: Api-Key <your-api-key>
    Or as a query parameter:
        ?api_key=<your-api-key>
    """

    keyword = 'Api-Key'

    def authenticate(self, request):
        # Check Authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith(self.keyword + ' '):
            api_key = auth_header[len(self.keyword) + 1:].strip()
            return self._validate_key(api_key, request)

        # Check query parameter
        api_key = request.query_params.get('api_key', '')
        if api_key:
            return self._validate_key(api_key, request)

        # No API key provided, let other auth backends handle it
        return None

    def _validate_key(self, api_key, request):
        if api_key == settings.API_KEY:
            # Return a simple user-like object for API key auth
            return (APIKeyUser(), None)
        raise AuthenticationFailed('Invalid API key')

    def authenticate_header(self, request):
        return self.keyword


class APIKeyUser:
    """Minimal user object for API key authentication."""

    is_authenticated = True
    is_active = True
    is_staff = False
    username = 'api_user'
    pk = None

    def __str__(self):
        return 'API Key User'
