"""
ChromaDB vector store operations.

All functions receive the ChromaDB collection and (where needed) the LLM backend
as explicit parameters so they remain independently testable.
"""

import hashlib
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def add_chunks_to_chroma(
    collection,
    backend,
    chunks: list[str],
    document_id: int,
    filename: str,
    user_id: int | None = None,
    is_shared: bool = False,
    progress_callback=None,
) -> list[str]:
    """Add text chunks to ChromaDB with embeddings.

    Embeddings are generated in batches of settings.EMBED_BATCH_SIZE to:
    - Respect OLLAMA_REQUEST_TIMEOUT per request (not per whole document).
    - Bound memory use on machines without GPU.
    - Enable per-batch progress reporting (Stage 3).

    Args:
        progress_callback: optional callable(done: int, total: int) invoked after
            each embed batch.  Receives count of chunks embedded so far and total.
            Ignored when None.

    Returns:
        List of Chroma IDs for the inserted chunks.
    """
    if not chunks:
        return []

    total = len(chunks)
    embed_batch_size = settings.EMBED_BATCH_SIZE

    # Build all Chroma IDs and metadata upfront (cheap, no I/O).
    chroma_ids = []
    metadatas = []
    for i, chunk in enumerate(chunks):
        chunk_hash = hashlib.md5(chunk.encode(), usedforsecurity=False).hexdigest()[:12]
        chroma_ids.append(f'doc{document_id}_chunk{i}_{chunk_hash}')
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

    # Generate embeddings in small batches so each HTTP request is time-bounded.
    logger.info('Generating embeddings for %d chunks (batch_size=%d)...', total, embed_batch_size)
    all_embeddings: list[list[float]] = []
    for batch_start in range(0, total, embed_batch_size):
        batch_end = min(batch_start + embed_batch_size, total)
        batch_embeddings = backend.embed(
            texts=chunks[batch_start:batch_end],
            model=settings.EMBED_MODEL,
        )
        all_embeddings.extend(batch_embeddings)
        logger.debug('Embedded %d/%d chunks', batch_end, total)
        if progress_callback is not None:
            progress_callback(batch_end, total)

    # Write to ChromaDB in batches of 100 (ChromaDB internal limit).
    chroma_batch_size = 100
    for batch_start in range(0, total, chroma_batch_size):
        batch_end = min(batch_start + chroma_batch_size, total)
        collection.add(
            ids=chroma_ids[batch_start:batch_end],
            embeddings=all_embeddings[batch_start:batch_end],
            documents=chunks[batch_start:batch_end],
            metadatas=metadatas[batch_start:batch_end],
        )

    logger.info('Added %d chunks to ChromaDB for document %d', total, document_id)
    return chroma_ids


def delete_document_from_chroma(collection, document_id: int) -> None:
    """Remove all chunks of a document from ChromaDB."""
    try:
        results = collection.get(where={'document_id': str(document_id)})
        if results and results['ids']:
            collection.delete(ids=results['ids'])
            logger.info('Deleted %d chunks from ChromaDB for document %d', len(results['ids']), document_id)
    except Exception as e:
        logger.error('Error deleting from ChromaDB: %s', e)


def update_chroma_metadata_for_document(
    collection,
    document_id: int,
    user_id: int | None,
    is_shared: bool,
) -> int:
    """Update user_id and is_shared metadata for an existing document in ChromaDB."""
    try:
        results = collection.get(where={'document_id': str(document_id)})
        if not results or not results['ids']:
            return 0

        new_metadatas = []
        for meta in results['metadatas']:
            meta['user_id'] = str(user_id) if user_id else ''
            meta['is_shared'] = 'true' if is_shared else 'false'
            new_metadatas.append(meta)

        collection.update(ids=results['ids'], metadatas=new_metadatas)
        logger.info(
            'Updated ChromaDB metadata for document %d: user_id=%s, is_shared=%s (%d chunks)',
            document_id,
            user_id,
            is_shared,
            len(results['ids']),
        )
        return len(results['ids'])
    except Exception as e:
        logger.error('Error updating ChromaDB metadata for document %d: %s', document_id, e)
        return 0


def search(
    collection,
    backend,
    query: str,
    k: int | None = None,
    user_id: int | None = None,
) -> list[dict]:
    """Search ChromaDB for relevant chunks, scoped to user + shared docs.

    ChromaDB with hnsw:space=cosine returns cosine DISTANCE (0 = identical,
    1 = orthogonal), not similarity.  We convert: relevance = 1 - distance,
    then drop chunks below settings.SEARCH_RELEVANCE_THRESHOLD.
    """
    k = k or settings.SEARCH_K
    threshold = settings.SEARCH_RELEVANCE_THRESHOLD

    if collection.count() == 0:
        logger.warning('ChromaDB collection is empty')
        return []

    query_embedding = backend.embed(texts=[query], model=settings.EMBED_MODEL)[0]

    where_filter = None
    if user_id:
        where_filter = {
            '$or': [
                {'user_id': str(user_id)},
                {'is_shared': 'true'},
            ],
        }

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(k, collection.count()),
        include=['documents', 'metadatas', 'distances'],
        where=where_filter,
    )

    search_results = []
    if results and results['documents']:
        for i, (doc, metadata, distance) in enumerate(
            zip(results['documents'][0], results['metadatas'][0], results['distances'][0], strict=False)
        ):
            search_results.append(
                {
                    'content': doc,
                    'metadata': metadata,
                    'relevance': round(1 - distance, 4),
                    'rank': i + 1,
                }
            )

    if threshold > 0 and search_results:
        before = len(search_results)
        search_results = [r for r in search_results if r['relevance'] >= threshold]
        dropped = before - len(search_results)
        if dropped:
            logger.info('Relevance threshold %.2f: dropped %d/%d chunks', threshold, dropped, before)

    logger.info(
        "Search '%s...' returned %d results (k=%d, threshold=%.2f)",
        query[:50],
        len(search_results),
        k,
        threshold,
    )
    return search_results
