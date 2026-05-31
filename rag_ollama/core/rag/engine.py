"""
RAGPipeline — the public singleton that orchestrates all RAG subsystems.

Delegates to:
  core.rag.backends  — LLM / embedding backends
  core.rag.extractor — document text extraction
  core.rag.chunker   — hierarchical text chunking
  core.rag.store     — ChromaDB vector operations
"""

import logging
from pathlib import Path
from typing import Optional

import chromadb
from django.conf import settings
from django.utils import timezone

from core.models import Chunk
from core.rag.backends import create_llm_backend
from core.rag.chunker import chunk_text as _chunk_text
from core.rag.extractor import extract_text as _extract_text
from core.rag.store import (
    add_chunks_to_chroma as _add_chunks_to_chroma,
)
from core.rag.store import (
    delete_document_from_chroma as _delete_document_from_chroma,
)
from core.rag.store import (
    search as _search,
)
from core.rag.store import (
    update_chroma_metadata_for_document as _update_chroma_metadata,
)

logger = logging.getLogger(__name__)


class RAGPipeline:
    """
    Singleton RAG pipeline.

    Responsibilities:
    - ChromaDB initialisation and collection access
    - Embedding generation (thin wrapper around backend.embed)
    - process_document(): full ingestion pipeline
    - chat(): retrieval-augmented generation
    - Status checks for LLM backend and ChromaDB
    """

    _instance: Optional['RAGPipeline'] = None

    def __init__(self):
        self._chroma_client = None
        self._collection = None
        self._llm_backend = None

    @classmethod
    def get_instance(cls) -> 'RAGPipeline':
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize ChromaDB and LLM backend."""
        chroma_dir = settings.CHROMA_PERSIST_DIR
        Path(chroma_dir).mkdir(parents=True, exist_ok=True)
        self._chroma_client = chromadb.PersistentClient(path=chroma_dir)
        self._collection = self._chroma_client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION,
            metadata={'hnsw:space': 'cosine'},
        )
        logger.info(
            "ChromaDB initialized: collection='%s', documents=%d",
            settings.CHROMA_COLLECTION,
            self._collection.count(),
        )
        self._llm_backend = create_llm_backend()

    @property
    def collection(self):
        if self._collection is None:
            self._initialize()
        return self._collection

    @property
    def llm(self):
        if self._llm_backend is None:
            self._initialize()
        return self._llm_backend

    # -------------------------------------------------------------------------
    # Text extraction — delegated to core.rag.extractor
    # -------------------------------------------------------------------------

    def extract_text(self, file_path: str, file_type: str) -> str:
        """Extract text content from a file."""
        return _extract_text(file_path, file_type)

    # -------------------------------------------------------------------------
    # Chunking — delegated to core.rag.chunker
    # -------------------------------------------------------------------------

    def chunk_text(self, text: str) -> list[str]:
        """Split text into chunks respecting section boundaries."""
        return _chunk_text(text)

    # -------------------------------------------------------------------------
    # Embeddings
    # -------------------------------------------------------------------------

    def get_embedding(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        return self.llm.embed(texts=[text], model=settings.EMBED_MODEL)[0]

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        return self.llm.embed(texts=texts, model=settings.EMBED_MODEL)

    # -------------------------------------------------------------------------
    # ChromaDB operations — delegated to core.rag.store
    # -------------------------------------------------------------------------

    def add_chunks_to_chroma(
        self,
        chunks: list[str],
        document_id: int,
        filename: str,
        user_id: int | None = None,
        is_shared: bool = False,
        progress_callback=None,
    ) -> list[str]:
        """Add text chunks to ChromaDB with embeddings."""
        return _add_chunks_to_chroma(
            self.collection,
            self.llm,
            chunks,
            document_id,
            filename,
            user_id,
            is_shared,
            progress_callback=progress_callback,
        )

    def delete_document_from_chroma(self, document_id: int) -> None:
        """Remove all chunks of a document from ChromaDB."""
        _delete_document_from_chroma(self.collection, document_id)

    def update_chroma_metadata_for_document(self, document_id: int, user_id: int | None, is_shared: bool) -> int:
        """Update user_id and is_shared metadata for an existing document in ChromaDB."""
        return _update_chroma_metadata(self.collection, document_id, user_id, is_shared)

    def search(self, query: str, k: int = None, user_id: int | None = None) -> list[dict]:
        """Search ChromaDB for relevant chunks, scoped to user + shared docs."""
        return _search(self.collection, self.llm, query, k, user_id)

    # -------------------------------------------------------------------------
    # Document processing pipeline
    # -------------------------------------------------------------------------

    def process_document(self, document) -> int:
        """
        Full document ingestion pipeline:
        1. Extract text
        2. Chunk text
        3. Generate embeddings and store in ChromaDB
        4. Create Chunk model instances
        """
        logger.info('Processing document: %s', document.original_filename)
        document.status = 'processing'
        document.save(update_fields=['status'])

        try:
            text = self.extract_text(document.file_path, document.file_type)
            if not text.strip():
                raise ValueError('No text content extracted from document')

            chunks = self.chunk_text(text)
            if not chunks:
                raise ValueError('No chunks generated from document text')

            # Record total chunk count immediately so the HTMX poller can show
            # "N of M" even before the first embed batch completes.
            document.__class__.objects.filter(pk=document.id).update(
                total_chunks=len(chunks),
                processed_chunks=0,
            )

            def _progress_callback(done: int, total: int) -> None:
                try:
                    document.__class__.objects.filter(pk=document.id).update(
                        processed_chunks=done,
                        total_chunks=total,
                    )
                except Exception:
                    logger.warning('Progress update failed for document %d', document.id)

            chroma_ids = self.add_chunks_to_chroma(
                chunks=chunks,
                document_id=document.id,
                filename=document.original_filename,
                user_id=document.user_id,
                is_shared=document.is_shared,
                progress_callback=_progress_callback,
            )

            chunk_objects = []
            for i, (chunk_text, chroma_id) in enumerate(zip(chunks, chroma_ids, strict=True)):
                chunk_objects.append(
                    Chunk(
                        document=document,
                        content=chunk_text,
                        chunk_index=i,
                        chroma_id=chroma_id,
                        metadata={
                            'filename': document.original_filename,
                            'chunk_index': i,
                            'char_count': len(chunk_text),
                        },
                    )
                )
            Chunk.objects.bulk_create(chunk_objects)

            document.status = 'completed'
            document.processed_at = timezone.now()
            document.save(update_fields=['status', 'processed_at'])

            logger.info('Document processed successfully: %s (%d chunks)', document.original_filename, len(chunks))
            return len(chunks)

        except Exception as e:
            logger.error('Error processing document %d: %s', document.id, e)
            document.status = 'error'
            document.error_message = str(e)
            document.save(update_fields=['status', 'error_message'])
            raise

    # -------------------------------------------------------------------------
    # Chat / RAG query
    # -------------------------------------------------------------------------

    def chat(self, question: str, user_id: int | None = None) -> dict:
        """
        RAG chat: search relevant context and generate answer with LLM.
        Returns dict with 'answer' and 'sources'.
        """
        logger.info('Chat query (user=%s): %s', user_id, question[:100])

        search_results = self.search(question, user_id=user_id)

        if not search_results:
            if self.collection.count() == 0:
                answer = self._generate_no_context_response(question)
            else:
                threshold = settings.SEARCH_RELEVANCE_THRESHOLD
                logger.info('No relevant context after threshold filtering (threshold=%.2f)', threshold)
                answer = (
                    'Релевантного контекста не найдено. '
                    'Загруженные документы не содержат информации по данному запросу '
                    f'(порог схожести: {threshold:.2f}). '
                    'Попробуйте переформулировать вопрос.'
                )
            return {'answer': answer, 'sources': [], 'question': question}

        context_parts = []
        sources = []
        for result in search_results:
            context_parts.append(result['content'])
            sources.append(
                {
                    'filename': result['metadata'].get('filename', 'Unknown'),
                    'chunk_index': result['metadata'].get('chunk_index', 0),
                    'relevance': result['relevance'],
                    'preview': result['content'][:200] + '...' if len(result['content']) > 200 else result['content'],
                }
            )

        context = '\n\n---\n\n'.join(context_parts)
        prompt = self._build_rag_prompt(question, context)
        answer = self._generate_llm_response(prompt)

        return {'answer': answer, 'sources': sources, 'question': question}

    def _build_rag_prompt(self, question: str, context: str) -> str:
        return f"""Ты - полезный ассистент, который отвечает на вопросы на основе предоставленного контекста.

