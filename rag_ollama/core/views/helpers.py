"""
Shared helpers for views.
"""

from django.db.models import Q


def user_docs_q(user):
    """Q filter: documents owned by user OR marked as shared."""
    return Q(user=user) | Q(is_shared=True)


def format_size(size_bytes):
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f'{size_bytes:.1f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.1f} TB'
