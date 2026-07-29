"""
Tests for document re-indexing (queue_reindex / reindex_now / views / command).

Recovering a failed document must not require re-uploading the file, and must
not leave a second copy of its chunks behind.
"""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from core.indexing import (
    DocumentBusyError,
    DocumentFileMissingError,
    IndexingQueueFullError,
    queue_reindex,
    reindex_now,
)
from core.models import Chunk, Document

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return User.objects.create_user(username='reindex_owner', password='pass12345')


@pytest.fixture
def other_user():
    return User.objects.create_user(username='reindex_other', password='pass12345')


@pytest.fixture
def make_document(owner, tmp_path):
    def _make(status=Document.Status.ERROR, user=None, on_disk=True, **extra):
        source = tmp_path / f'doc-{status}-{extra.get("suffix", "")}.txt'
        if on_disk:
            source.write_text('содержимое документа', encoding='utf-8')
        extra.pop('suffix', None)
        return Document.objects.create(
            user=user or owner,
            filename=source.name,
            original_filename='original.txt',
            file_path=str(source),
            file_type='txt',
            size=42,
            status=status,
            error_message='Ollama недоступна' if status == Document.Status.ERROR else '',
            processed_chunks=3,
            total_chunks=7,
            **extra,
        )

    return _make


# ---------------------------------------------------------------------------
# queue_reindex
# ---------------------------------------------------------------------------


class TestQueueReindex:
    def test_errored_document_is_queued_and_reset(self, make_document):
        document = make_document(status=Document.Status.ERROR)

        with patch('core.indexing.start_indexing_async') as mock_start:
            queue_reindex(document)

        mock_start.assert_called_once_with(document.pk)
        document.refresh_from_db()
        assert document.status == Document.Status.PENDING
        assert document.error_message == ''
        assert document.processed_chunks == 0
        assert document.total_chunks == 0
        assert document.processed_at is None

    def test_completed_document_can_be_reindexed(self, make_document):
        document = make_document(status=Document.Status.COMPLETED)

        with patch('core.indexing.start_indexing_async') as mock_start:
            queue_reindex(document)

        mock_start.assert_called_once_with(document.pk)

    def test_stale_chunks_are_discarded(self, make_document, mock_rag_pipeline):
        """Old rows and vectors must go, otherwise a re-index duplicates them."""
        document = make_document(status=Document.Status.COMPLETED)
        for i in range(3):
            Chunk.objects.create(document=document, content=f'chunk {i}', chunk_index=i, chroma_id=f'old-{i}')

        with patch('core.indexing.start_indexing_async'):
            queue_reindex(document)

        assert Chunk.objects.filter(document=document).count() == 0
        mock_rag_pipeline.delete_document_from_chroma.assert_called_once_with(document.pk)

    @pytest.mark.parametrize('busy_status', [Document.Status.PENDING, Document.Status.PROCESSING])
    def test_already_queued_document_is_rejected(self, make_document, busy_status):
        document = make_document(status=busy_status)

        with patch('core.indexing.start_indexing_async') as mock_start, pytest.raises(DocumentBusyError):
            queue_reindex(document)

        mock_start.assert_not_called()
        document.refresh_from_db()
        assert document.status == busy_status

    def test_missing_file_is_rejected(self, make_document):
        document = make_document(status=Document.Status.ERROR, on_disk=False)

        with patch('core.indexing.start_indexing_async') as mock_start, pytest.raises(DocumentFileMissingError):
            queue_reindex(document)

        mock_start.assert_not_called()
        document.refresh_from_db()
        # Status untouched: nothing was claimed.
        assert document.status == Document.Status.ERROR

    def test_full_queue_leaves_document_in_error(self, make_document):
        document = make_document(status=Document.Status.ERROR)

        with (
            patch('core.indexing.start_indexing_async', side_effect=IndexingQueueFullError('full')),
            pytest.raises(IndexingQueueFullError),
        ):
            queue_reindex(document)

        document.refresh_from_db()
        assert document.status == Document.Status.ERROR
        assert 'Очередь индексации переполнена' in document.error_message


class TestReindexNow:
    def test_runs_pipeline_synchronously(self, make_document, mock_rag_pipeline):
        document = make_document(status=Document.Status.ERROR)

        chunks = reindex_now(document)

        assert chunks == mock_rag_pipeline.process_document.return_value
        mock_rag_pipeline.process_document.assert_called_once()

    def test_busy_document_is_rejected(self, make_document, mock_rag_pipeline):
        document = make_document(status=Document.Status.PROCESSING)

        with pytest.raises(DocumentBusyError):
            reindex_now(document)

        mock_rag_pipeline.process_document.assert_not_called()


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------


