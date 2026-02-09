"""
Django views for RAG system.
Combines Django REST Framework API views and Django Template views.
"""

import logging
import os
import uuid

from django.conf import settings
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .models import ChatMessage, Chunk, Document
from .rag_pipeline import RAGPipeline
from .serializers import (
    ChatMessageSerializer,
    ChatRequestSerializer,
    ChatResponseSerializer,
    DocumentSerializer,
    DocumentUploadSerializer,
    StatsSerializer,
)

logger = logging.getLogger('core')


# =============================================================================
# Template Views (UI)
# =============================================================================

def index_view(request):
    """Main page - Chat interface."""
    messages = ChatMessage.objects.all().order_by('created_at')[:100]
    docs_count = Document.objects.filter(status='completed').count()
    chunks_count = Chunk.objects.count()
    return render(request, 'core/index.html', {
        'messages': messages,
        'docs_count': docs_count,
        'chunks_count': chunks_count,
    })


def docs_view(request):
    """Documents management page."""
    documents = Document.objects.all()
    total_size = documents.aggregate(total=Sum('size'))['total'] or 0
    return render(request, 'core/docs.html', {
        'documents': documents,
        'total_size': _format_size(total_size),
        'docs_count': documents.count(),
    })


def _format_size(size_bytes):
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# =============================================================================
# HTMX Partial Views
# =============================================================================

def htmx_stats(request):
    """Return stats partial for HTMX polling."""
    docs_count = Document.objects.filter(status='completed').count()
    chunks_count = Chunk.objects.count()
    total_size = Document.objects.aggregate(total=Sum('size'))['total'] or 0

    pipeline = RAGPipeline.get_instance()
    ollama_info = pipeline.check_ollama_status()

    return render(request, 'core/partials/stats.html', {
        'docs_count': docs_count,
        'chunks_count': chunks_count,
        'total_size': _format_size(total_size),
        'ollama_status': ollama_info.get('status', 'unknown'),
    })


