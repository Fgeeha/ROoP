"""
Custom authentication for Django REST Framework.
Supports both Django session auth and API key auth.
"""

import hmac

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class APIKeyAuthentication(BaseAuthentication):
    """
    API Key authentication.
    Clients pass the key in the Authorization header:
        Authorization: Api-Key <your-api-key>
    """

    keyword = 'Api-Key'

    def authenticate(self, request):
        auth_header = request.headers.get('authorization', '')
        if not auth_header.startswith(self.keyword + ' '):
            return None

        api_key = auth_header[len(self.keyword) + 1 :].strip()
        return self._validate_key(api_key)

    def _validate_key(self, api_key: str):
        # hmac.compare_digest prevents timing attacks
        if hmac.compare_digest(api_key, settings.API_KEY):
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
