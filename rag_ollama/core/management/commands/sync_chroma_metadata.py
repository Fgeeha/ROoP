"""
Management command to sync ChromaDB metadata with Document model.
Updates user_id and is_shared for all existing documents in ChromaDB.

Usage:
    python manage.py sync_chroma_metadata
"""

from django.core.management.base import BaseCommand

from core.models import Document
from core.rag_pipeline import RAGPipeline


class Command(BaseCommand):
    help = 'Sync ChromaDB metadata (user_id, is_shared) with Document model'

    def handle(self, *args, **options):
        pipeline = RAGPipeline.get_instance()
        documents = Document.objects.filter(status='completed')

        total = 0
        updated = 0

        for doc in documents:
            total += 1
            count = pipeline.update_chroma_metadata_for_document(
                document_id=doc.id,
                user_id=doc.user_id,
                is_shared=doc.is_shared,
            )
            if count > 0:
                updated += 1
                self.stdout.write(
                    f'  Updated {count} chunks for document {doc.id} '
                    f'({doc.original_filename}): user_id={doc.user_id}, is_shared={doc.is_shared}'
                )

        self.stdout.write(self.style.SUCCESS(f'Done. Processed {total} documents, updated ChromaDB for {updated}.'))
