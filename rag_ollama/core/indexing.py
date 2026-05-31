"""
Asynchronous document indexing via a background daemon thread.

No external broker required — a threading.Thread is sufficient for a
single-machine local deployment.  The thread owns its own DB connection
which is explicitly closed in the finally block to prevent leaks.
"""

import logging
import threading

from django.core.exceptions import ObjectDoesNotExist
from django.db import connection

from core.models import Document
from core.rag_pipeline import RAGPipeline

logger = logging.getLogger(__name__)


def _run_indexing_in_thread(document_id: int) -> None:
    """
    Target for the background thread.

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
        connection.close()


def start_indexing_async(document_id: int) -> None:
    """Start document indexing in a background daemon thread."""
    thread = threading.Thread(
        target=_run_indexing_in_thread,
        args=(document_id,),
        daemon=True,
        name=f'indexing-doc-{document_id}',
    )
    thread.start()
    logger.info('Background indexing started for document %d (thread: %s)', document_id, thread.name)