class TestApiReindex:
    def _url(self, doc_id):
        return reverse('core:api_doc_reindex', args=[doc_id])

    def test_owner_gets_202(self, client, owner, make_document):
        document = make_document(status=Document.Status.ERROR)
        client.force_login(owner)

        with patch('core.indexing.start_indexing_async') as mock_start:
            response = client.post(self._url(document.pk))

        assert response.status_code == 202
        assert response.json()['status'] == Document.Status.PENDING
        mock_start.assert_called_once_with(document.pk)

    def test_requires_authentication(self, client, make_document):
        document = make_document(status=Document.Status.ERROR)

        response = client.post(self._url(document.pk))

        assert response.status_code in (401, 403)

    def test_non_owner_gets_403(self, client, other_user, make_document):
        document = make_document(status=Document.Status.ERROR)
        client.force_login(other_user)

        with patch('core.indexing.start_indexing_async') as mock_start:
            response = client.post(self._url(document.pk))

        assert response.status_code == 403
        mock_start.assert_not_called()

    def test_shared_document_of_another_user_gets_403(self, client, other_user, make_document):
        """A shared document is searchable by everyone but re-indexable only by its owner."""
        document = make_document(status=Document.Status.ERROR, is_shared=True)
        client.force_login(other_user)

        response = client.post(self._url(document.pk))

        assert response.status_code == 403

    def test_busy_document_gets_409(self, client, owner, make_document):
        document = make_document(status=Document.Status.PROCESSING)
        client.force_login(owner)

        response = client.post(self._url(document.pk))

        assert response.status_code == 409

    def test_missing_file_gets_409(self, client, owner, make_document):
        document = make_document(status=Document.Status.ERROR, on_disk=False)
        client.force_login(owner)

        response = client.post(self._url(document.pk))

        assert response.status_code == 409
        assert 'не найден' in response.json()['error']

    def test_full_queue_gets_503(self, client, owner, make_document):
        document = make_document(status=Document.Status.ERROR)
        client.force_login(owner)

        with patch('core.indexing.start_indexing_async', side_effect=IndexingQueueFullError('full')):
            response = client.post(self._url(document.pk))

        assert response.status_code == 503
        document.refresh_from_db()
        assert document.status == Document.Status.ERROR

    def test_unknown_document_gets_404(self, client, owner):
        client.force_login(owner)

        response = client.post(self._url(999999))

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# HTMX
# ---------------------------------------------------------------------------


class TestHtmxReindex:
    def _url(self, doc_id):
        return reverse('core:htmx_doc_reindex', args=[doc_id])

    def test_owner_gets_refreshed_doc_list(self, client, owner, make_document):
        document = make_document(status=Document.Status.ERROR)
        client.force_login(owner)

        with patch('core.indexing.start_indexing_async') as mock_start:
            response = client.post(self._url(document.pk))

        assert response.status_code == 200
        assert 'переиндексацию' in response.content.decode()
        mock_start.assert_called_once_with(document.pk)

    def test_get_is_rejected(self, client, owner, make_document):
        document = make_document(status=Document.Status.ERROR)
        client.force_login(owner)

        response = client.get(self._url(document.pk))

        assert response.status_code == 405

    def test_requires_login(self, client, make_document):
        document = make_document(status=Document.Status.ERROR)

        response = client.post(self._url(document.pk))

        assert response.status_code == 302

    def test_non_owner_gets_403(self, client, other_user, make_document):
        document = make_document(status=Document.Status.ERROR)
        client.force_login(other_user)

        response = client.post(self._url(document.pk))

        assert response.status_code == 403

    def test_button_shown_for_errored_document_only(self, client, owner, make_document):
        errored = make_document(status=Document.Status.ERROR, suffix='err')
        processing = make_document(status=Document.Status.PROCESSING, suffix='proc')
        client.force_login(owner)

        body = client.get(reverse('core:htmx_doc_list')).content.decode()

        assert reverse('core:htmx_doc_reindex', args=[errored.pk]) in body
        assert reverse('core:htmx_doc_reindex', args=[processing.pk]) not in body

    def test_busy_document_gets_409_with_message(self, client, owner, make_document):
        document = make_document(status=Document.Status.PROCESSING)
        client.force_login(owner)

        response = client.post(self._url(document.pk))

        assert response.status_code == 409
        assert 'очереди' in response.content.decode()


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------


class TestReindexCommand:
    def test_reindexes_errored_documents(self, make_document, mock_rag_pipeline):
        from django.core.management import call_command

        make_document(status=Document.Status.ERROR, suffix='a')
        make_document(status=Document.Status.COMPLETED, suffix='b')

        call_command('reindex_documents')

        assert mock_rag_pipeline.process_document.call_count == 1

    def test_dry_run_changes_nothing(self, make_document, mock_rag_pipeline):
        from django.core.management import call_command

        document = make_document(status=Document.Status.ERROR)

        call_command('reindex_documents', '--dry-run')

        mock_rag_pipeline.process_document.assert_not_called()
        document.refresh_from_db()
        assert document.status == Document.Status.ERROR

    def test_id_filter_overrides_status(self, make_document, mock_rag_pipeline):
        from django.core.management import call_command

        make_document(status=Document.Status.ERROR, suffix='a')
        target = make_document(status=Document.Status.COMPLETED, suffix='b')

        call_command('reindex_documents', '--id', str(target.pk))

        assert mock_rag_pipeline.process_document.call_count == 1
        assert mock_rag_pipeline.process_document.call_args[0][0].pk == target.pk

    def test_unknown_id_raises(self, mock_rag_pipeline):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match='not found'):
            call_command('reindex_documents', '--id', '999999')

    def test_missing_file_is_skipped_not_fatal(self, make_document, mock_rag_pipeline):
        from django.core.management import call_command

        make_document(status=Document.Status.ERROR, on_disk=False, suffix='gone')
        ok = make_document(status=Document.Status.ERROR, suffix='ok')

        call_command('reindex_documents')

        assert mock_rag_pipeline.process_document.call_count == 1
        assert mock_rag_pipeline.process_document.call_args[0][0].pk == ok.pk
