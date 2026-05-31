# Changelog

## [Unreleased]

### Security

- API key comparison changed to constant-time (`hmac.compare_digest`) to prevent timing attacks.
- API key no longer accepted via `?api_key=` query parameter; header-only (`Authorization: Api-Key`).
- File uploads now validated by MIME type (magic bytes) in addition to file extension, rejecting mismatched or binary content.
- Superuser password removed from docker-compose files; read from `DJANGO_SUPERUSER_PASSWORD` env var. Entrypoint warns and skips creation if unset.

### Performance

- Document indexing moved to a background daemon thread; HTTP response returns immediately after file upload.
- Embedding requests batched in groups of `EMBED_BATCH_SIZE` (default 10) instead of one large request per document, reducing per-request wall time and memory pressure on CPU-only machines.
- `OLLAMA_REQUEST_TIMEOUT` setting added (default 300 s); passed to `ollama.Client` to bound embed and chat requests. Previously, Ollama requests had no deadline and could block indefinitely on CPU.
- Stuck documents (status `processing` after server kill / OOM) recovered at startup via `manage.py recover_stuck_documents`; no manual intervention needed.

### RAG quality

- `SEARCH_K` configurable via env (default raised from 4 to 6).
- Relevance threshold (`SEARCH_RELEVANCE_THRESHOLD`, default 0.20) applied after vector search: chunks below the cosine-similarity floor are dropped before building LLM context. Threshold direction verified: low distance = high relevance = passes filter.
- Empty-context edge case: when all chunks fail the threshold, a descriptive message is returned instead of passing empty context to the LLM.

### Refactoring

- `core/rag_pipeline.py` (913 lines) decomposed into focused modules under `core/rag/`:
  - `backends.py` — Ollama and Open WebUI API clients
  - `extractor.py` — document text extraction (PDF, DOCX, DOC, TXT/MD)
  - `chunker.py` — hierarchical text chunking
  - `store.py` — ChromaDB vector operations
  - `engine.py` — `RAGPipeline` orchestrator singleton
  - `rag_pipeline.py` retained as a thin re-export shim for backward compatibility.
- File upload validation and save logic extracted to `validate_and_save_upload()` helper, eliminating ~50-line duplication between API and HTMX views.

### Fixes

- Indexing progress (`processed_chunks / total_chunks`) persisted to DB via point `UPDATE` after each embed batch; HTMX status poller shows "N / M chunks" in real time.
- Error message from failed indexing displayed in the UI status badge instead of a silent error indicator.
- `DJANGO_SUPERUSER_PASSWORD=admin123` removed from all docker-compose files.
