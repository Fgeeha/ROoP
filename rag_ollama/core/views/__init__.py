"""
Core views package.
Re-exports all views for backward-compatible imports:
    from . import views
    views.index_view, views.api_upload, etc.
"""

# UI pages
# REST API
from .api import (
    api_chat,
    api_chat_clear,
    api_chat_history,
    api_doc_delete,
    api_doc_reindex,
    api_docs_list,
    api_stats,
    api_upload,
)

# HTMX partials
from .htmx import (
    htmx_chat_history,
    htmx_chat_send,
    htmx_clear_chat,
    htmx_doc_delete,
    htmx_doc_list,
    htmx_doc_reindex,
    htmx_doc_status,
    htmx_stats,
    htmx_upload,
)

# Sharing
from .sharing import create_share_chat, create_share_document, shared_view
from .ui import docs_view, index_view

__all__ = [
    # UI
    'index_view',
    'docs_view',
    # HTMX
    'htmx_stats',
    'htmx_chat_send',
    'htmx_chat_history',
    'htmx_clear_chat',
    'htmx_upload',
    'htmx_doc_list',
    'htmx_doc_delete',
    'htmx_doc_reindex',
    'htmx_doc_status',
    # Sharing
    'create_share_chat',
    'create_share_document',
    'shared_view',
    # API
    'api_upload',
    'api_chat',
    'api_chat_history',
    'api_chat_clear',
    'api_docs_list',
    'api_doc_delete',
    'api_doc_reindex',
    'api_stats',
]
