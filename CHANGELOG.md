# Changelog

## [Unreleased]

### Security

- API key comparison changed to constant-time (`hmac.compare_digest`) to prevent timing attacks.
- API key no longer accepted via `?api_key=` query parameter; header-only (`Authorization: Api-Key`).
- File uploads now validated by MIME type (magic bytes) in addition to file extension, rejecting mismatched or binary content.
- Superuser password removed from docker-compose files; read from `DJANGO_SUPERUSER_PASSWORD` env var. Entrypoint warns and skips creation if unset.

### Security

- Dependencies with known HIGH advisories upgraded: Django 5.2.11 → 5.2.16, pillow 12.1.0 → 12.3.0, cryptography 46.0.4 → 49.0.0, lxml 6.0.2 → 6.1.1, urllib3 2.6.3 → 2.7.0. All within the existing version constraints; no application change was needed.
- Dockerfile split into build and runtime stages. Poetry and its own dependency tree (dulwich, requests, …) were being shipped in the runtime image, where they are never executed but still counted against it — `dulwich` and `poetry` each carried a HIGH advisory. The runtime now copies only the resolved virtualenv, and `libpq-dev` was narrowed to `libpq5`. Image size drops from ~1.1 GB to 545 MB.
- Trivy findings on the image: 25 HIGH → 2, both in starlette, which reaches the image only through `chromadb → fastapi` and is never imported (ChromaDB runs as an embedded `PersistentClient`, no ASGI application). fastapi still caps starlette at `<1.0.0`, so the fixed versions are unreachable; both are recorded in `.trivyignore.yaml` with a rationale and an expiry date of 2027-02-01.

### CI/CD

- The release job no longer treats the Trivy verdict as a gate. The scan still runs and reports on a tag, but the image is already published by the time it finishes, and an image with no matching release entry is worse than a release carrying a known finding.
- Images are now published to GitHub Packages (`ghcr.io/fgeeha/roop`) alongside Docker Hub. One build feeds both registries, so the tags are identical.
- Pushing a `v*` tag builds and scans the image, then creates a GitHub Release with generated release notes and `docker pull` commands. Tags carrying a suffix (`v1.2.0-rc1`) are published as pre-releases. Version tags (`1.2.0`, `1.2`) are added to the images. The CD workflow previously ran only after CI on `Master`; tags never reached it, because CI listens on branches only.

### Added

- Share links now expire and can be revoked. `SHARE_LINK_TTL_DAYS` (default 30, `0` = unlimited) sets the lifetime of a newly issued link; `expires_at` was already on the model but was never filled in, so every link issued so far is permanent. The profile page lists active links with their expiry and a revoke button (`POST /share/{token}/revoke/`, owner only — a foreign token answers `404`, not `403`, so revocation cannot be used to probe for valid tokens). An expired or revoked link is no longer handed back by "Поделиться": a new one is issued instead of a URL that answers `410`.
- Document re-indexing. `POST /api/docs/{id}/reindex/`, a "↻" button in the document list, and `manage.py reindex_documents` (`--status`, `--id`, `--dry-run`) re-run indexing from the file already on the server. Previously a document that failed — full queue, Ollama unavailable, OOM-kill, timeout — could only be fixed by deleting it and uploading the file again. Chunks and vectors from the previous attempt are dropped first, so a re-index cannot duplicate the index. Answers `409` when the document is already queued or its file is gone, `503` when the backlog is full. The management command indexes synchronously and requires the web service to be stopped: embedded ChromaDB allows one writer.

### Stability on low-memory machines (16 GB)

- `RAGPipeline` singleton initialisation made thread-safe (`threading.RLock`, double-checked locking). With Gunicorn now running one process and several threads, two concurrent requests on a cold start could each build a `chromadb.PersistentClient` against the same persist directory. The instance is published only after a successful initialisation, so a pipeline whose ChromaDB client failed to start no longer becomes the process-wide singleton; `_initialize()` is idempotent.
- Document indexing serialized: a single long-lived worker thread consumes a bounded queue (max 100 documents) instead of spawning one thread per upload. Concurrent uploads no longer hold several documents' text, chunks and embedding vectors in memory at once. Queue overflow returns `503`; the file is kept and the document marked as errored so it can be re-indexed later.
- Gunicorn switched from 3 worker processes to `1 worker + 4 threads` (`GUNICORN_WORKERS`, `GUNICORN_THREADS`). Embedded ChromaDB (`PersistentClient`) is per-process: multiple processes each held their own copy of the HNSW index and wrote to the same persist directory concurrently.
- `MAX_UPLOAD_SIZE` setting added (default 25 MiB). Enforced before indexing starts, independently of file extension, and re-checked while streaming to disk so an understated `Content-Length` cannot bypass it. REST API answers `413`; UI shows a plain message.
- `FILE_UPLOAD_MAX_MEMORY_SIZE` lowered from 50 MB to 2.5 MiB so larger uploads spill to a temporary file instead of being buffered entirely in RAM.
- Ollama resource limits set in the GPU and CPU compose files: `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=5m`, `OLLAMA_CONTEXT_LENGTH=4096`. All overridable via `.env`.
- PostgreSQL host port no longer published in the standard compose configurations; Django reaches it over the internal Docker network. Host access for development is available via the new `docker-compose.dev-ports.yml` override.

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
