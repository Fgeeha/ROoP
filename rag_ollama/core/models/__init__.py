"""
Core models package.
Re-exports all models for backward-compatible imports:
    from core.models import Document, Chunk, ChatMessage, SharedLink, UserProfile
"""

from .chat import ChatMessage
from .document import Chunk, Document
from .sharing import SharedLink
from .user import UserProfile

__all__ = [
    'Document',
    'Chunk',
    'ChatMessage',
    'SharedLink',
    'UserProfile',
]
