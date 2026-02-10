from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'RAG Core'

    def ready(self):
        """Initialize ChromaDB collection on app startup."""
        import logging

        logger = logging.getLogger(__name__)
        try:
            from core.rag_pipeline import RAGPipeline

            RAGPipeline.get_instance()
            logger.info('RAG Pipeline initialized successfully')
        except Exception as e:
            logger.warning(f'RAG Pipeline initialization deferred: {e}')
