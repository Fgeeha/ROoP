"""
Tests for share-link lifetime and revocation.

A public link needs no authentication, so its lifetime and its revocation are
the only things standing between a shared chat and anyone who ever saw the URL.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from core.models import Document, SharedLink

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return User.objects.create_user(username='share_owner', password='pass12345')


@pytest.fixture
def other_user():
    return User.objects.create_user(username='share_other', password='pass12345')


@pytest.fixture
def document(owner, tmp_path):
    source = tmp_path / 'shared.txt'
    source.write_text('текст', encoding='utf-8')
    return Document.objects.create(
        user=owner,
        filename=source.name,
        original_filename='shared.txt',
        file_path=str(source),
        file_type='txt',
        size=10,
        status=Document.Status.COMPLETED,
    )


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


class TestShareLinkExpiry:
    def test_new_link_gets_expiry_from_settings(self, settings, owner):
        settings.SHARE_LINK_TTL_DAYS = 30

        link = SharedLink.issue(owner, SharedLink.ShareType.CHAT)

        assert link.expires_at is not None
        expected = timezone.now() + timedelta(days=30)
        assert abs((link.expires_at - expected).total_seconds()) < 60

    def test_zero_ttl_means_no_expiry(self, settings, owner):
        settings.SHARE_LINK_TTL_DAYS = 0

        link = SharedLink.issue(owner, SharedLink.ShareType.CHAT)

        assert link.expires_at is None

    def test_valid_link_is_reused(self, settings, owner):
        settings.SHARE_LINK_TTL_DAYS = 30

        first = SharedLink.issue(owner, SharedLink.ShareType.CHAT)
        second = SharedLink.issue(owner, SharedLink.ShareType.CHAT)

        assert first.pk == second.pk

    def test_expired_link_is_not_reused(self, settings, owner):
        """Reusing an expired link would hand the user a URL that answers 410."""
        settings.SHARE_LINK_TTL_DAYS = 30
        stale = SharedLink.objects.create(
            user=owner,
            share_type=SharedLink.ShareType.CHAT,
            token=SharedLink.generate_token(),
            expires_at=timezone.now() - timedelta(days=1),
        )

        fresh = SharedLink.issue(owner, SharedLink.ShareType.CHAT)

        assert fresh.pk != stale.pk
        assert fresh.is_valid

    def test_revoked_link_is_not_reused(self, settings, owner):
        settings.SHARE_LINK_TTL_DAYS = 30
        revoked = SharedLink.objects.create(
            user=owner,
            share_type=SharedLink.ShareType.CHAT,
            token=SharedLink.generate_token(),
            is_active=False,
        )

        fresh = SharedLink.issue(owner, SharedLink.ShareType.CHAT)

        assert fresh.pk != revoked.pk
        assert fresh.is_active

    def test_document_links_are_per_document(self, settings, owner, document, tmp_path):
        settings.SHARE_LINK_TTL_DAYS = 30
        second_doc = Document.objects.create(
            user=owner,
            filename='other.txt',
            original_filename='other.txt',
            file_path=str(tmp_path / 'other.txt'),
            file_type='txt',
            size=10,
            status=Document.Status.COMPLETED,
        )

        first = SharedLink.issue(owner, SharedLink.ShareType.DOCUMENT, document=document)
        second = SharedLink.issue(owner, SharedLink.ShareType.DOCUMENT, document=second_doc)

        assert first.pk != second.pk

    def test_expired_link_answers_410(self, client, owner):
        link = SharedLink.objects.create(
            user=owner,
            share_type=SharedLink.ShareType.CHAT,
            token=SharedLink.generate_token(),
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = client.get(f'/s/{link.token}/')

        assert response.status_code == 410


# ---------------------------------------------------------------------------
# Creation endpoints
# ---------------------------------------------------------------------------


class TestCreateShareLink:
    def test_chat_link_response_carries_expiry(self, client, settings, owner):
        settings.SHARE_LINK_TTL_DAYS = 30
        client.force_login(owner)

        response = client.post(reverse('core:share_chat'))

        assert response.status_code == 200
        payload = response.json()
        assert payload['expires_at'] is not None
        assert SharedLink.objects.get(token=payload['token']).expires_at is not None

    def test_unlimited_link_reports_null_expiry(self, client, settings, owner):
        settings.SHARE_LINK_TTL_DAYS = 0
        client.force_login(owner)

        response = client.post(reverse('core:share_chat'))

        assert response.json()['expires_at'] is None

    def test_document_link_requires_ownership(self, client, other_user, document):
        client.force_login(other_user)

        response = client.post(reverse('core:share_document', args=[document.pk]))

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


class TestRevokeShareLink:
    def _url(self, token):
        return reverse('core:revoke_share', args=[token])

    def test_owner_can_revoke(self, client, owner):
        link = SharedLink.issue(owner, SharedLink.ShareType.CHAT)
        client.force_login(owner)

        response = client.post(self._url(link.token))

        assert response.status_code == 302
        link.refresh_from_db()
        assert link.is_active is False

    def test_revoked_link_answers_410(self, client, owner):
        link = SharedLink.issue(owner, SharedLink.ShareType.CHAT)
        client.force_login(owner)
        client.post(self._url(link.token))
        client.logout()

        response = client.get(f'/s/{link.token}/')

        assert response.status_code == 410

    def test_other_user_cannot_revoke(self, client, owner, other_user):
        """404, not 403: a 403 would confirm the token exists."""
        link = SharedLink.issue(owner, SharedLink.ShareType.CHAT)
        client.force_login(other_user)

        response = client.post(self._url(link.token))

        assert response.status_code == 404
        link.refresh_from_db()
        assert link.is_active is True

    def test_anonymous_cannot_revoke(self, client, owner):
        link = SharedLink.issue(owner, SharedLink.ShareType.CHAT)

        response = client.post(self._url(link.token))

        assert response.status_code == 302
        assert '/accounts/login/' in response['Location']
        link.refresh_from_db()
        assert link.is_active is True

    def test_get_is_rejected(self, client, owner):
        link = SharedLink.issue(owner, SharedLink.ShareType.CHAT)
        client.force_login(owner)

        response = client.get(self._url(link.token))

        assert response.status_code == 405
        link.refresh_from_db()
        assert link.is_active is True

    def test_unknown_token_gets_404(self, client, owner):
        client.force_login(owner)

        response = client.post(self._url('no-such-token'))

        assert response.status_code == 404

    def test_revoke_is_idempotent(self, client, owner):
        link = SharedLink.issue(owner, SharedLink.ShareType.CHAT)
        client.force_login(owner)

        client.post(self._url(link.token))
        response = client.post(self._url(link.token))

        assert response.status_code == 302
        link.refresh_from_db()
        assert link.is_active is False

    def test_json_client_gets_json(self, client, owner):
        link = SharedLink.issue(owner, SharedLink.ShareType.CHAT)
        client.force_login(owner)

        response = client.post(self._url(link.token), headers={'accept': 'application/json'})

        assert response.status_code == 200
        assert response.json() == {'revoked': True}


# ---------------------------------------------------------------------------
# Profile listing
# ---------------------------------------------------------------------------


class TestProfileShareLinks:
    def test_active_link_is_listed_with_revoke_button(self, client, settings, owner, document):
        settings.SHARE_LINK_TTL_DAYS = 30
        link = SharedLink.issue(owner, SharedLink.ShareType.DOCUMENT, document=document)
        client.force_login(owner)

        body = client.get(reverse('core:profile')).content.decode()

        assert 'shared.txt' in body
        assert reverse('core:revoke_share', args=[link.token]) in body

    def test_expired_and_revoked_links_are_hidden(self, client, owner):
        expired = SharedLink.objects.create(
            user=owner,
            share_type=SharedLink.ShareType.CHAT,
            token=SharedLink.generate_token(),
            expires_at=timezone.now() - timedelta(days=1),
        )
        revoked = SharedLink.objects.create(
            user=owner,
            share_type=SharedLink.ShareType.CHAT,
            token=SharedLink.generate_token(),
            is_active=False,
        )
        client.force_login(owner)

        body = client.get(reverse('core:profile')).content.decode()

        assert expired.token not in body
        assert revoked.token not in body
        assert 'Активных публичных ссылок нет' in body

    def test_other_users_links_are_not_listed(self, client, owner, other_user):
        foreign = SharedLink.issue(other_user, SharedLink.ShareType.CHAT)
        client.force_login(owner)

        body = client.get(reverse('core:profile')).content.decode()

        assert foreign.token not in body
