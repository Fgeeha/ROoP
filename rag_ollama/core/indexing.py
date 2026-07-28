"""
Serialized background document indexing.

A single long-lived worker thread consumes document IDs from a bounded queue.

Why a queue instead of one thread per upload:
    The previous implementation started a new daemon thread for every upload.
    N simultaneous uploads meant N documents' text, chunks and embedding
    vectors resident at once, plus N concurrent embed streams against Ollama
    (which then multiplies its own KV cache).  On a 16 GB machine that is the
    main OOM path.  Exactly one indexing task now runs at a time.

Daemon thread, deliberately:
    An abrupt process exit (SIGKILL, OOM-kill, power loss) must not block on
    in-flight indexing.  Work interrupted that way is reconciled at the next
    startup by the `recover_stuck_documents` management command, which flips
    any document left in 'processing' to 'error'.

Process scope:
    This bounds concurrency *within one process*.  It relies on the deployment
    running a single Gunicorn worker process (see entrypoint.sh /
    GUNICORN_WORKERS), which the embedded ChromaDB client requires anyway.
"""

import logging
import queue
import threading

from django.core.exceptions import ObjectDoesNotExist
from django.db import connection

from core.models import Document
from core.rag_pipeline import RAGPipeline

logger = logging.getLogger(__name__)

# Bound the backlog so a burst of uploads cannot accumulate without limit.
# A queued item is just an int, so memory is not the binding constraint --
# the cap exists to give the user an immediate, honest answer instead of a
# silent multi-hour backlog.  On CPU a document takes roughly 1-3 minutes,
# so 100 queued documents is already several hours of work; beyond that,
# refusing the upload is more useful than accepting it.
INDEXING_QUEUE_MAXSIZE = 100

QUEUE_FULL_USER_MESSAGE = (
    'Очередь индексации переполнена. Файл сохранён, но не проиндексирован. '
    'Дождитесь завершения текущих задач и запустите индексацию повторно.'
)

# Sentinel that tells the worker loop to exit (used by shutdown_indexing_worker).
_SHUTDOWN = object()

_queue: queue.Queue | None = None
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


class IndexingQueueFullError(RuntimeError):
    """Raised when the indexing backlog is full and a document cannot be queued."""


def _run_indexing_in_thread(document_id: int) -> None:
    """
    Index a single document.  Runs on the worker thread.

    process_document() already handles status transitions:
      pending → processing → completed | error
    The outer except is a safety net for unexpected failures that occur
    before process_document() can save the error status itself (e.g. a DB
    connection drop right at startup).  It only writes to the DB if the
    document is still stuck in 'processing'.
    """
    try:
        document = Document.objects.get(pk=document_id)
        pipeline = RAGPipeline.get_instance()
        pipeline.process_document(document)
    except ObjectDoesNotExist:
        logger.error('Background indexing: document %d not found', document_id)
    except Exception as e:
        logger.error('Background indexing failed for document %d: %s', document_id, e)
        # Only patch status if it is still 'processing' — process_document()
        # may have already moved it to 'error' before re-raising.
        try:
            Document.objects.filter(pk=document_id, status=Document.Status.PROCESSING).update(
                status=Document.Status.ERROR,
                error_message=str(e)[:1000],
            )
        except Exception:
            logger.exception('Failed to persist error status for document %d', document_id)
    finally:
        # Release the worker thread's DB connection between tasks so the
        # long-lived thread does not hold an idle connection open.
        connection.close()


def _worker_loop(work_queue: queue.Queue) -> None:
    """Consume document IDs until the shutdown sentinel arrives."""
    logger.info('Indexing worker started (queue maxsize=%d)', INDEXING_QUEUE_MAXSIZE)
    while True:
        item = work_queue.get()
        try:
            if item is _SHUTDOWN:
                logger.info('Indexing worker stopping')
                return
            _run_indexing_in_thread(item)
        except Exception:
            # _run_indexing_in_thread handles its own errors; this is a
            # last-resort guard so one bad task can never kill the worker
            # and stall every document queued behind it.
            logger.exception('Indexing worker: unhandled error for document %s', item)
        finally:
            work_queue.task_done()


def _ensure_worker() -> queue.Queue:
    """
    Return the process-wide indexing queue, starting the worker on first use.

    Idempotent: repeated calls (and repeated module imports) reuse the same
    queue and thread.  A worker that died unexpectedly is replaced.
    """
    global _queue, _worker
    with _worker_lock:
        if _queue is None:
            _queue = queue.Queue(maxsize=INDEXING_QUEUE_MAXSIZE)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(
                target=_worker_loop,
                args=(_queue,),
                daemon=True,
                name='indexing-worker',
            )
            _worker.start()
        return _queue


def start_indexing_async(document_id: int) -> None:
    """
    Queue a document for indexing and return immediately.

    Raises:
        IndexingQueueFullError: backlog is at INDEXING_QUEUE_MAXSIZE.  The caller
            must surface this to the user and mark the document accordingly —
            the uploaded file is left on disk untouched.
    """
    work_queue = _ensure_worker()
    try:
        work_queue.put_nowait(document_id)
    except queue.Full as exc:
        logger.warning(
            'Indexing queue full (maxsize=%d), rejected document %d',
            INDEXING_QUEUE_MAXSIZE,
            document_id,
        )
        raise IndexingQueueFullError(QUEUE_FULL_USER_MESSAGE) from exc

    logger.info('Document %d queued for indexing (queue depth=%d)', document_id, work_queue.qsize())


def shutdown_indexing_worker(timeout: float = 5.0) -> None:
    """
    Stop the worker thread and reset module state.

    Safe to call when no worker is running.  Bounded by `timeout` so shutdown
    can never hang; the thread is a daemon, so a timeout is not fatal.
    """
    global _queue, _worker
    with _worker_lock:
        work_queue, worker = _queue, _worker
        _queue, _worker = None, None

    if worker is not None and worker.is_alive():
        if work_queue is not None:
            try:
                work_queue.put_nowait(_SHUTDOWN)
            except queue.Full:
                logger.warning('Could not enqueue shutdown sentinel: queue full')
        worker.join(timeout=timeout)
        if worker.is_alive():
            logger.warning('Indexing worker did not stop within %.1fs (daemon, will die with process)', timeout)