ПРАВИЛА:
1. Отвечай ТОЛЬКО на основе предоставленного контекста
2. Если в контексте нет информации для ответа, честно скажи об этом
3. Цитируй источники, когда это возможно
4. Отвечай на русском языке, если вопрос на русском
5. Будь точным и конкретным

КОНТЕКСТ:
{context}

ВОПРОС: {question}

ОТВЕТ:"""

    def _generate_no_context_response(self, question: str) -> str:
        prompt = f"""Ты - ассистент RAG системы. В данный момент в базе знаний нет документов.

Пользователь задал вопрос: {question}

Вежливо сообщи, что для ответа на вопрос необходимо сначала загрузить документы в систему.
Предложи загрузить документы через интерфейс или API."""
        return self._generate_llm_response(prompt)

    def _generate_llm_response(self, prompt: str) -> str:
        """Generate response from LLM backend."""
        try:
            return self.llm.chat(model=settings.LLM_MODEL, prompt=prompt)
        except Exception as e:
            logger.error('LLM error (%s): %s', settings.LLM_BACKEND, e)
            backend_name = 'Open WebUI' if settings.LLM_BACKEND == 'openwebui' else 'Ollama'
            return (
                f'Ошибка генерации ответа: {e}. '
                f'Убедитесь, что {backend_name} запущена и модель {settings.LLM_MODEL} доступна.'
            )

    # -------------------------------------------------------------------------
    # Status checks
    # -------------------------------------------------------------------------

    def check_ollama_status(self) -> dict:
        """Check LLM backend status and available models."""
        return self.llm.check_status()

    def check_chroma_status(self) -> dict:
        """Check ChromaDB status."""
        try:
            count = self.collection.count()
            return {
                'status': 'online',
                'collection': settings.CHROMA_COLLECTION,
                'documents_in_collection': count,
            }
        except Exception as e:
            return {'status': 'offline', 'error': str(e)}