def htmx_chat_send(request):
    """Handle chat message via HTMX."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    question = request.POST.get('question', '').strip()
    if not question:
        return render(request, 'core/partials/chat_error.html', {
            'error': 'Введите вопрос',
        })

    # Save user message
    ChatMessage.objects.create(role='user', content=question)

    try:
        pipeline = RAGPipeline.get_instance()
        result = pipeline.chat(question)

        # Save assistant message
        ChatMessage.objects.create(
            role='assistant',
            content=result['answer'],
            sources=result.get('sources', []),
        )

        return render(request, 'core/partials/chat_messages.html', {
            'user_message': question,
            'answer': result['answer'],
            'sources': result.get('sources', []),
        })
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return render(request, 'core/partials/chat_error.html', {
            'error': f'Ошибка: {str(e)}',
        })


def htmx_upload(request):
    """Handle file upload via HTMX."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    uploaded_file = request.FILES.get('file')
    if not uploaded_file:
        return render(request, 'core/partials/upload_result.html', {
            'success': False,
            'error': 'Файл не выбран',
        })

    # Validate file type
    ext = uploaded_file.name.rsplit('.', 1)[-1].lower() if '.' in uploaded_file.name else ''
    if ext not in ('pdf', 'txt', 'md'):
        return render(request, 'core/partials/upload_result.html', {
            'success': False,
            'error': 'Неподдерживаемый формат. Допустимые: PDF, TXT, MD',
        })

    try:
        # Save file
        unique_name = f"{uuid.uuid4().hex[:12]}_{uploaded_file.name}"
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'documents')
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, unique_name)

        with open(file_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        # Create document record
        document = Document.objects.create(
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

        return render(request, 'core/partials/upload_result.html', {
            'success': True,
            'document': document,
            'chunks_count': chunks_count,
        })

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return render(request, 'core/partials/upload_result.html', {
            'success': False,
            'error': str(e),
        })


def htmx_doc_list(request):
    """Return document list partial for HTMX."""
    documents = Document.objects.all()
    return render(request, 'core/partials/doc_list.html', {
        'documents': documents,
    })


def htmx_doc_delete(request, doc_id):
    """Delete document via HTMX."""
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    document = get_object_or_404(Document, id=doc_id)

    try:
        # Delete from ChromaDB
        pipeline = RAGPipeline.get_instance()
        pipeline.delete_document_from_chroma(document.id)

        # Delete file from disk
        if os.path.exists(document.file_path):
            os.remove(document.file_path)

        filename = document.original_filename
        document.delete()

        documents = Document.objects.all()
        return render(request, 'core/partials/doc_list.html', {
            'documents': documents,
            'deleted': filename,
        })

    except Exception as e:
        logger.error(f"Delete error: {e}")
        return render(request, 'core/partials/doc_list.html', {
            'documents': Document.objects.all(),
            'error': str(e),
        })


def htmx_chat_history(request):
    """Return chat history partial."""
    messages = ChatMessage.objects.all().order_by('created_at')[:100]
    return render(request, 'core/partials/chat_history.html', {
        'messages': messages,
    })


def htmx_clear_chat(request):
    """Clear chat history via HTMX."""
    if request.method == 'POST':
        ChatMessage.objects.all().delete()
    return render(request, 'core/partials/chat_history.html', {
        'messages': [],
    })


# =============================================================================
# REST API Views
# =============================================================================

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def api_upload(request):
    """
    POST /api/upload/
    Upload a document (PDF, TXT, MD).
    """
    serializer = DocumentUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    uploaded_file = serializer.validated_data['file']
    ext = uploaded_file.name.rsplit('.', 1)[-1].lower()

    # Save file to disk
    unique_name = f"{uuid.uuid4().hex[:12]}_{uploaded_file.name}"
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'documents')
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, unique_name)

    with open(file_path, 'wb+') as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    # Create document record
    document = Document.objects.create(
        filename=unique_name,
        original_filename=uploaded_file.name,
        file_path=file_path,
        file_type=ext,
        size=uploaded_file.size,
        status='pending',
    )

    try:
        # Process document synchronously
        pipeline = RAGPipeline.get_instance()
        chunks_count = pipeline.process_document(document)

        document.refresh_from_db()
        return Response({
            'id': document.id,
            'filename': document.original_filename,
            'chunks': chunks_count,
            'status': document.status,
            'size': document.size_display,
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        document.refresh_from_db()
        return Response({
            'id': document.id,
            'filename': document.original_filename,
            'status': document.status,
            'error': str(e),
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_chat(request):
    """
    POST /api/chat/
    Send a question and get RAG-based answer.
    """
    serializer = ChatRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    question = serializer.validated_data['question']

    try:
        pipeline = RAGPipeline.get_instance()
        result = pipeline.chat(question)

        # Save to chat history
        ChatMessage.objects.create(role='user', content=question)
        ChatMessage.objects.create(
            role='assistant',
            content=result['answer'],
            sources=result.get('sources', []),
        )

        response_serializer = ChatResponseSerializer(data=result)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.data)

    except Exception as e:
        logger.error(f"API chat error: {e}")
        return Response({
            'error': str(e),
            'question': question,
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_docs_list(request):
    """
    GET /api/docs/
    List all uploaded documents.
    """
    documents = Document.objects.all()
    serializer = DocumentSerializer(documents, many=True)
    return Response({'docs': serializer.data})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def api_doc_delete(request, doc_id):
    """
    DELETE /api/docs/{id}/
    Delete a document and its chunks.
    """
    document = get_object_or_404(Document, id=doc_id)

    try:
        # Delete from ChromaDB
        pipeline = RAGPipeline.get_instance()
        pipeline.delete_document_from_chroma(document.id)

        # Delete file from disk
        if os.path.exists(document.file_path):
            os.remove(document.file_path)

        document.delete()

        return Response({
            'message': f'Document {doc_id} deleted successfully',
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"API delete error: {e}")
        return Response({
            'error': str(e),
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_stats(request):
    """
    GET /api/stats/
    Get system statistics.
    """
    docs_count = Document.objects.filter(status='completed').count()
    chunks_count = Chunk.objects.count()
    total_size_bytes = Document.objects.aggregate(total=Sum('size'))['total'] or 0

    pipeline = RAGPipeline.get_instance()
    ollama_info = pipeline.check_ollama_status()
    chroma_info = pipeline.check_chroma_status()

    return Response({
        'docs_count': docs_count,
        'chunks_count': chunks_count,
        'total_size': _format_size(total_size_bytes),
        'ollama_status': ollama_info.get('status', 'unknown'),
        'ollama_models': ollama_info.get('models', []),
        'chroma_status': chroma_info.get('status', 'unknown'),
        'chroma_docs': chroma_info.get('documents_in_collection', 0),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chat_history(request):
    """
    GET /api/chat/history/
    Get chat history.
    """
    messages = ChatMessage.objects.all().order_by('created_at')[:100]
    serializer = ChatMessageSerializer(messages, many=True)
    return Response({'messages': serializer.data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_chat_clear(request):
    """
    POST /api/chat/clear/
    Clear chat history.
    """
    count = ChatMessage.objects.count()
    ChatMessage.objects.all().delete()
    return Response({'message': f'Deleted {count} messages'})
