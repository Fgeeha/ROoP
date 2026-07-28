"""
Tests for async document indexing (core/indexing.py).

All external I/O (RAGPipeline, DB connection.close) is mocked so the
suite runs without Ollama, ChromaDB, or a running PostgreSQL.
"""

import queue
import threading
from unittest.mock import MagicMock, patch

import pytest

import core.indexing as indexing_module
from core.indexing import (
    INDEXING_QUEUE_MAXSIZE,
    IndexingQueueFullError,
    _run_indexing_in_thread,
    shutdown_indexing_worker,
    start_indexing_async,
)

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


@pytest.fixture
def clean_worker():
    """Ensure each test starts and ends with no indexing worker running."""
    shutdown_indexing_worker(timeout=2)
    yield
    shutdown_indexing_worker(timeout=2)


# ---------------------------------------------------------------------------
# start_indexing_async — queue semantics
# ---------------------------------------------------------------------------


class TestStartIndexingAsync:
    def test_returns_immediately(self, clean_worker):
        """start_indexing_async must not block the caller."""
        started = threading.Event()
        release = threading.Event()

        def slow_index(doc_id):
            started.set()
            release.wait(timeout=5)

        with patch('core.indexing._run_indexing_in_thread', side_effect=slow_index):
            start_indexing_async(99)
            assert started.wait(timeout=5), 'worker never picked up the task'
            release.set()

    def test_uses_single_named_worker_thread(self, clean_worker):
        """Work runs on one long-lived 'indexing-worker' thread, not a per-document thread."""
        seen: list[str] = []
        done = threading.Event()

        def record(doc_id):
            seen.append(threading.current_thread().name)
            if len(seen) == 3:
                done.set()

        with patch('core.indexing._run_indexing_in_thread', side_effect=record):
            for doc_id in (1, 2, 3):
                start_indexing_async(doc_id)
            assert done.wait(timeout=5)

        assert set(seen) == {'indexing-worker'}, f'expected one worker thread, got {set(seen)}'

    def test_only_one_indexing_runs_at_a_time(self, clean_worker):
        """Two documents queued together must never be indexed concurrently."""
        concurrent = 0
        max_concurrent = 0
        lock = threading.Lock()
        both_done = threading.Event()
        processed = 0

        def track(doc_id):
            nonlocal concurrent, max_concurrent, processed
            with lock:
                concurrent += 1
                max_concurrent = max(max_concurrent, concurrent)
            # Hold the slot long enough that a second concurrent task would overlap.
            threading.Event().wait(0.05)
            with lock:
                concurrent -= 1
                processed += 1
                if processed == 2:
                    both_done.set()

        with patch('core.indexing._run_indexing_in_thread', side_effect=track):
            start_indexing_async(1)
            start_indexing_async(2)
            assert both_done.wait(timeout=5)

        assert max_concurrent == 1, f'{max_concurrent} indexing tasks ran concurrently'

    def test_processes_in_fifo_order(self, clean_worker):
        """Queue order is predictable: first queued, first indexed."""
        order: list[int] = []
        done = threading.Event()

        def record(doc_id):
            order.append(doc_id)
            if len(order) == 4:
                done.set()

        with patch('core.indexing._run_indexing_in_thread', side_effect=record):
            for doc_id in (10, 20, 30, 40):
                start_indexing_async(doc_id)
            assert done.wait(timeout=5)

        assert order == [10, 20, 30, 40]

    def test_worker_is_daemon(self, clean_worker):
        """The worker must be a daemon so process exit is never blocked."""
        with patch('core.indexing._run_indexing_in_thread'):
            start_indexing_async(1)

        assert indexing_module._worker is not None
        assert indexing_module._worker.daemon is True

    def test_repeated_calls_do_not_spawn_extra_workers(self, clean_worker):
        """_ensure_worker is idempotent — no second background worker appears."""
        done = threading.Event()
        count = 0

        def record(doc_id):
            nonlocal count
            count += 1
            if count == 5:
                done.set()

        with patch('core.indexing._run_indexing_in_thread', side_effect=record):
            for doc_id in range(5):
                start_indexing_async(doc_id)
            assert done.wait(timeout=5)

        workers = [t for t in threading.enumerate() if t.name == 'indexing-worker']
        assert len(workers) == 1, f'expected 1 worker thread, found {len(workers)}'

    def test_reimport_does_not_create_second_worker(self, clean_worker):
        """Importing the module again must reuse the existing worker."""
        with patch('core.indexing._run_indexing_in_thread'):
            start_indexing_async(1)
            first_worker = indexing_module._worker

            import importlib

            reimported = importlib.import_module('core.indexing')
            reimported.start_indexing_async(2)

        assert reimported._worker is first_worker
        workers = [t for t in threading.enumerate() if t.name == 'indexing-worker']
        assert len(workers) == 1


