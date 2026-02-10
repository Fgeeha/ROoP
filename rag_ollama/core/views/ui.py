"""
Template views (UI pages).
"""

from django.db.models import Sum
from django.shortcuts import render

from ..models import ChatMessage, Chunk, Document
from .helpers import format_size, user_docs_q


def index_view(request):
    """Main page - Chat interface."""
    messages = ChatMessage.objects.filter(user=request.user).order_by('created_at')[:100]
    docs_count = Document.objects.filter(user_docs_q(request.user), status='completed').count()
    chunks_count = Chunk.objects.filter(document__in=Document.objects.filter(user_docs_q(request.user))).count()
    return render(
        request,
        'core/index.html',
        {
            'messages': messages,
            'docs_count': docs_count,
            'chunks_count': chunks_count,
        },
    )


def docs_view(request):
    """Documents management page."""
    documents = Document.objects.filter(user_docs_q(request.user))
    total_size = documents.aggregate(total=Sum('size'))['total'] or 0
    return render(
        request,
        'core/docs.html',
        {
            'documents': documents,
            'total_size': format_size(total_size),
            'docs_count': documents.count(),
        },
    )
