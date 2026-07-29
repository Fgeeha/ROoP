"""
Management command: reindex_documents

Re-indexes already uploaded documents from their files on disk: drops the
previous attempt's vectors and chunk rows, then runs the ingestion pipeline
again.  Nothing is re-uploaded.

When to use:
    - bulk recovery after an outage that left many documents in 'error'
      (Ollama unavailable, OOM-kill, a full indexing queue);
    - rebuilding the index after EMBED_MODEL changed.

    For a single document prefer the UI button or POST /api/docs/{id}/reindex/,
    which run inside the web process.

IMPORTANT — stop the web service first:
    ChromaDB runs embedded (PersistentClient), so this command opens its own
    client against the persist directory.  Running it while Gunicorn is up
    means two processes writing one HNSW index — the corruption case the
    single-worker deployment exists to prevent.

Indexing is synchronous here: a CLI process exits as soon as the command
returns, and the background worker is a daemon thread.
"""

import logging

from django.core.management.base import BaseCommand, CommandError

from core.indexing import DocumentBusyError, DocumentFileMissingError, reindex_now
from core.models import Document

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Re-index uploaded documents from disk. Stop the web service before running.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--id',
            type=int,
            action='append',
            dest='ids',
            help='Document id to re-index. May be repeated. Overrides --status.',
        )
        parser.add_argument(
            '--status',
            default=Document.Status.ERROR,
            choices=[Document.Status.ERROR, Document.Status.COMPLETED],
            help='Re-index every document in this status (default: error).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List what would be re-indexed and exit.',
        )

    def handle(self, *args, **options):
        documents = self._select(options)
        if not documents:
            self.stdout.write('reindex_documents: nothing to do.')
            return

        if options['dry_run']:
            self.stdout.write(f'Would re-index {len(documents)} document(s):')
            for doc in documents:
                self.stdout.write(f'  [{doc.id}] {doc.original_filename} ({doc.status})')
            return

        self.stdout.write(
            self.style.WARNING('Make sure the web service is stopped: embedded ChromaDB allows one writer.')
        )

        succeeded, failed = 0, 0
        for i, doc in enumerate(documents, start=1):
            self.stdout.write(f'[{i}/{len(documents)}] {doc.original_filename} (id={doc.id}) ... ', ending='')
            try:
                chunks = reindex_now(doc)
            except (DocumentBusyError, DocumentFileMissingError) as exc:
                failed += 1
                self.stdout.write(self.style.WARNING(f'skipped: {exc}'))
            except Exception as exc:
                # process_document() has already stored the error on the document.
                failed += 1
                logger.exception('reindex_documents: document %d failed', doc.id)
                self.stdout.write(self.style.ERROR(f'failed: {exc}'))
            else:
                succeeded += 1
                self.stdout.write(self.style.SUCCESS(f'ok ({chunks} chunks)'))

        summary = f'reindex_documents: {succeeded} succeeded, {failed} failed.'
        self.stdout.write(self.style.SUCCESS(summary) if not failed else self.style.WARNING(summary))

    def _select(self, options) -> list[Document]:
        if options['ids']:
            documents = list(Document.objects.filter(id__in=options['ids']))
            missing = set(options['ids']) - {doc.id for doc in documents}
            if missing:
                raise CommandError(f'Document(s) not found: {sorted(missing)}')
            return documents

        return list(Document.objects.filter(status=options['status']).order_by('uploaded_at'))