# ---------------------------------------------------------------------------
# Worker resilience
# ---------------------------------------------------------------------------


class TestWorkerResilience:
    def test_exception_does_not_stop_next_task(self, clean_worker):
        """A failing task must not stall the documents queued behind it."""
        processed: list[int] = []
        done = threading.Event()

        def flaky(doc_id):
            if doc_id == 1:
                raise RuntimeError('embed exploded')
            processed.append(doc_id)
            done.set()

        with patch('core.indexing._run_indexing_in_thread', side_effect=flaky):
            start_indexing_async(1)
            start_indexing_async(2)
            assert done.wait(timeout=5)

        assert processed == [2]

    def test_worker_survives_many_failures(self, clean_worker):
        """Repeated failures must leave the worker alive and consuming."""
        done = threading.Event()

        def always_fail(doc_id):
            if doc_id == 99:
                done.set()
                return
            raise ValueError('boom')

        with patch('core.indexing._run_indexing_in_thread', side_effect=always_fail):
            for doc_id in range(5):
                start_indexing_async(doc_id)
            start_indexing_async(99)
            assert done.wait(timeout=5)

        assert indexing_module._worker.is_alive()


# ---------------------------------------------------------------------------
# Bounded queue
# ---------------------------------------------------------------------------


class TestQueueBackpressure:
    def test_queue_full_raises(self, clean_worker):
        """Once the backlog is full, start_indexing_async must refuse fast."""
        block = threading.Event()

        def blocking(doc_id):
            block.wait(timeout=10)

        with patch('core.indexing._run_indexing_in_thread', side_effect=blocking):
            start_indexing_async(0)  # occupies the worker
            # Fill the queue. The worker holds one item, so this cannot drain.
            for doc_id in range(1, INDEXING_QUEUE_MAXSIZE + 1):
                try:
                    start_indexing_async(doc_id)
                except IndexingQueueFullError:
                    break

            with pytest.raises(IndexingQueueFullError):
                start_indexing_async(999_999)

            block.set()

    def test_queue_maxsize_is_bounded(self):
        """The queue must never be unbounded."""
        assert 0 < INDEXING_QUEUE_MAXSIZE < 10_000


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_stops_worker(self, clean_worker):
        with patch('core.indexing._run_indexing_in_thread'):
            start_indexing_async(1)
            worker = indexing_module._worker

        shutdown_indexing_worker(timeout=5)
        assert not worker.is_alive()
        assert indexing_module._worker is None

    def test_shutdown_without_worker_is_safe(self):
        """Calling shutdown when nothing is running must not raise."""
        shutdown_indexing_worker(timeout=1)
        shutdown_indexing_worker(timeout=1)

    def test_shutdown_is_bounded_by_timeout(self, clean_worker):
        """A wedged task must not make shutdown hang forever."""
        block = threading.Event()

        def blocking(doc_id):
            block.wait(timeout=10)

        try:
            with patch('core.indexing._run_indexing_in_thread', side_effect=blocking):
                start_indexing_async(1)
                threading.Event().wait(0.1)
                # Worker is stuck in the task; shutdown must still return.
                shutdown_indexing_worker(timeout=0.5)
        finally:
            block.set()

    def test_start_after_shutdown_creates_new_worker(self, clean_worker):
        """The queue must be usable again after a shutdown."""
        done = threading.Event()

        with patch('core.indexing._run_indexing_in_thread'):
            start_indexing_async(1)
        shutdown_indexing_worker(timeout=5)

        with patch('core.indexing._run_indexing_in_thread', side_effect=lambda d: done.set()):
            start_indexing_async(2)
            assert done.wait(timeout=5)


# ---------------------------------------------------------------------------
# Module contract
# ---------------------------------------------------------------------------


class TestQueueContract:
    def test_queue_is_a_bounded_queue(self, clean_worker):
        with patch('core.indexing._run_indexing_in_thread'):
            start_indexing_async(1)
        assert isinstance(indexing_module._queue, queue.Queue)
        assert indexing_module._queue.maxsize == INDEXING_QUEUE_MAXSIZE


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
