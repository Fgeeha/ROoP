"""
Tests for Stage 3: indexing progress (processed_chunks / total_chunks).

  - progress_callback in engine.process_document() updates fields via
    point UPDATE (filter().update()), not full save()
  - doc_status view reflects progress when status=processing
  - full cycle: pending → processing (with progress) → completed
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# engine.process_document — progress callback wires up correctly
# ---------------------------------------------------------------------------


class TestProcessDocumentProgressCallback:
    """process_document() must write processed_chunks/total_chunks via filter().update()."""

    def _run_process_document(self, chunks=None, embed_batch_size=10):
        """
        Run process_document() with a mocked document and faked extract/chunk/embed.
        Returns the list of filter().update() calls made.
        """
        if chunks is None:
            chunks = [f'chunk {i}' for i in range(25)]

        mock_document = MagicMock()
        mock_document.id = 42
        mock_document.original_filename = 'test.pdf'
        mock_document.file_path = '/tmp/test.pdf'
        mock_document.file_type = 'pdf'
        mock_document.user_id = 1
        mock_document.is_shared = False
        mock_document.__class__ = MagicMock()

        update_calls = []

        def fake_filter_update(**kwargs):
            update_calls.append(kwargs)

        mock_qs = MagicMock()
        mock_qs.update.side_effect = lambda **kw: update_calls.append(kw)
        mock_document.__class__.objects.filter.return_value = mock_qs

        mock_chroma_ids = [f'id_{i}' for i in range(len(chunks))]

        from core.rag.engine import RAGPipeline

        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline._llm_backend = MagicMock()
        pipeline._llm_backend.embed.side_effect = lambda texts, model: [[0.1] * 4 for _ in texts]
        pipeline._collection = MagicMock()
        pipeline._collection.count.return_value = 999

        with (
            patch.object(pipeline, 'extract_text', return_value='some text'),
            patch.object(pipeline, 'chunk_text', return_value=chunks),
            patch('core.rag.engine._add_chunks_to_chroma') as mock_store_fn,
            patch('core.rag.engine.Chunk') as mock_chunk_cls,
            patch('core.rag.engine.timezone'),
            patch('core.rag.store.settings') as s,
        ):
            mock_store_fn.return_value = mock_chroma_ids
            mock_chunk_cls.objects.bulk_create.return_value = None
            s.EMBED_BATCH_SIZE = embed_batch_size
            s.EMBED_MODEL = 'test-model'

            pipeline.process_document(mock_document)

            # Capture the progress_callback passed to _add_chunks_to_chroma
            # and manually call it to simulate what store.add_chunks_to_chroma does
            captured_callback = mock_store_fn.call_args.kwargs.get('progress_callback')
            if captured_callback:
                total = len(chunks)
                for batch_end in range(embed_batch_size, total + 1, embed_batch_size):
                    captured_callback(min(batch_end, total), total)
                if total % embed_batch_size:
                    captured_callback(total, total)

        return update_calls, mock_document

    def test_total_chunks_written_before_embed(self):
        """total_chunks must be written immediately after chunk_text(), before embed starts."""
        chunks = [f'c{i}' for i in range(15)]
        update_calls, _ = self._run_process_document(chunks=chunks)

        # First update call should set total_chunks and reset processed_chunks
        first_call = update_calls[0]
        assert first_call.get('total_chunks') == 15
        assert first_call.get('processed_chunks') == 0

    def test_progress_callback_updates_processed_chunks(self):
        """Each callback invocation must write processed_chunks via filter().update()."""
        chunks = [f'c{i}' for i in range(20)]
        update_calls, _ = self._run_process_document(chunks=chunks, embed_batch_size=10)

        # Skip the first "total_chunks" call; look at subsequent ones
        progress_calls = [c for c in update_calls if 'processed_chunks' in c and c.get('processed_chunks', 0) > 0]
        assert len(progress_calls) >= 1
        # Each call must carry processed_chunks
        for c in progress_calls:
            assert 'processed_chunks' in c
            assert 'total_chunks' in c

    def test_progress_never_exceeds_total(self):
        """processed_chunks must never exceed total_chunks in any callback."""
        chunks = [f'c{i}' for i in range(25)]
        update_calls, _ = self._run_process_document(chunks=chunks, embed_batch_size=10)

        for c in update_calls:
            done = c.get('processed_chunks', 0)
            total = c.get('total_chunks', 0)
            if total > 0:
                assert done <= total, f'done={done} > total={total}'

    def test_progress_callback_passed_to_store(self):
        """add_chunks_to_chroma must be called with a non-None progress_callback."""
        chunks = [f'c{i}' for i in range(5)]
        mock_document = MagicMock()
        mock_document.id = 99
        mock_document.original_filename = 'f.pdf'
        mock_document.file_path = '/tmp/f.pdf'
        mock_document.file_type = 'pdf'
        mock_document.user_id = 1
        mock_document.is_shared = False
        mock_document.__class__ = MagicMock()
        mock_document.__class__.objects.filter.return_value = MagicMock()

        from core.rag.engine import RAGPipeline

        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline._llm_backend = MagicMock()
        pipeline._collection = MagicMock()
        pipeline._collection.count.return_value = 0

        with (
            patch.object(pipeline, 'extract_text', return_value='text'),
            patch.object(pipeline, 'chunk_text', return_value=chunks),
            patch('core.rag.engine._add_chunks_to_chroma') as mock_store,
            patch('core.rag.engine.Chunk') as mock_chunk,
            patch('core.rag.engine.timezone'),
        ):
            mock_store.return_value = [f'id_{i}' for i in range(len(chunks))]
            mock_chunk.objects.bulk_create.return_value = None

            pipeline.process_document(mock_document)

        _, kwargs = mock_store.call_args
        assert kwargs.get('progress_callback') is not None


# ---------------------------------------------------------------------------
# htmx_doc_status view — shows progress when processing
# ---------------------------------------------------------------------------


class TestDocStatusViewProgress:
    """htmx_doc_status endpoint must render progress when total_chunks > 0."""

    @pytest.fixture
    def user(self, db):
        from django.contrib.auth.models import User

        from core.models import UserProfile

        u = User.objects.create_user(username='prog_user', password='x', email='p@t.com')
        UserProfile.objects.create(user=u, is_email_verified=True)
        return u

    @pytest.mark.django_db
    def test_status_shows_progress_during_processing(self, client, user):
        from django.test import Client

        from core.models import Document

        doc = Document.objects.create(
            user=user,
            filename='prog.pdf',
            original_filename='prog.pdf',
            file_path='/tmp/prog.pdf',
            file_type='pdf',
            size=500,
            status=Document.Status.PROCESSING,
            total_chunks=30,
            processed_chunks=10,
        )

        c = Client()
        c.login(username='prog_user', password='x')
        resp = c.get(f'/htmx/docs/{doc.id}/status/')

        assert resp.status_code == 200
        content = resp.content.decode()
        assert '10' in content
        assert '30' in content

    @pytest.mark.django_db
    def test_status_shows_spinner_when_total_unknown(self, client, user):
        from django.test import Client

        from core.models import Document

        doc = Document.objects.create(
            user=user,
            filename='spin.pdf',
            original_filename='spin.pdf',
            file_path='/tmp/spin.pdf',
            file_type='pdf',
            size=500,
            status=Document.Status.PROCESSING,
            total_chunks=0,
            processed_chunks=0,
        )

        c = Client()
        c.login(username='prog_user', password='x')
        resp = c.get(f'/htmx/docs/{doc.id}/status/')

        assert resp.status_code == 200
        # Should render the spinner/generic processing message
        assert b'hx-trigger' in resp.content  # still polling

    @pytest.mark.django_db
    def test_status_shows_error_message_on_failure(self, client, user):
        from django.test import Client

        from core.models import Document

        doc = Document.objects.create(
            user=user,
            filename='err.pdf',
            original_filename='err.pdf',
            file_path='/tmp/err.pdf',
            file_type='pdf',
            size=500,
            status=Document.Status.ERROR,
            error_message='Ollama timed out after 300s',
        )

        c = Client()
        c.login(username='prog_user', password='x')
        resp = c.get(f'/htmx/docs/{doc.id}/status/')

        assert resp.status_code == 200
        assert b'Ollama timed out' in resp.content

    @pytest.mark.django_db
    def test_status_stops_polling_on_completed(self, client, user):
        from django.test import Client

        from core.models import Document

        doc = Document.objects.create(
            user=user,
            filename='done.pdf',
            original_filename='done.pdf',
            file_path='/tmp/done.pdf',
            file_type='pdf',
            size=500,
            status=Document.Status.COMPLETED,
            total_chunks=20,
            processed_chunks=20,
        )

        c = Client()
        c.login(username='prog_user', password='x')
        resp = c.get(f'/htmx/docs/{doc.id}/status/')

        assert resp.status_code == 200
        # Completed state must NOT include HTMX polling trigger
        assert b'hx-trigger' not in resp.content
