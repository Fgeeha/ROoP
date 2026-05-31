"""
Backward-compatible re-export shim.

All code has been relocated to core/rag/:
  core.rag.engine    — RAGPipeline class
  core.rag.backends  — OllamaBackend, OpenWebUIBackend, create_llm_backend
  core.rag.extractor — text extraction
  core.rag.chunker   — text chunking
  core.rag.store     — ChromaDB operations

External consumers (views, indexing, admin, management commands) continue to
import RAGPipeline from this module without any changes.
"""

from core.rag.backends import OllamaBackend, OpenWebUIBackend, create_llm_backend  # noqa: F401
from core.rag.engine import RAGPipeline

__all__ = ['RAGPipeline', 'OllamaBackend', 'OpenWebUIBackend', 'create_llm_backend']
