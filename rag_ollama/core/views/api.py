"""
REST API views (DRF).
"""

import logging
import os
import uuid

from django.conf import settings
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import ChatMessage, Chunk, Document
from ..rag_pipeline import RAGPipeline
from ..serializers import (
    ChatMessageSerializer,
    ChatRequestSerializer,
    ChatResponseSerializer,
    DocumentSerializer,
    DocumentUploadSerializer,
)
from .helpers import format_size, user_docs_q

logger = logging.getLogger('core')


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
        result = pipeline.chat(question, user_id=request.user.id)

        # Save to chat history
        ChatMessage.objects.create(user=request.user, role='user', content=question)
        ChatMessage.objects.create(
            user=request.user,
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
    List documents visible to the current user.
    """
    documents = Document.objects.filter(user_docs_q(request.user))
    serializer = DocumentSerializer(documents, many=True)
    return Response({'docs': serializer.data})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def api_doc_delete(request, doc_id):
    """
    DELETE /api/docs/{id}/
    Delete a document and its chunks. Only the owner or admin.
    """
    document = get_object_or_404(Document, id=doc_id)

    if document.user != request.user and not request.user.is_staff:
        return Response({'error': 'Доступ запрещен'}, status=status.HTTP_403_FORBIDDEN)

    try:
        # Delete from ChromaDB
        pipeline = RAGPipeline.get_instance()
        pipeline.delete_document_from_chroma(document.id)

        # Delete file from disk
        if os.path.exists(document.file_path):
            os.remove(document.file_path)

        document.delete()

        return Response({
            'message': f'Документ {doc_id} успешно удален',
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
    Get statistics for current user's environment.
    """
    user_docs = Document.objects.filter(user_docs_q(request.user))
    docs_count = user_docs.filter(status='completed').count()
    chunks_count = Chunk.objects.filter(document__in=user_docs).count()
    total_size_bytes = user_docs.aggregate(total=Sum('size'))['total'] or 0

    pipeline = RAGPipeline.get_instance()
    ollama_info = pipeline.check_ollama_status()
    chroma_info = pipeline.check_chroma_status()

    return Response({
        'docs_count': docs_count,
        'chunks_count': chunks_count,
        'total_size': format_size(total_size_bytes),
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
    Get chat history for the current user.
    """
    messages = ChatMessage.objects.filter(user=request.user).order_by('created_at')[:100]
    serializer = ChatMessageSerializer(messages, many=True)
    return Response({'messages': serializer.data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_chat_clear(request):
    """
    POST /api/chat/clear/
    Clear chat history for the current user.
    """
    count = ChatMessage.objects.filter(user=request.user).count()
    ChatMessage.objects.filter(user=request.user).delete()
    return Response({'message': f'Удалено сообщений: {count}'})
