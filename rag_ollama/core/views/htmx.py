"""
HTMX partial views (stats, chat send, upload, doc list, etc.).
"""

import logging
import os

from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from ..indexing import (
    QUEUE_FULL_USER_MESSAGE,
    DocumentBusyError,
    DocumentFileMissingError,
    IndexingQueueFullError,
    queue_reindex,
    start_indexing_async,
)
from ..models import ChatMessage, Chunk, Document
from ..rag_pipeline import RAGPipeline
from .helpers import FileValidationError, format_size, user_docs_q, validate_and_save_upload

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
            {'error': 'Введите вопрос'},
        )

    ChatMessage.objects.create(user=request.user, role='user', content=question)

    try:
        pipeline = RAGPipeline.get_instance()
        result = pipeline.chat(question, user_id=request.user.id)

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
        logger.error('Chat error: %s', e)
        return render(
            request,
            'core/partials/chat_error.html',
            {'error': f'Ошибка: {e}'},
        )


def htmx_upload(request):
    """
    Handle file upload via HTMX.

    Validates and saves the file synchronously, then hands off indexing
    to a background thread.  Returns immediately so the browser is not
    blocked by the (potentially slow) embedding + ChromaDB write.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    uploaded_file = request.FILES.get('file')
    if not uploaded_file:
        return render(
            request,
            'core/partials/upload_result.html',
            {'success': False, 'error': 'Файл не выбран'},
        )

    try:
        file_path, ext, unique_name = validate_and_save_upload(uploaded_file)
    except FileValidationError as e:
        # Message is already user-facing (size / extension / MIME mismatch).
        logger.info('Upload rejected: %s', e)
        return render(
            request,
            'core/partials/upload_result.html',
            {'success': False, 'error': str(e)},
        )
    except OSError:
        # Disk full, permissions, etc. — keep internals in the log only.
        logger.exception('Upload failed while writing file to disk')
        return render(
            request,
            'core/partials/upload_result.html',
            {'success': False, 'error': 'Не удалось сохранить файл. Попробуйте ещё раз.'},
        )

    document = Document.objects.create(
        user=request.user,
        filename=unique_name,
        original_filename=uploaded_file.name,
        file_path=file_path,
        file_type=ext,
        size=uploaded_file.size,
        status=Document.Status.PENDING,
    )

    try:
        start_indexing_async(document.id)
    except IndexingQueueFullError:
        # The file stays on disk and the document row is kept, so the user can
        # retry once the backlog drains instead of re-uploading.
        document.status = Document.Status.ERROR
        document.error_message = QUEUE_FULL_USER_MESSAGE
        document.save(update_fields=['status', 'error_message'])
        return render(
            request,
            'core/partials/upload_result.html',
            {'success': False, 'error': QUEUE_FULL_USER_MESSAGE},
            status=503,
        )

    return render(
        request,
        'core/partials/upload_result.html',
        {'queued': True, 'document': document},
    )


def htmx_doc_status(request, doc_id):
    """
    Return a small status partial for a single document.
    Used by HTMX polling after async upload.
    """
    document = get_object_or_404(Document, id=doc_id)

    if document.user != request.user and not request.user.is_staff:
        return JsonResponse({'error': 'Доступ запрещен'}, status=403)

    return render(request, 'core/partials/doc_status.html', {'document': document})


def htmx_doc_list(request):
    """Return document list partial for HTMX."""
    documents = Document.objects.filter(user_docs_q(request.user))
    return render(request, 'core/partials/doc_list.html', {'documents': documents})


def htmx_doc_reindex(request, doc_id):
    """Re-index an existing document via HTMX. Only owner can re-index."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    document = get_object_or_404(Document, id=doc_id)

    if document.user != request.user and not request.user.is_staff:
        return JsonResponse({'error': 'Доступ запрещен'}, status=403)

    def _doc_list(**extra):
        return {'documents': Document.objects.filter(user_docs_q(request.user)), **extra}

    try:
        queue_reindex(document)
    except (DocumentBusyError, DocumentFileMissingError) as e:
        return render(request, 'core/partials/doc_list.html', _doc_list(error=str(e)), status=409)
    except IndexingQueueFullError:
        return render(
            request,
            'core/partials/doc_list.html',
            _doc_list(error=QUEUE_FULL_USER_MESSAGE),
            status=503,
        )

    return render(
        request,
        'core/partials/doc_list.html',
        _doc_list(reindexed=document.original_filename),
    )


def htmx_doc_delete(request, doc_id):
    """Delete document via HTMX. Only owner can delete."""
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    document = get_object_or_404(Document, id=doc_id)

    if document.user != request.user and not request.user.is_staff:
        return JsonResponse({'error': 'Доступ запрещен'}, status=403)

    try:
        pipeline = RAGPipeline.get_instance()
        pipeline.delete_document_from_chroma(document.id)

        if os.path.exists(document.file_path):
            os.remove(document.file_path)

        filename = document.original_filename
        document.delete()

        documents = Document.objects.filter(user_docs_q(request.user))
        return render(
            request,
            'core/partials/doc_list.html',
            {'documents': documents, 'deleted': filename},
        )

    except Exception as e:
        logger.error('Delete error: %s', e)
        return render(
            request,
            'core/partials/doc_list.html',
            {'documents': Document.objects.filter(user_docs_q(request.user)), 'error': str(e)},
        )


def htmx_chat_history(request):
    """Return chat history partial."""
    messages = ChatMessage.objects.filter(user=request.user).order_by('created_at')[:100]
    return render(request, 'core/partials/chat_history.html', {'messages': messages})


def htmx_clear_chat(request):
    """Clear chat history via HTMX."""
    if request.method == 'POST':
        ChatMessage.objects.filter(user=request.user).delete()
    return render(request, 'core/partials/chat_history.html', {'messages': []})
