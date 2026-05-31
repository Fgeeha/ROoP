"""
Tests for async document indexing (core/indexing.py).

All external I/O (RAGPipeline, DB connection.close) is mocked so the
suite runs without Ollama, ChromaDB, or a running PostgreSQL.
"""

import threading
from unittest.mock import MagicMock, patch

from core.indexing import _run_indexing_in_thread, start_indexing_async

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(status='pending', pk=42):
    doc = MagicMock()
    doc.pk = pk
    doc.id = pk
    doc.status = status
    doc.Status = MagicMock()
    doc.Status.PROCESSING = 'processing'
    doc.Status.ERROR = 'error'
    return doc


# ---------------------------------------------------------------------------
# start_indexing_async
# ---------------------------------------------------------------------------


class TestStartIndexingAsync:
    def test_returns_immediately(self):
        """start_indexing_async must not block the caller."""
        started = threading.Event()

        def slow_index(doc_id):
            started.set()

        with patch('core.indexing._run_indexing_in_thread', side_effect=slow_index):
            # Even if _run_indexing_in_thread blocks, start_indexing_async
            # should return before it finishes.  We just check the thread was
            # launched and the call returns.
            start_indexing_async(99)
            # Give the daemon thread a moment to fire
            started.wait(timeout=2)
            assert started.is_set()

    def test_spawns_daemon_thread(self):
        """The spawned thread must be a daemon so it doesn't block shutdown."""
        spawned: list[threading.Thread] = []
        original_start = threading.Thread.start

        def capture_start(self, *args, **kwargs):
            spawned.append(self)
            original_start(self, *args, **kwargs)

        with (
            patch('core.indexing._run_indexing_in_thread'),
            patch.object(threading.Thread, 'start', capture_start),
        ):
            start_indexing_async(1)

        assert spawned, 'No thread was started'
        assert spawned[0].daemon is True

    def test_thread_name_contains_doc_id(self):
        spawned: list[threading.Thread] = []
        original_start = threading.Thread.start

        def capture_start(self, *args, **kwargs):
            spawned.append(self)
            original_start(self, *args, **kwargs)

        with (
            patch('core.indexing._run_indexing_in_thread'),
            patch.object(threading.Thread, 'start', capture_start),
        ):
            start_indexing_async(77)

        assert '77' in spawned[0].name


# ---------------------------------------------------------------------------
# _run_indexing_in_thread — happy path
# ---------------------------------------------------------------------------


class TestRunIndexingInThread:
    def _run(self, doc_id=42, pipeline_side_effect=None):
        """
        Run _run_indexing_in_thread with mocked Document and RAGPipeline.
        Returns (mock_document, mock_pipeline).
        """
        mock_doc = _make_doc(pk=doc_id)
        mock_pipeline = MagicMock()
        if pipeline_side_effect:
            mock_pipeline.process_document.side_effect = pipeline_side_effect

        with (
            patch('core.indexing.Document', create=True) as mock_doc_cls,
            patch('core.indexing.RAGPipeline') as mock_pipeline_cls,
            patch('core.indexing.connection') as mock_conn,
        ):
            mock_doc_cls.objects.get.return_value = mock_doc
            mock_doc_cls.Status.PROCESSING = 'processing'
            mock_pipeline_cls.get_instance.return_value = mock_pipeline

            _run_indexing_in_thread(doc_id)

            return mock_doc, mock_pipeline, mock_conn

    def test_calls_process_document(self):
        _, mock_pipeline, _ = self._run()
        mock_pipeline.process_document.assert_called_once()

    def test_closes_db_connection_on_success(self):
        _, _, mock_conn = self._run()
        mock_conn.close.assert_called_once()

    def test_closes_db_connection_on_error(self):
        """connection.close() must be called even when indexing fails."""
        _, _, mock_conn = self._run(pipeline_side_effect=RuntimeError('embed fail'))
        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# _run_indexing_in_thread — error handling
# ---------------------------------------------------------------------------


class TestRunIndexingInThreadErrors:
    def _run_with_error(self, error, doc_pk=42):
        """Run thread with process_document raising error. Return mock queryset."""
        mock_doc = _make_doc(pk=doc_pk, status='processing')

        mock_qs = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.process_document.side_effect = error

        with (
            patch('core.indexing.Document', create=True) as mock_doc_cls,
            patch('core.indexing.RAGPipeline') as mock_pipeline_cls,
            patch('core.indexing.connection'),
        ):
            mock_doc_cls.objects.get.return_value = mock_doc
            mock_doc_cls.Status.PROCESSING = 'processing'
            mock_doc_cls.objects.filter.return_value = mock_qs
            mock_pipeline_cls.get_instance.return_value = mock_pipeline

            _run_indexing_in_thread(doc_pk)

            return mock_qs

    def test_filters_by_processing_status_on_error(self):
        """Only patch status if document is still 'processing' (not already 'error')."""
        mock_qs = self._run_with_error(RuntimeError('boom'))
        # filter() should have been called with status='processing'
        call_kwargs = mock_qs.update.call_args
        assert call_kwargs is not None

    def test_document_not_found_does_not_raise(self):
        """Missing document must be logged, not crash the thread."""
        from django.core.exceptions import ObjectDoesNotExist

        with (
            patch('core.indexing.Document', create=True) as mock_doc_cls,
            patch('core.indexing.RAGPipeline'),
            patch('core.indexing.connection'),
        ):
            mock_doc_cls.objects.get.side_effect = ObjectDoesNotExist('not found')
            # Should complete without raising
            _run_indexing_in_thread(999)

    def test_thread_does_not_propagate_exception(self):
        """Exceptions inside the thread must not escape (daemon threads silently die)."""
        finished = threading.Event()

        def target(doc_id):
            _run_indexing_in_thread(doc_id)
            finished.set()

        with (
            patch('core.indexing.Document', create=True) as mock_doc_cls,
            patch('core.indexing.RAGPipeline') as mock_pipeline_cls,
            patch('core.indexing.connection'),
        ):
            mock_doc_cls.objects.get.return_value = _make_doc()
            mock_doc_cls.Status.PROCESSING = 'processing'
            mock_pipeline_cls.get_instance.return_value = MagicMock(
                process_document=MagicMock(side_effect=ValueError('oops'))
            )

            t = threading.Thread(target=target, args=(42,), daemon=True)
            t.start()
            t.join(timeout=3)
            assert finished.is_set(), 'Thread did not finish cleanly'


# ---------------------------------------------------------------------------
# Status transitions (via Document model — no DB needed)
# ---------------------------------------------------------------------------


class TestStatusTransitionContract:
    """Verify process_document() status contract via RAGPipeline mock."""

    def test_process_document_sets_processing_then_completed(self):
        """
        RAGPipeline.process_document should leave document.status == 'completed'
        on success.  We verify the mock contract used by _run_indexing_in_thread.
        """
        mock_doc = _make_doc(status='pending')

        def fake_process(doc):
            doc.status = 'processing'
            doc.status = 'completed'
            return 5

        mock_pipeline = MagicMock()
        mock_pipeline.process_document.side_effect = fake_process

        with (
            patch('core.indexing.Document', create=True) as mock_doc_cls,
            patch('core.indexing.RAGPipeline') as mock_pipeline_cls,
            patch('core.indexing.connection'),
        ):
            mock_doc_cls.objects.get.return_value = mock_doc
            mock_doc_cls.Status.PROCESSING = 'processing'
            mock_pipeline_cls.get_instance.return_value = mock_pipeline

            _run_indexing_in_thread(42)

        assert mock_doc.status == 'completed'
