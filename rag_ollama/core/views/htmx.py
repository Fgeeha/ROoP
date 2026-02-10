"""
HTMX partial views (stats, chat send, upload, doc list, etc.).
"""

import logging
import os
import uuid

from django.conf import settings
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from ..models import ChatMessage, Chunk, Document
from ..rag_pipeline import RAGPipeline
from .helpers import format_size, user_docs_q

logger = logging.getLogger('core')


def htmx_stats(request):
    """Return stats partial for HTMX polling."""
    user_docs = Document.objects.filter(user_docs_q(request.user))
    docs_count = user_docs.filter(status='completed').count()
    chunks_count = Chunk.objects.filter(document__in=user_docs).count()
    total_size = user_docs.aggregate(total=Sum('size'))['total'] or 0

    pipeline = RAGPipeline.get_instance()
    ollama_info = pipeline.check_ollama_status()

    return render(
        request,
        'core/partials/stats.html',
        {
            'docs_count': docs_count,
            'chunks_count': chunks_count,
            'total_size': format_size(total_size),
            'ollama_status': ollama_info.get('status', 'unknown'),
        },
    )


def htmx_chat_send(request):
    """Handle chat message via HTMX."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    question = request.POST.get('question', '').strip()
    if not question:
        return render(
            request,
            'core/partials/chat_error.html',
            {
                'error': 'Введите вопрос',
            },
        )

    # Save user message
    ChatMessage.objects.create(user=request.user, role='user', content=question)

    try:
        pipeline = RAGPipeline.get_instance()
        result = pipeline.chat(question, user_id=request.user.id)

        # Save assistant message
        ChatMessage.objects.create(
            user=request.user,
            role='assistant',
            content=result['answer'],
            sources=result.get('sources', []),
        )

        return render(
            request,
            'core/partials/chat_messages.html',
            {
                'user_message': question,
                'answer': result['answer'],
                'sources': result.get('sources', []),
            },
        )
    except Exception as e:
        logger.error(f'Chat error: {e}')
        return render(
            request,
            'core/partials/chat_error.html',
            {
                'error': f'Ошибка: {str(e)}',
            },
        )


def htmx_upload(request):
    """Handle file upload via HTMX."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    uploaded_file = request.FILES.get('file')
    if not uploaded_file:
        return render(
            request,
            'core/partials/upload_result.html',
            {
                'success': False,
                'error': 'Файл не выбран',
            },
        )

    # Validate file type
    ext = uploaded_file.name.rsplit('.', 1)[-1].lower() if '.' in uploaded_file.name else ''
    if ext not in ('pdf', 'txt', 'md'):
        return render(
            request,
            'core/partials/upload_result.html',
            {
                'success': False,
                'error': 'Неподдерживаемый формат. Допустимые: PDF, TXT, MD',
            },
        )

    try:
        # Save file
        unique_name = f'{uuid.uuid4().hex[:12]}_{uploaded_file.name}'
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'documents')
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, unique_name)

        with open(file_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        # Create document record (owned by current user)
        document = Document.objects.create(
            user=request.user,
            filename=unique_name,
            original_filename=uploaded_file.name,
            file_path=file_path,
            file_type=ext,
            size=uploaded_file.size,
            status='pending',
        )

        # Process document synchronously
        pipeline = RAGPipeline.get_instance()
        chunks_count = pipeline.process_document(document)

        return render(
            request,
            'core/partials/upload_result.html',
            {
                'success': True,
                'document': document,
                'chunks_count': chunks_count,
            },
        )

    except Exception as e:
        logger.error(f'Upload error: {e}')
        return render(
            request,
            'core/partials/upload_result.html',
            {
                'success': False,
                'error': str(e),
            },
        )


def htmx_doc_list(request):
    """Return document list partial for HTMX."""
    documents = Document.objects.filter(user_docs_q(request.user))
    return render(
        request,
        'core/partials/doc_list.html',
        {
            'documents': documents,
        },
    )


def htmx_doc_delete(request, doc_id):
    """Delete document via HTMX. Only owner can delete."""
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    document = get_object_or_404(Document, id=doc_id)

    # Only the owner (or admin) can delete
    if document.user != request.user and not request.user.is_staff:
        return JsonResponse({'error': 'Доступ запрещен'}, status=403)

    try:
        # Delete from ChromaDB
        pipeline = RAGPipeline.get_instance()
        pipeline.delete_document_from_chroma(document.id)

        # Delete file from disk
        if os.path.exists(document.file_path):
            os.remove(document.file_path)

        filename = document.original_filename
        document.delete()

        documents = Document.objects.filter(user_docs_q(request.user))
        return render(
            request,
            'core/partials/doc_list.html',
            {
                'documents': documents,
                'deleted': filename,
            },
        )

    except Exception as e:
        logger.error(f'Delete error: {e}')
        return render(
            request,
            'core/partials/doc_list.html',
            {
                'documents': Document.objects.filter(user_docs_q(request.user)),
                'error': str(e),
            },
        )


def htmx_chat_history(request):
    """Return chat history partial."""
    messages = ChatMessage.objects.filter(user=request.user).order_by('created_at')[:100]
    return render(
        request,
        'core/partials/chat_history.html',
        {
            'messages': messages,
        },
    )


def htmx_clear_chat(request):
    """Clear chat history via HTMX."""
    if request.method == 'POST':
        ChatMessage.objects.filter(user=request.user).delete()
    return render(
        request,
        'core/partials/chat_history.html',
        {
            'messages': [],
        },
    )
