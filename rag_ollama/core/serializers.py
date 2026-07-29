"""
Django REST Framework serializers for RAG system.
"""

from rest_framework import serializers

from .models import ChatMessage, Chunk, Document, SharedLink


class ChunkSerializer(serializers.ModelSerializer):
    """Serializer for Chunk model."""

    class Meta:
        model = Chunk
        fields = ['id', 'content', 'chunk_index', 'metadata', 'created_at']
        read_only_fields = ['id', 'created_at']


class DocumentSerializer(serializers.ModelSerializer):
    """Serializer for Document model."""

    chunks_count = serializers.ReadOnlyField()
    size_display = serializers.ReadOnlyField()
    owner = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        model = Document
        fields = [
            'id',
            'filename',
            'original_filename',
            'file_type',
            'size',
            'size_display',
            'status',
            'error_message',
            'chunks_count',
            'uploaded_at',
            'processed_at',
            'owner',
            'is_shared',
        ]
        read_only_fields = ['id', 'uploaded_at', 'processed_at']


class DocumentUploadSerializer(serializers.Serializer):
    """Serializer for document upload."""

    file = serializers.FileField(
        help_text='PDF, TXT, MD, DOCX или DOC файл',
    )

    def validate_file(self, value):
        allowed_types = ['.pdf', '.txt', '.md', '.docx', '.doc']
        ext = '.' + value.name.rsplit('.', 1)[-1].lower() if '.' in value.name else ''
        if ext not in allowed_types:
            raise serializers.ValidationError(f'Неподдерживаемый формат файла. Допустимые: {", ".join(allowed_types)}')
        # Size is NOT checked here: validate_and_save_upload() enforces
        # settings.MAX_UPLOAD_SIZE so the view can answer 413 rather than the
        # 400 a serializer ValidationError would produce.
        return value


class ChatRequestSerializer(serializers.Serializer):
    """Serializer for chat request."""

    question = serializers.CharField(
        max_length=2000,
        help_text='Вопрос к RAG системе',
    )


class ChatResponseSerializer(serializers.Serializer):
    """Serializer for chat response."""

    answer = serializers.CharField()
    sources = serializers.ListField(
        child=serializers.DictField(),
        required=False,
    )
    question = serializers.CharField()
    # True when relevant chunks were found but did not fit MAX_CONTEXT_CHARS.
    # `sources` then lists only the chunks the answer was actually built from.
    context_truncated = serializers.BooleanField(required=False, default=False)


class ChatMessageSerializer(serializers.ModelSerializer):
    """Serializer for ChatMessage model."""

    owner = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        model = ChatMessage
        fields = ['id', 'owner', 'role', 'content', 'sources', 'created_at']
        read_only_fields = ['id', 'created_at']


class SharedLinkSerializer(serializers.ModelSerializer):
    """Serializer for SharedLink model."""

    owner = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = SharedLink
        fields = ['id', 'token', 'owner', 'share_type', 'is_active', 'created_at', 'expires_at']
        read_only_fields = ['id', 'token', 'created_at']


class StatsSerializer(serializers.Serializer):
    """Serializer for system statistics."""

    docs_count = serializers.IntegerField()
    chunks_count = serializers.IntegerField()
    total_size = serializers.CharField()
    ollama_status = serializers.CharField()
    chroma_status = serializers.CharField()
