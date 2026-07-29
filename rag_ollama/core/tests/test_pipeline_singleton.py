"""
Regression tests for RAGPipeline singleton initialisation under threads.

Gunicorn runs one worker process with GUNICORN_THREADS threads (see
entrypoint.sh).  Two concurrent requests on a cold start therefore reach
RAGPipeline.get_instance() in the same process at the same time.  Creating
two chromadb.PersistentClient objects against one persist directory is the
index-corruption path that the single-worker deployment exists to prevent.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from core.rag.engine import RAGPipeline


@pytest.fixture(autouse=True)
def mock_rag_pipeline():
    """
    Override the project-wide RAGPipeline mock from conftest.

    These tests exercise the real get_instance(); the global autouse fixture
    patches it away.
    """
    yield


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Each test starts and ends with no cached instance."""
    RAGPipeline._instance = None
    yield
    RAGPipeline._instance = None


class _SlowPersistentClient:
    """
    Stand-in for chromadb.PersistentClient that is slow to construct.

    The delay widens the race window: without a lock, every thread passes the
    `_instance is None` check before the first one finishes building.
    """

    calls = 0
    _counter_lock = threading.Lock()

    def __init__(self, path):
        with _SlowPersistentClient._counter_lock:
            _SlowPersistentClient.calls += 1
        self.path = path
        # Long enough that all threads are inside __init__ concurrently.
        threading.Event().wait(0.05)

    def get_or_create_collection(self, name, metadata=None):
        collection = MagicMock()
        collection.count.return_value = 0
        return collection


@pytest.fixture
def _slow_client():
    _SlowPersistentClient.calls = 0
    with (
        patch('core.rag.engine.chromadb.PersistentClient', _SlowPersistentClient),
        patch('core.rag.engine.create_llm_backend', return_value=MagicMock()),
    ):
        yield _SlowPersistentClient


class TestSingletonThreadSafety:
    def test_concurrent_get_instance_creates_one_client(self, _slow_client, tmp_path, settings):
        """Parallel get_instance() calls must build exactly one ChromaDB client."""
        settings.CHROMA_PERSIST_DIR = str(tmp_path / 'chroma')

        instances = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()  # release all threads at once
            instances.append(RAGPipeline.get_instance())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(instances) == 8
        assert all(inst is instances[0] for inst in instances)
        assert _slow_client.calls == 1

    def test_concurrent_lazy_property_creates_one_client(self, _slow_client, tmp_path, settings):
        """Parallel access to .collection on an uninitialised instance must not re-init."""
        settings.CHROMA_PERSIST_DIR = str(tmp_path / 'chroma')

        pipeline = RAGPipeline()
        barrier = threading.Barrier(8)
        results = []

        def worker():
            barrier.wait()
            results.append(pipeline.collection)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(results) == 8
        assert all(r is results[0] for r in results)
        assert _slow_client.calls == 1


class TestSingletonInitFailure:
    def test_failed_initialisation_is_not_published(self, tmp_path, settings):
        """A pipeline whose _initialize() raised must not become the singleton."""
        settings.CHROMA_PERSIST_DIR = str(tmp_path / 'chroma')

        with (
            patch('core.rag.engine.chromadb.PersistentClient', side_effect=RuntimeError('chroma down')),
            patch('core.rag.engine.create_llm_backend', return_value=MagicMock()),
            pytest.raises(RuntimeError, match='chroma down'),
        ):
            RAGPipeline.get_instance()

        assert RAGPipeline._instance is None

        # A later call, once ChromaDB is reachable, must succeed.
        with (
            patch('core.rag.engine.chromadb.PersistentClient', _SlowPersistentClient),
            patch('core.rag.engine.create_llm_backend', return_value=MagicMock()),
        ):
            pipeline = RAGPipeline.get_instance()

        assert RAGPipeline._instance is pipeline
        assert pipeline._collection is not None

    def test_initialize_is_idempotent(self, _slow_client, tmp_path, settings):
        """Repeated _initialize() on a ready pipeline must not rebuild the client."""
        settings.CHROMA_PERSIST_DIR = str(tmp_path / 'chroma')

        pipeline = RAGPipeline.get_instance()
        collection = pipeline.collection

        pipeline._initialize()

        assert _slow_client.calls == 1
        assert pipeline.collection is collection
