"""
RAG Pipeline - core logic for document processing, embedding and retrieval.
Supports two LLM backends:
  - ollama:    direct connection to Ollama API
  - openwebui: connection via Open WebUI OpenAI-compatible API (Bearer token auth)
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

import chromadb
from django.conf import settings
from django.utils import timezone

from core.rag.backends import OllamaBackend, OpenWebUIBackend, create_llm_backend  # noqa: F401

logger = logging.getLogger(__name__)


# =============================================================================
# RAG Pipeline
# =============================================================================


class RAGPipeline:
    """
    Singleton RAG Pipeline handling:
    - Document text extraction (PDF, TXT, MD)
    - Text chunking with overlap
    - Embedding generation via LLM backend
    - ChromaDB vector storage and retrieval
    - LLM query with context (RAG)
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
        # ChromaDB
        chroma_dir = settings.CHROMA_PERSIST_DIR
        Path(chroma_dir).mkdir(parents=True, exist_ok=True)
        self._chroma_client = chromadb.PersistentClient(path=chroma_dir)
        self._collection = self._chroma_client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION,
            metadata={'hnsw:space': 'cosine'},
        )
        logger.info(
            f"ChromaDB initialized: collection='{settings.CHROMA_COLLECTION}', documents={self._collection.count()}"
        )

        # LLM backend
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
    # Text extraction
    # -------------------------------------------------------------------------

    def extract_text(self, file_path: str, file_type: str) -> str:
        """Extract text content from a file."""
        logger.info(f'Extracting text from: {file_path} (type: {file_type})')

        if file_type == 'pdf':
            raw = self._extract_pdf(file_path)
        elif file_type in ('txt', 'md'):
            raw = self._extract_text_file(file_path)
        elif file_type == 'docx':
            raw = self._extract_docx(file_path)
        elif file_type == 'doc':
            raw = self._extract_doc(file_path)
        else:
            raise ValueError(f'Unsupported file type: {file_type}')

        cleaned = self._clean_extracted_text(raw)
        logger.info(f'Text extracted and cleaned: {len(raw)} -> {len(cleaned)} chars')
        return cleaned

    def _extract_pdf(self, file_path: str) -> str:
        """Extract text from PDF using pdfplumber (much better layout handling than PyPDF2)."""
        import pdfplumber

        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text(
                    x_tolerance=2,  # merge chars closer than 2pt (fixes broken words)
                    y_tolerance=3,  # merge lines closer than 3pt
                )
                if page_text:
                    text_parts.append(page_text)
                    logger.debug(f'Extracted page {page_num + 1}: {len(page_text)} chars')

        full_text = '\n\n'.join(text_parts)
        logger.info(f'PDF extraction complete: {len(full_text)} chars from {len(pdf.pages)} pages')
        return full_text

    def _extract_text_file(self, file_path: str) -> str:
        """Extract text from TXT/MD file with encoding detection."""
        import chardet

        with open(file_path, 'rb') as f:
            raw_data = f.read()

        detected = chardet.detect(raw_data)
        encoding = detected.get('encoding', 'utf-8') or 'utf-8'
        logger.debug(f'Detected encoding: {encoding} (confidence: {detected.get("confidence", 0):.2f})')

        try:
            text = raw_data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            text = raw_data.decode('utf-8', errors='replace')

        return text

    def _extract_docx(self, file_path: str) -> str:
        """Extract text from DOCX file using python-docx."""
        import docx

        doc = docx.Document(file_path)
        text_parts = []

        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if text:
                text_parts.append(text)

        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                row_text = '\t'.join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    text_parts.append(row_text)

        full_text = '\n\n'.join(text_parts)
        logger.info(f'DOCX extraction complete: {len(full_text)} chars')
        return full_text

    def _extract_doc(self, file_path: str) -> str:
        """
        Extract text from legacy DOC file.
        Uses antiword (system utility) as primary method.
        Falls back to python-docx in case the file is actually DOCX with .doc extension.
        """
        import subprocess

        # Try antiword first (handles genuine .doc binary format)
        try:
            result = subprocess.run(  # noqa: S603
                ['/usr/bin/antiword', '-w', '0', file_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info(f'DOC extraction via antiword complete: {len(result.stdout)} chars')
                return result.stdout
            logger.warning(f'antiword returned code {result.returncode}: {result.stderr.strip()}')
        except FileNotFoundError:
            logger.warning('antiword not installed, falling back to python-docx')
        except subprocess.TimeoutExpired:
            logger.warning('antiword timed out, falling back to python-docx')

        # Fallback: try python-docx (works if the file is actually DOCX with .doc extension)
        try:
            return self._extract_docx(file_path)
        except Exception as e:
            raise ValueError(
                'Не удалось извлечь текст из DOC файла. '
                'Убедитесь, что antiword установлен (apt-get install antiword) '
                'или конвертируйте файл в DOCX формат.'
            ) from e

    def _clean_extracted_text(self, text: str) -> str:
        """
        Post-process extracted text:
        - Remove repeated page headers/footers (address blocks, page numbers)
        - Fix broken words (letters separated by spaces within a word)
        - Normalize whitespace
        """
        lines = text.split('\n')

        # 1. Detect and remove repeated header/footer lines.
        #    Lines appearing on 3+ "pages" (delimited by double-newline) are likely headers/footers.
        page_blocks = text.split('\n\n')
        if len(page_blocks) >= 3:
            line_counts: dict[str, int] = {}
            for block in page_blocks:
                seen_in_block: set[str] = set()
                for line in block.split('\n'):
                    stripped = line.strip()
                    if stripped and stripped not in seen_in_block:
                        seen_in_block.add(stripped)
                        line_counts[stripped] = line_counts.get(stripped, 0) + 1

            # Lines that appear in >= 40% of page blocks are headers/footers
            threshold = max(3, len(page_blocks) * 0.4)
            header_footer_lines = {
                line for line, count in line_counts.items() if count >= threshold and len(line) < 200
            }

            if header_footer_lines:
                logger.info(f'Removing {len(header_footer_lines)} repeated header/footer patterns')
                lines = [line for line in lines if line.strip() not in header_footer_lines]

        # 2. Remove standalone page numbers (lines that are just a number)
        lines = [line for line in lines if not re.match(r'^\s*\d{1,4}\s*$', line)]

        # 3. Join lines
        text = '\n'.join(lines)

        # 4. Fix clearly broken words: only merge single isolated letter fragments.
        #    Example: "переведе н на" has an isolated single "н" between spaces.
        #    Pattern: word fragment (2+ chars) + space + single letter + space
        #    This is safe because single Cyrillic letters between spaces are almost
        #    never real words (except "в", "и", "с", "к", "о", "а", "у" - prepositions).
        _prepositions = set('вискоау')

        def _merge_fragment(m):
            frag = m.group(2)
            if frag.lower() in _prepositions:
                return m.group(0)  # keep as is -- it's a real word
            return m.group(1) + frag + ' '

        text = re.sub(r'([а-яА-ЯёЁ]{2,}) ([а-яёЁА-ЯЁ]) ', _merge_fragment, text)

        # 5. Normalize excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]{2,}', ' ', text)

        return text.strip()

    # -------------------------------------------------------------------------
    # Chunking
    # -------------------------------------------------------------------------

    # Heading patterns: lines that look like section titles in Russian technical docs.
    # Examples: "Социальная защита", "Интеграционный модуль", "Расписание"
    _HEADING_RE = re.compile(
        r'^(?:'
        r'(?:Модуль|Раздел|Глава|Часть|Блок)\s+.+'  # "Модуль ..."
        r'|[А-ЯЁ][а-яёА-ЯЁ\s\-]{2,60}'  # Capitalised short line (heading)
        r')$'
    )

    def chunk_text(self, text: str) -> list[str]:
        """
        Split text into chunks, respecting section boundaries.

        Strategy:
        1. Split the document into sections by headings.
        2. If a section fits into chunk_size -- keep it as one chunk.
        3. If a section is too long -- split by paragraphs with overlap.
        4. If a paragraph is still too long -- split by sentences with overlap.
        """
        chunk_size = settings.CHUNK_SIZE
        chunk_overlap = settings.CHUNK_OVERLAP

        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        if not text:
            return []

        if len(text) <= chunk_size:
            return [text]

        # Step 1: Split into sections by headings
        sections = self._split_by_headings(text)

        # Step 2: Build chunks from sections
        chunks = []
        for section in sections:
            section = section.strip()
            if not section:
                continue

            if len(section) <= chunk_size:
                chunks.append(section)
            else:
                # Section too large -- split by paragraphs with overlap
                sub_chunks = self._split_by_paragraphs(section, chunk_size, chunk_overlap)
                chunks.extend(sub_chunks)

        # Filter tiny chunks (< 50 chars are noise)
        chunks = [c for c in chunks if len(c.strip()) > 50]

        logger.info(f'Text chunked: {len(text)} chars -> {len(chunks)} chunks')
        return chunks

    def _split_by_headings(self, text: str) -> list[str]:
        """
        Split text into sections at heading boundaries.
        A heading is a short line (<= 80 chars) that either:
        - Matches common heading patterns, or
        - Is followed by a numbered list ("1. ...")
        """
        lines = text.split('\n')
        sections: list[str] = []
        current_lines: list[str] = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            is_heading = False

            if stripped and len(stripped) <= 80:
                # Check if it looks like a heading
                if self._HEADING_RE.match(stripped):
                    is_heading = True
                # Also treat as heading if next non-empty line starts with "1."
                elif stripped and not stripped[0].isdigit():
                    for j in range(i + 1, min(i + 3, len(lines))):
                        next_stripped = lines[j].strip()
                        if next_stripped:
                            if re.match(r'^1[\.\)]\s', next_stripped):
                                is_heading = True
                            break

            if is_heading and current_lines:
                # Save current section, start new one with this heading
                section_text = '\n'.join(current_lines).strip()
                if section_text:
                    sections.append(section_text)
                current_lines = [line]
            else:
                current_lines.append(line)

        # Don't forget the last section
        if current_lines:
            section_text = '\n'.join(current_lines).strip()
            if section_text:
                sections.append(section_text)

        logger.debug(f'Split into {len(sections)} sections by headings')
        return sections

    def _split_by_paragraphs(self, text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
        """Split a section into chunks by paragraph boundaries with overlap."""
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = ''

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            if len(current_chunk) + len(paragraph) + 2 <= chunk_size:
                current_chunk = current_chunk + '\n\n' + paragraph if current_chunk else paragraph
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                if len(paragraph) > chunk_size:
                    # Paragraph itself too long -- split by sentences
                    sub_chunks = self._split_long_text(paragraph, chunk_size, chunk_overlap)
                    chunks.extend(sub_chunks)
                    current_chunk = ''
                else:
                    # Start new chunk; add overlap from end of previous chunk
                    if chunks:
                        overlap_text = chunks[-1][-chunk_overlap:]
                        current_chunk = overlap_text + '\n\n' + paragraph
                    else:
                        current_chunk = paragraph

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def _split_long_text(self, text: str, chunk_size: int, overlap: int) -> list[str]:
        """Split a long text block by sentence boundaries with overlap."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size

            # Try to break at sentence boundary
            if end < len(text):
                search_start = max(end - 100, start)
                last_period = max(
                    text.rfind('. ', search_start, end),
                    text.rfind('! ', search_start, end),
                    text.rfind('? ', search_start, end),
                    text.rfind('\n', search_start, end),
                )
                if last_period > start:
                    end = last_period + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - overlap if end < len(text) else len(text)

        return chunks

    # -------------------------------------------------------------------------
    # Embeddings
    # -------------------------------------------------------------------------

    def get_embedding(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        embeddings = self.llm.embed(texts=[text], model=settings.EMBED_MODEL)
        return embeddings[0]

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        return self.llm.embed(texts=texts, model=settings.EMBED_MODEL)

    # -------------------------------------------------------------------------
    # ChromaDB operations
    # -------------------------------------------------------------------------

    def add_chunks_to_chroma(
        self,
        chunks: list[str],
        document_id: int,
        filename: str,
        user_id: int | None = None,
        is_shared: bool = False,
    ) -> list[str]:
        """Add text chunks to ChromaDB with embeddings."""
        if not chunks:
            return []

        logger.info(f'Generating embeddings for {len(chunks)} chunks...')
        embeddings = self.get_embeddings_batch(chunks)

        # Generate unique IDs for each chunk
        chroma_ids = []
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_hash = hashlib.md5(chunk.encode(), usedforsecurity=False).hexdigest()[:12]
            chroma_id = f'doc{document_id}_chunk{i}_{chunk_hash}'
            chroma_ids.append(chroma_id)
            metadatas.append(
                {
                    'document_id': str(document_id),
                    'filename': filename,
                    'chunk_index': i,
                    'char_count': len(chunk),
                    'user_id': str(user_id) if user_id else '',
                    'is_shared': 'true' if is_shared else 'false',
                }
            )

        # Add to ChromaDB in batches
        batch_size = 100
        for batch_start in range(0, len(chunks), batch_size):
            batch_end = min(batch_start + batch_size, len(chunks))
            self.collection.add(
                ids=chroma_ids[batch_start:batch_end],
                embeddings=embeddings[batch_start:batch_end],
                documents=chunks[batch_start:batch_end],
                metadatas=metadatas[batch_start:batch_end],
            )

        logger.info(f'Added {len(chunks)} chunks to ChromaDB for document {document_id}')
        return chroma_ids

    def delete_document_from_chroma(self, document_id: int):
        """Remove all chunks of a document from ChromaDB."""
        try:
            results = self.collection.get(
                where={'document_id': str(document_id)},
            )
            if results and results['ids']:
                self.collection.delete(ids=results['ids'])
                logger.info(f'Deleted {len(results["ids"])} chunks from ChromaDB for document {document_id}')
        except Exception as e:
            logger.error(f'Error deleting from ChromaDB: {e}')

    def update_chroma_metadata_for_document(self, document_id: int, user_id: int | None, is_shared: bool):
        """Update user_id and is_shared metadata for an existing document in ChromaDB."""
        try:
            results = self.collection.get(
                where={'document_id': str(document_id)},
            )
            if not results or not results['ids']:
                return 0

            new_metadatas = []
            for meta in results['metadatas']:
                meta['user_id'] = str(user_id) if user_id else ''
                meta['is_shared'] = 'true' if is_shared else 'false'
                new_metadatas.append(meta)

            self.collection.update(
                ids=results['ids'],
                metadatas=new_metadatas,
            )
            logger.info(
                f'Updated ChromaDB metadata for document {document_id}: '
                f'user_id={user_id}, is_shared={is_shared} ({len(results["ids"])} chunks)'
            )
            return len(results['ids'])
        except Exception as e:
            logger.error(f'Error updating ChromaDB metadata for document {document_id}: {e}')
            return 0

    def search(self, query: str, k: int = None, user_id: int | None = None) -> list[dict]:
        """Search ChromaDB for relevant chunks, scoped to user + shared docs.

        ChromaDB with hnsw:space=cosine returns cosine DISTANCE (0 = identical,
        1 = orthogonal), not similarity.  We convert: relevance = 1 - distance,
        then drop chunks below settings.SEARCH_RELEVANCE_THRESHOLD.
        """
        k = k or settings.SEARCH_K
        threshold = settings.SEARCH_RELEVANCE_THRESHOLD

        if self.collection.count() == 0:
            logger.warning('ChromaDB collection is empty')
            return []

        query_embedding = self.get_embedding(query)

        # Build user-scoped filter
        where_filter = None
        if user_id:
            where_filter = {
                '$or': [
                    {'user_id': str(user_id)},
                    {'is_shared': 'true'},
                ],
            }

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(k, self.collection.count()),
            include=['documents', 'metadatas', 'distances'],
            where=where_filter,
        )

        search_results = []
        if results and results['documents']:
            for i, (doc, metadata, distance) in enumerate(
                zip(
                    results['documents'][0],
                    results['metadatas'][0],
                    results['distances'][0],
                    strict=False,
                )
            ):
                search_results.append(
                    {
                        'content': doc,
                        'metadata': metadata,
                        'relevance': round(1 - distance, 4),
                        'rank': i + 1,
                    }
                )

        # Apply relevance threshold.
        # relevance = 1 - distance, so higher is better.
        # Keep only chunks with relevance >= threshold.
        if threshold > 0 and search_results:
            before = len(search_results)
            search_results = [r for r in search_results if r['relevance'] >= threshold]
            dropped = before - len(search_results)
            if dropped:
                logger.info(
                    'Relevance threshold %.2f: dropped %d/%d chunks',
                    threshold,
                    dropped,
                    before,
                )

        logger.info(
            "Search '%s...' returned %d results (k=%d, threshold=%.2f)",
            query[:50],
            len(search_results),
            k,
            threshold,
        )
        return search_results

    # -------------------------------------------------------------------------
    # Document processing pipeline
    # -------------------------------------------------------------------------

    def process_document(self, document) -> int:
        """
        Full document processing pipeline:
        1. Extract text
        2. Chunk text
        3. Generate embeddings
        4. Store in ChromaDB
        5. Create Chunk model instances
        """
        from core.models import Chunk

        logger.info(f'Processing document: {document.original_filename}')
        document.status = 'processing'
        document.save(update_fields=['status'])

        try:
            # Step 1: Extract text
            text = self.extract_text(document.file_path, document.file_type)
            if not text.strip():
                raise ValueError('No text content extracted from document')

            # Step 2: Chunk text
            chunks = self.chunk_text(text)
            if not chunks:
                raise ValueError('No chunks generated from document text')

            # Step 3 & 4: Generate embeddings and store in ChromaDB
            chroma_ids = self.add_chunks_to_chroma(
                chunks=chunks,
                document_id=document.id,
                filename=document.original_filename,
                user_id=document.user_id,
                is_shared=document.is_shared,
            )

            # Step 5: Create Chunk model instances
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

            # Update document status
            document.status = 'completed'
            document.processed_at = timezone.now()
            document.save(update_fields=['status', 'processed_at'])

            logger.info(f'Document processed successfully: {document.original_filename} ({len(chunks)} chunks)')
            return len(chunks)

        except Exception as e:
            logger.error(f'Error processing document {document.id}: {e}')
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
        logger.info(f'Chat query (user={user_id}): {question[:100]}')

        # Search for relevant context (scoped to user)
        search_results = self.search(question, user_id=user_id)

        if not search_results:
            if self.collection.count() == 0:
                # No documents uploaded yet — ask LLM to explain
                answer = self._generate_no_context_response(question)
            else:
                # Documents exist but no chunk passed the relevance threshold
                threshold = settings.SEARCH_RELEVANCE_THRESHOLD
                logger.info('No relevant context after threshold filtering (threshold=%.2f)', threshold)
                answer = (
                    'Релевантного контекста не найдено. '
                    'Загруженные документы не содержат информации по данному запросу '
                    f'(порог схожести: {threshold:.2f}). '
                    'Попробуйте переформулировать вопрос.'
                )
            return {
                'answer': answer,
                'sources': [],
                'question': question,
            }

        # Build context from search results
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

        # Generate answer using LLM
        prompt = self._build_rag_prompt(question, context)
        answer = self._generate_llm_response(prompt)

        return {
            'answer': answer,
            'sources': sources,
            'question': question,
        }

    def _build_rag_prompt(self, question: str, context: str) -> str:
        """Build RAG prompt with context and question."""
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
        """Generate response when no documents are available."""
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
            logger.error(f'LLM error ({settings.LLM_BACKEND}): {e}')
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
            return {
                'status': 'offline',
                'error': str(e),
            }
