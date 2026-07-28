"""Tests for core views (auth, UI pages, sharing, HTMX upload)."""

import os
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from core.indexing import IndexingQueueFullError
from core.models import ChatMessage, Document, SharedLink, UserProfile

# Small limit so tests never build a real multi-MB payload.
TEST_MAX_UPLOAD_SIZE = 1024
PDF_HEADER = b'%PDF-1.4\n%%EOF\n'


def _pdf_upload(size: int, name: str = 'doc.pdf') -> SimpleUploadedFile:
    """Build a PDF-looking upload of exactly `size` bytes."""
    content = (PDF_HEADER + b'A' * size)[:size]
    return SimpleUploadedFile(name, content, content_type='application/pdf')


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def user(db):
    u = User.objects.create_user(username='testuser', email='test@example.com', password='testpass123')
    u.is_active = True
    u.save()
    UserProfile.objects.create(user=u, is_email_verified=True)
    return u


@pytest.fixture
def auth_client(client, user):
    client.login(username='testuser', password='testpass123')
    return client


@pytest.fixture
def document(user):
    return Document.objects.create(
        user=user,
        filename='test_abc.pdf',
        original_filename='test.pdf',
        file_path='/tmp/test_abc.pdf',
        file_type='pdf',
        size=1024,
        status='completed',
    )


# ============================================================================
# Auth pages (unauthenticated)
# ============================================================================


class TestAuthPages:
    def test_login_page(self, client, db):
        resp = client.get('/accounts/login/')
        assert resp.status_code == 200
        assert 'Вход' in resp.content.decode()

    def test_register_page(self, client, db):
        resp = client.get('/accounts/register/')
        assert resp.status_code == 200
        assert 'Регистрация' in resp.content.decode()

    def test_password_reset_page(self, client, db):
        resp = client.get('/accounts/password-reset/')
        assert resp.status_code == 200
        assert 'Сброс пароля' in resp.content.decode()

    def test_resend_verification_page(self, client, db):
        resp = client.get('/accounts/resend-verification/')
        assert resp.status_code == 200


# ============================================================================
# Login / Logout
# ============================================================================


class TestLoginLogout:
    def test_login_success(self, client, user):
        resp = client.post(
            '/accounts/login/',
            {
                'username': 'testuser',
                'password': 'testpass123',
            },
        )
        assert resp.status_code == 302  # redirect to index

    def test_login_wrong_password(self, client, user):
        resp = client.post(
            '/accounts/login/',
            {
                'username': 'testuser',
                'password': 'wrongpass',
            },
        )
        assert resp.status_code == 200  # stays on login page

    def test_logout(self, auth_client):
        resp = auth_client.get('/accounts/logout/')
        assert resp.status_code == 302

    def test_authenticated_login_redirects(self, auth_client):
        resp = auth_client.get('/accounts/login/')
        assert resp.status_code == 302  # already logged in


# ============================================================================
# Protected pages (require login)
# ============================================================================


class TestProtectedPages:
    def test_index_requires_login(self, client, db):
        resp = client.get('/')
        assert resp.status_code == 302
        assert '/accounts/login/' in resp.url

    def test_docs_requires_login(self, client, db):
        resp = client.get('/docs/')
        assert resp.status_code == 302

    def test_profile_requires_login(self, client, db):
        resp = client.get('/accounts/profile/')
        assert resp.status_code == 302

    def test_index_page(self, auth_client):
        resp = auth_client.get('/')
        assert resp.status_code == 200
        assert 'ROoP' in resp.content.decode()

    def test_docs_page(self, auth_client):
        resp = auth_client.get('/docs/')
        assert resp.status_code == 200

    def test_profile_page(self, auth_client):
        resp = auth_client.get('/accounts/profile/')
        assert resp.status_code == 200
        assert 'testuser' in resp.content.decode()


# ============================================================================
# HTMX endpoints
# ============================================================================


class TestHtmxEndpoints:
    def test_stats(self, auth_client):
        resp = auth_client.get('/htmx/stats/')
        assert resp.status_code == 200

    def test_doc_list(self, auth_client):
        resp = auth_client.get('/htmx/docs/')
        assert resp.status_code == 200

    def test_chat_history(self, auth_client):
        resp = auth_client.get('/htmx/chat/history/')
        assert resp.status_code == 200

    def test_clear_chat(self, auth_client, user):
        ChatMessage.objects.create(user=user, role='user', content='Hello')
        resp = auth_client.post('/htmx/chat/clear/')
        assert resp.status_code == 200
        assert ChatMessage.objects.filter(user=user).count() == 0


