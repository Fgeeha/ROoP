"""
Tests for Stage 2 reliability fixes:
  - OllamaBackend timeout applied (no infinite hang)
  - Embed batching by EMBED_BATCH_SIZE
  - Exception in indexing thread → status=error (not stuck in processing)
  - recover_stuck_documents command → processing → error
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# OllamaBackend — timeout is passed to ollama.Client
# ---------------------------------------------------------------------------


class TestOllamaBackendTimeout:
    def test_timeout_passed_to_client(self):
        """ollama.Client must be created with the configured timeout."""
        with (
            patch('core.rag.backends.ollama.Client') as mock_client_cls,
            patch('core.rag.backends.settings') as mock_settings,
        ):
            mock_settings.OLLAMA_REQUEST_TIMEOUT = 120
            mock_settings.LLM_BACKEND = 'ollama'
            mock_settings.OLLAMA_URL = 'http://localhost:11434'

            from core.rag.backends import OllamaBackend

            OllamaBackend(url='http://localhost:11434', timeout=120)

            mock_client_cls.assert_called_once_with(host='http://localhost:11434', timeout=120)

    def test_default_timeout_is_300(self):
        """OllamaBackend default timeout must be 300 seconds."""
        with patch('core.rag.backends.ollama.Client'):
            from core.rag.backends import OllamaBackend

            backend = OllamaBackend(url='http://x')
            assert backend._timeout == 300

    def test_create_llm_backend_passes_timeout_from_settings(self):
        """create_llm_backend() must read OLLAMA_REQUEST_TIMEOUT from settings."""
        with (
            patch('core.rag.backends.ollama.Client') as mock_client_cls,
            patch('core.rag.backends.settings') as mock_settings,
        ):
            mock_settings.LLM_BACKEND = 'ollama'
            mock_settings.OLLAMA_URL = 'http://ollama:11434'
            mock_settings.OLLAMA_REQUEST_TIMEOUT = 42

            from core.rag.backends import create_llm_backend

            create_llm_backend()

            mock_client_cls.assert_called_once_with(host='http://ollama:11434', timeout=42)

    def test_timeout_exception_propagates(self):
        """A timeout raised by ollama.Client.embed() must propagate as an exception."""
        import httpx

        with patch('core.rag.backends.ollama.Client') as mock_client_cls:
            mock_client = MagicMock()
            mock_client.embed.side_effect = httpx.ReadTimeout('timed out')
            mock_client_cls.return_value = mock_client

            from core.rag.backends import OllamaBackend

            backend = OllamaBackend(url='http://x', timeout=1)
            with pytest.raises(httpx.ReadTimeout):
                backend.embed(texts=['hello'], model='nomic-embed-text')


# ---------------------------------------------------------------------------
# store.add_chunks_to_chroma — batching
# ---------------------------------------------------------------------------


class TestEmbedBatching:
    """backend.embed() must be called multiple times when chunks > EMBED_BATCH_SIZE."""

    def _make_collection(self):
        col = MagicMock()
        col.add.return_value = None
        return col

    def _make_backend(self, embed_dim: int = 4):
        backend = MagicMock()
        # Return a fresh batch of fake embeddings for each call.
        backend.embed.side_effect = lambda texts, model: [[0.1] * embed_dim for _ in texts]
        return backend

    def test_embed_called_multiple_times_for_large_input(self):
        """30 chunks with batch_size=10 must trigger 3 embed() calls."""
        from core.rag.store import add_chunks_to_chroma

        chunks = [f'chunk {i}' for i in range(30)]
        col = self._make_collection()
        backend = self._make_backend()

        with patch('core.rag.store.settings') as s:
            s.EMBED_BATCH_SIZE = 10
            s.EMBED_MODEL = 'test-model'

            add_chunks_to_chroma(col, backend, chunks, document_id=1, filename='f.pdf')

        assert backend.embed.call_count == 3

    def test_embed_called_once_when_chunks_fit_in_one_batch(self):
        """5 chunks with batch_size=10 must trigger exactly 1 embed() call."""
        from core.rag.store import add_chunks_to_chroma

        chunks = [f'chunk {i}' for i in range(5)]
        col = self._make_collection()
        backend = self._make_backend()

        with patch('core.rag.store.settings') as s:
            s.EMBED_BATCH_SIZE = 10
            s.EMBED_MODEL = 'test-model'

            add_chunks_to_chroma(col, backend, chunks, document_id=1, filename='f.pdf')

        assert backend.embed.call_count == 1

    def test_each_embed_call_receives_correct_batch_size(self):
        """Each embed() call must not exceed EMBED_BATCH_SIZE texts."""
        from core.rag.store import add_chunks_to_chroma

        chunks = [f'chunk {i}' for i in range(25)]
        col = self._make_collection()
        backend = self._make_backend()

        with patch('core.rag.store.settings') as s:
            s.EMBED_BATCH_SIZE = 10
            s.EMBED_MODEL = 'test-model'

            add_chunks_to_chroma(col, backend, chunks, document_id=1, filename='f.pdf')

        batch_sizes = [len(c.kwargs['texts']) for c in backend.embed.call_args_list]
        assert batch_sizes == [10, 10, 5]

    def test_progress_callback_called_after_each_batch(self):
        """progress_callback(done, total) must be called once per embed batch."""
        from core.rag.store import add_chunks_to_chroma

        chunks = [f'chunk {i}' for i in range(15)]
        col = self._make_collection()
        backend = self._make_backend()
        calls_received = []

        def progress(done, total):
            calls_received.append((done, total))

        with patch('core.rag.store.settings') as s:
            s.EMBED_BATCH_SIZE = 10
            s.EMBED_MODEL = 'test-model'

            add_chunks_to_chroma(col, backend, chunks, document_id=1, filename='f.pdf', progress_callback=progress)

        assert calls_received == [(10, 15), (15, 15)]

    def test_all_embeddings_stored_in_chromadb(self):
        """All generated embeddings must end up in ChromaDB, in order."""
        from core.rag.store import add_chunks_to_chroma

        chunks = [f'chunk {i}' for i in range(12)]
        col = self._make_collection()
        backend = self._make_backend(embed_dim=3)

        with patch('core.rag.store.settings') as s:
            s.EMBED_BATCH_SIZE = 10
            s.EMBED_MODEL = 'test-model'

            add_chunks_to_chroma(col, backend, chunks, document_id=7, filename='f.pdf')

        # collection.add() is batched by 100; 12 chunks fit in one add() call.
        assert col.add.call_count == 1
        embeddings_stored = col.add.call_args.kwargs['embeddings']
        assert len(embeddings_stored) == 12


# ---------------------------------------------------------------------------
# Indexing thread — timeout/exception → status=error
# ---------------------------------------------------------------------------


class TestIndexingThreadReliability:
    """Exceptions (including timeouts) must transition document to error, not freeze it."""

    def _run_thread_with_error(self, error, doc_pk=99):
        """Run _run_indexing_in_thread with process_document raising error."""

        mock_doc = MagicMock()
        mock_doc.id = doc_pk
        mock_doc.status = 'processing'

        mock_pipeline = MagicMock()
        mock_pipeline.process_document.side_effect = error

        with (
            patch('core.indexing.Document') as mock_document_cls,
            patch('core.indexing.RAGPipeline') as mock_pipeline_cls,
            patch('core.indexing.connection'),
        ):
            mock_document_cls.objects.get.return_value = mock_doc
            mock_document_cls.Status.PROCESSING = 'processing'
            mock_document_cls.Status.ERROR = 'error'
            mock_document_cls.objects.filter.return_value = MagicMock()
            mock_pipeline_cls.get_instance.return_value = mock_pipeline

            from core.indexing import _run_indexing_in_thread

            _run_indexing_in_thread(doc_pk)

            return mock_document_cls.objects.filter.return_value

    def test_timeout_exception_sets_status_to_error(self):
        """An httpx.ReadTimeout from embed() must transition document to error."""
        import httpx

        mock_qs = self._run_thread_with_error(httpx.ReadTimeout('timed out'))
        mock_qs.update.assert_called_once()
        update_kwargs = mock_qs.update.call_args.kwargs
        assert update_kwargs['status'] == 'error'

    def test_generic_exception_sets_status_to_error(self):
        """Any unexpected exception must set status to error."""
        mock_qs = self._run_thread_with_error(RuntimeError('OOM'))
        mock_qs.update.assert_called_once()
        assert mock_qs.update.call_args.kwargs['status'] == 'error'

    def test_error_message_contains_exception_text(self):
        """The error_message field must contain the exception description."""
        mock_qs = self._run_thread_with_error(ValueError('disk full'))
        error_message = mock_qs.update.call_args.kwargs.get('error_message', '')
        assert 'disk full' in error_message

    def test_connection_closed_on_timeout(self):
        """DB connection must be closed even when embed() times out."""
        import httpx

        from core.indexing import _run_indexing_in_thread

        mock_doc = MagicMock()
        mock_doc.id = 5
        mock_doc.status = 'processing'
        mock_pipeline = MagicMock()
        mock_pipeline.process_document.side_effect = httpx.ReadTimeout('timeout')

        with (
            patch('core.indexing.Document') as mock_document_cls,
            patch('core.indexing.RAGPipeline') as mock_pipeline_cls,
            patch('core.indexing.connection') as mock_conn,
        ):
            mock_document_cls.objects.get.return_value = mock_doc
            mock_document_cls.Status.PROCESSING = 'processing'
            mock_document_cls.objects.filter.return_value = MagicMock()
            mock_pipeline_cls.get_instance.return_value = mock_pipeline

            _run_indexing_in_thread(5)

        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# recover_stuck_documents management command
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRecoverStuckDocuments:
    """recover_stuck_documents must flip processing → error at startup."""

    def test_processing_document_becomes_error(self, db):
        from django.contrib.auth.models import User
        from django.core.management import call_command

        from core.models import Document

        user = User.objects.create_user(username='recovery_test', password='x')
        doc = Document.objects.create(
            user=user,
            filename='stuck.pdf',
            original_filename='stuck.pdf',
            file_path='/tmp/stuck.pdf',
            file_type='pdf',
            size=100,
            status=Document.Status.PROCESSING,
        )

        call_command('recover_stuck_documents')

        doc.refresh_from_db()
        assert doc.status == Document.Status.ERROR
        assert doc.error_message  # must not be empty

    def test_completed_document_not_touched(self, db):
        from django.contrib.auth.models import User
        from django.core.management import call_command

        from core.models import Document

        user = User.objects.create_user(username='recovery_test2', password='x')
        doc = Document.objects.create(
            user=user,
            filename='done.pdf',
            original_filename='done.pdf',
            file_path='/tmp/done.pdf',
            file_type='pdf',
            size=100,
            status=Document.Status.COMPLETED,
        )

        call_command('recover_stuck_documents')

        doc.refresh_from_db()
        assert doc.status == Document.Status.COMPLETED

    def test_pending_document_not_touched(self, db):
        from django.contrib.auth.models import User
        from django.core.management import call_command

        from core.models import Document

        user = User.objects.create_user(username='recovery_test3', password='x')
        doc = Document.objects.create(
            user=user,
            filename='pending.pdf',
            original_filename='pending.pdf',
            file_path='/tmp/pending.pdf',
            file_type='pdf',
            size=100,
            status=Document.Status.PENDING,
        )

        call_command('recover_stuck_documents')

        doc.refresh_from_db()
        assert doc.status == Document.Status.PENDING
