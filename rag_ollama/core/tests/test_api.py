"""Tests for REST API endpoints."""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from core.indexing import IndexingQueueFullError
from core.models import ChatMessage, Document, UserProfile

# Small limit so tests never build a real multi-MB payload.
TEST_MAX_UPLOAD_SIZE = 1024
PDF_HEADER = b'%PDF-1.4\n%%EOF\n'


def _pdf_upload(size: int, name: str = 'doc.pdf') -> SimpleUploadedFile:
    """Build a PDF-looking upload of exactly `size` bytes."""
    content = (PDF_HEADER + b'A' * size)[:size]
    return SimpleUploadedFile(name, content, content_type='application/pdf')


@pytest.fixture
def user(db):
    u = User.objects.create_user(username='apiuser', email='api@example.com', password='testpass123')
    UserProfile.objects.create(user=u, is_email_verified=True)
    return u


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def document(user):
    return Document.objects.create(
        user=user,
        filename='api_test.pdf',
        original_filename='api_test.pdf',
        file_path='/tmp/api_test.pdf',
        file_type='pdf',
        size=2048,
        status='completed',
    )


class TestDocsAPI:
    def test_list_docs(self, api_client):
        resp = api_client.get('/api/docs/')
        assert resp.status_code == 200
        assert 'docs' in resp.json()

    def test_list_docs_returns_own(self, api_client, document):
        resp = api_client.get('/api/docs/')
        data = resp.json()
        assert len(data['docs']) == 1
        assert data['docs'][0]['original_filename'] == 'api_test.pdf'

    def test_list_docs_unauthenticated(self, db):
        client = APIClient()
        resp = client.get('/api/docs/')
        assert resp.status_code in (401, 403)


class TestStatsAPI:
    def test_stats(self, api_client):
        resp = api_client.get('/api/stats/')
        assert resp.status_code == 200
        data = resp.json()
        assert 'docs_count' in data
        assert 'chunks_count' in data
        assert 'total_size' in data

    def test_stats_unauthenticated(self, db):
        client = APIClient()
        resp = client.get('/api/stats/')
        assert resp.status_code in (401, 403)


class TestChatHistoryAPI:
    def test_empty_history(self, api_client):
        resp = api_client.get('/api/chat/history/')
        assert resp.status_code == 200
        assert resp.json()['messages'] == []

    def test_history_with_messages(self, api_client, user):
        ChatMessage.objects.create(user=user, role='user', content='Q1')
        ChatMessage.objects.create(user=user, role='assistant', content='A1')
        resp = api_client.get('/api/chat/history/')
        data = resp.json()
        assert len(data['messages']) == 2

    def test_clear_chat(self, api_client, user):
        ChatMessage.objects.create(user=user, role='user', content='To delete')
        resp = api_client.post('/api/chat/clear/')
        assert resp.status_code == 200
        assert ChatMessage.objects.filter(user=user).count() == 0

    def test_history_user_isolation(self, api_client, user):
        other = User.objects.create_user(username='other', password='pass123')
        ChatMessage.objects.create(user=other, role='user', content='Other msg')
        ChatMessage.objects.create(user=user, role='user', content='My msg')
        resp = api_client.get('/api/chat/history/')
        data = resp.json()
        assert len(data['messages']) == 1
        assert data['messages'][0]['content'] == 'My msg'


class TestDocDeleteAPI:
    def test_delete_own_document(self, api_client, document):
        resp = api_client.delete(f'/api/docs/{document.id}/')
        assert resp.status_code == 200
        assert not Document.objects.filter(id=document.id).exists()

    def test_delete_other_user_document_forbidden(self, api_client, db):
        other = User.objects.create_user(username='other', password='pass123')
        doc = Document.objects.create(
            user=other,
            filename='other.pdf',
            original_filename='other.pdf',
            file_path='/tmp/other.pdf',
            file_type='pdf',
            size=100,
            status='completed',
        )
        resp = api_client.delete(f'/api/docs/{doc.id}/')
        assert resp.status_code == 403

    def test_delete_nonexistent_document(self, api_client, db):
        resp = api_client.delete('/api/docs/99999/')
        assert resp.status_code == 404


# ============================================================================
# Upload API — size limit and queue backpressure
# ============================================================================


@pytest.mark.django_db
class TestUploadAPI:
    def test_upload_under_limit_returns_202(self, api_client, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.api.start_indexing_async') as mock_start:
            resp = api_client.post(
                '/api/upload/',
                {'file': _pdf_upload(TEST_MAX_UPLOAD_SIZE - 1)},
                format='multipart',
            )

        assert resp.status_code == 202
        mock_start.assert_called_once()

    def test_upload_exactly_at_limit_returns_202(self, api_client, settings):
        """The limit is inclusive."""
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.api.start_indexing_async') as mock_start:
            resp = api_client.post(
                '/api/upload/',
                {'file': _pdf_upload(TEST_MAX_UPLOAD_SIZE)},
                format='multipart',
            )

        assert resp.status_code == 202
        mock_start.assert_called_once()

    def test_upload_over_limit_returns_413(self, api_client, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.api.start_indexing_async') as mock_start:
            resp = api_client.post(
                '/api/upload/',
                {'file': _pdf_upload(TEST_MAX_UPLOAD_SIZE + 500)},
                format='multipart',
            )

        assert resp.status_code == 413
        assert 'error' in resp.json()
        mock_start.assert_not_called()

    def test_over_limit_creates_no_document(self, api_client, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.api.start_indexing_async'):
            api_client.post(
                '/api/upload/',
                {'file': _pdf_upload(TEST_MAX_UPLOAD_SIZE + 500)},
                format='multipart',
            )

        assert Document.objects.count() == 0

    def test_bad_extension_still_returns_400(self, api_client, settings):
        """Format rejection must stay 400 — only size maps to 413."""
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        upload = SimpleUploadedFile('virus.exe', b'MZ\x90\x00', content_type='application/octet-stream')
        with patch('core.views.api.start_indexing_async') as mock_start:
            resp = api_client.post('/api/upload/', {'file': upload}, format='multipart')

        assert resp.status_code == 400
        mock_start.assert_not_called()

    def test_queue_full_returns_503(self, api_client, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.api.start_indexing_async', side_effect=IndexingQueueFullError('full')):
            resp = api_client.post('/api/upload/', {'file': _pdf_upload(100)}, format='multipart')

        assert resp.status_code == 503
        assert 'error' in resp.json()

    def test_queue_full_marks_document_error(self, api_client, settings):
        """The document must not be left waiting forever in pending."""
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        with patch('core.views.api.start_indexing_async', side_effect=IndexingQueueFullError('full')):
            api_client.post('/api/upload/', {'file': _pdf_upload(100)}, format='multipart')

        document = Document.objects.get()
        assert document.status == Document.Status.ERROR
        assert document.error_message

    def test_upload_requires_authentication(self, db, settings):
        settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
        client = APIClient()
        resp = client.post('/api/upload/', {'file': _pdf_upload(100)}, format='multipart')
        assert resp.status_code in (401, 403)
