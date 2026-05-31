"""Tests for APIKeyAuthentication."""

from unittest.mock import patch

import pytest
from django.test import RequestFactory

from core.authentication import APIKeyAuthentication, APIKeyUser


@pytest.fixture
def factory():
    return RequestFactory()


@pytest.fixture
def auth():
    return APIKeyAuthentication()


class TestAPIKeyAuthentication:
    VALID_KEY = 'test-api-key-abc123'

    def _request(self, factory, header=None):
        req = factory.get('/api/stats/')
        if header:
            req.META['HTTP_AUTHORIZATION'] = header
        return req

    def _patch_key(self):
        return (
            patch('core.authentication.settings')
            if False
            else patch(
                'core.authentication.settings',
                **{'API_KEY': self.VALID_KEY},
            )
        )

    # --- Valid header ---

    def test_valid_api_key_returns_api_key_user(self, factory, auth):
        req = self._request(factory, f'Api-Key {self.VALID_KEY}')
        with patch('core.authentication.settings') as s:
            s.API_KEY = self.VALID_KEY
            result = auth.authenticate(req)
        assert result is not None
        user, token = result
        assert isinstance(user, APIKeyUser)
        assert token is None

    def test_wrong_api_key_raises(self, factory, auth):
        from rest_framework.exceptions import AuthenticationFailed

        req = self._request(factory, 'Api-Key wrong-key')
        with patch('core.authentication.settings') as s:
            s.API_KEY = self.VALID_KEY
            with pytest.raises(AuthenticationFailed):
                auth.authenticate(req)

    def test_no_header_returns_none(self, factory, auth):
        req = self._request(factory)
        result = auth.authenticate(req)
        assert result is None

    def test_different_scheme_returns_none(self, factory, auth):
        req = self._request(factory, f'Bearer {self.VALID_KEY}')
        result = auth.authenticate(req)
        assert result is None

    def test_empty_key_raises(self, factory, auth):
        from rest_framework.exceptions import AuthenticationFailed

        req = self._request(factory, 'Api-Key ')
        with patch('core.authentication.settings') as s:
            s.API_KEY = self.VALID_KEY
            with pytest.raises(AuthenticationFailed):
                auth.authenticate(req)

    # --- Query param must NOT work (removed) ---

    def test_query_param_api_key_ignored(self, factory, auth):
        """?api_key= must no longer be accepted."""
        req = factory.get('/api/stats/', {'api_key': self.VALID_KEY})
        with patch('core.authentication.settings') as s:
            s.API_KEY = self.VALID_KEY
            result = auth.authenticate(req)
        assert result is None

    # --- Timing safety ---

    def test_uses_compare_digest(self):
        """Verify _validate_key uses hmac.compare_digest, not ==."""
        import inspect

        src = inspect.getsource(APIKeyAuthentication._validate_key)
        assert 'hmac.compare_digest' in src
        assert '==' not in src.split('hmac')[0]  # no == before hmac call


class TestAPIKeyUser:
    def test_is_authenticated(self):
        u = APIKeyUser()
        assert u.is_authenticated is True

    def test_is_not_staff(self):
        u = APIKeyUser()
        assert u.is_staff is False

    def test_str(self):
        assert 'API Key' in str(APIKeyUser())