# ============================================================================
# HTMX upload — size limit and queue backpressure
# ============================================================================


@pytest.mark.django_db
class TestHtmxUploadLimits:
    def test_upload_under_limit_is_queued(self, auth_client, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.htmx.start_indexing_async') as mock_start:
            resp = auth_client.post('/htmx/upload/', {'file': _pdf_upload(TEST_MAX_UPLOAD_SIZE - 1)})

        assert resp.status_code == 200
        mock_start.assert_called_once()
        assert Document.objects.count() == 1

    def test_upload_exactly_at_limit_is_queued(self, auth_client, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.htmx.start_indexing_async') as mock_start:
            resp = auth_client.post('/htmx/upload/', {'file': _pdf_upload(TEST_MAX_UPLOAD_SIZE)})

        assert resp.status_code == 200
        mock_start.assert_called_once()

    def test_upload_over_limit_shows_error(self, auth_client, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.htmx.start_indexing_async') as mock_start:
            resp = auth_client.post('/htmx/upload/', {'file': _pdf_upload(TEST_MAX_UPLOAD_SIZE + 500)})

        assert resp.status_code == 200  # HTMX partial carries the error inline
        body = resp.content.decode()
        assert 'слишком большой' in body
        mock_start.assert_not_called()

    def test_over_limit_creates_no_document(self, auth_client, settings):
        """A rejected file must not leave a Document row behind."""
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.htmx.start_indexing_async'):
            auth_client.post('/htmx/upload/', {'file': _pdf_upload(TEST_MAX_UPLOAD_SIZE + 500)})

        assert Document.objects.count() == 0

    def test_error_partial_has_no_stack_trace(self, auth_client, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        resp = auth_client.post('/htmx/upload/', {'file': _pdf_upload(TEST_MAX_UPLOAD_SIZE + 500)})

        body = resp.content.decode()
        assert 'Traceback' not in body
        assert 'core/views/helpers.py' not in body

    def test_queue_full_returns_503_and_marks_error(self, auth_client, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.htmx.start_indexing_async', side_effect=IndexingQueueFullError('full')):
            resp = auth_client.post('/htmx/upload/', {'file': _pdf_upload(100)})

        assert resp.status_code == 503
        document = Document.objects.get()
        assert document.status == Document.Status.ERROR
        assert document.error_message

    def test_queue_full_keeps_uploaded_file(self, auth_client, settings):
        """The file must survive a queue-full rejection so the user can retry."""
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.htmx.start_indexing_async', side_effect=IndexingQueueFullError('full')):
            auth_client.post('/htmx/upload/', {'file': _pdf_upload(100)})

        document = Document.objects.get()
        assert os.path.exists(document.file_path)


# ============================================================================
# Sharing
# ============================================================================


class TestSharing:
    def test_create_share_chat(self, auth_client, user):
        resp = auth_client.post('/share/chat/', content_type='application/json')
        assert resp.status_code == 200
        data = resp.json()
        assert 'url' in data
        assert 'token' in data

    def test_create_share_document(self, auth_client, document):
        resp = auth_client.post(f'/share/doc/{document.id}/', content_type='application/json')
        assert resp.status_code == 200
        data = resp.json()
        assert 'url' in data

    def test_shared_chat_view(self, client, user):
        link = SharedLink.objects.create(
            user=user,
            share_type='chat',
            token=SharedLink.generate_token(),
        )
        resp = client.get(f'/s/{link.token}/')
        assert resp.status_code == 200
        assert 'testuser' in resp.content.decode()

    def test_shared_document_view(self, client, user, document):
        link = SharedLink.objects.create(
            user=user,
            share_type='document',
            document=document,
            token=SharedLink.generate_token(),
        )
        resp = client.get(f'/s/{link.token}/')
        assert resp.status_code == 200
        assert 'test.pdf' in resp.content.decode()

    def test_expired_shared_link(self, client, user):
        from datetime import timedelta

        from django.utils import timezone

        link = SharedLink.objects.create(
            user=user,
            share_type='chat',
            token=SharedLink.generate_token(),
            expires_at=timezone.now() - timedelta(hours=1),
        )
        resp = client.get(f'/s/{link.token}/')
        assert resp.status_code == 410

    def test_inactive_shared_link(self, client, user):
        link = SharedLink.objects.create(
            user=user,
            share_type='chat',
            token=SharedLink.generate_token(),
            is_active=False,
        )
        resp = client.get(f'/s/{link.token}/')
        assert resp.status_code == 410

    def test_nonexistent_shared_link(self, client, db):
        resp = client.get('/s/nonexistent-token-12345/')
        assert resp.status_code == 404
