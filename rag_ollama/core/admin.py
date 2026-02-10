"""
Django Admin configuration for RAG system models.
"""

from django.contrib import admin
from .models import Document, Chunk, ChatMessage, SharedLink, UserProfile


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'original_filename', 'user', 'is_shared', 'file_type',
        'size_display', 'status', 'chunks_count', 'uploaded_at',
    ]
    list_filter = ['status', 'file_type', 'is_shared', 'uploaded_at']
    search_fields = ['original_filename', 'filename', 'user__username']
    readonly_fields = ['uploaded_at', 'processed_at', 'chunks_count', 'size_display']
    raw_id_fields = ['user']
    list_per_page = 25

    fieldsets = (
        ('Владелец и доступ', {
            'fields': ('user', 'is_shared'),
        }),
        ('Основная информация', {
            'fields': ('original_filename', 'filename', 'file_path', 'file_type', 'size', 'size_display'),
        }),
        ('Статус обработки', {
            'fields': ('status', 'error_message', 'chunks_count'),
        }),
        ('Даты', {
            'fields': ('uploaded_at', 'processed_at'),
        }),
    )

    actions = ['make_shared', 'make_private']

    @admin.action(description='Сделать выбранные документы общими (доступны всем)')
    def make_shared(self, request, queryset):
        count = queryset.update(is_shared=True)
        self.message_user(request, f'{count} документов помечены как общие.')
        # Update ChromaDB metadata
        from .rag_pipeline import RAGPipeline
        try:
            pipeline = RAGPipeline.get_instance()
            for doc in queryset:
                pipeline.update_chroma_metadata_for_document(doc.id, doc.user_id, True)
        except Exception:
            pass

    @admin.action(description='Сделать выбранные документы приватными (только владелец)')
    def make_private(self, request, queryset):
        count = queryset.update(is_shared=False)
        self.message_user(request, f'{count} документов помечены как приватные.')
        from .rag_pipeline import RAGPipeline
        try:
            pipeline = RAGPipeline.get_instance()
            for doc in queryset:
                pipeline.update_chroma_metadata_for_document(doc.id, doc.user_id, False)
        except Exception:
            pass


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ['id', 'document', 'chunk_index', 'chroma_id', 'content_preview', 'created_at']
    list_filter = ['document__original_filename', 'created_at']
    search_fields = ['content', 'chroma_id']
    readonly_fields = ['created_at']
    raw_id_fields = ['document']
    list_per_page = 50

    def content_preview(self, obj):
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content
    content_preview.short_description = 'Содержимое'


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'role', 'content_preview', 'created_at']
    list_filter = ['role', 'user', 'created_at']
    search_fields = ['content', 'user__username']
    readonly_fields = ['created_at']
    raw_id_fields = ['user']
    list_per_page = 50

    def content_preview(self, obj):
        return obj.content[:120] + '...' if len(obj.content) > 120 else obj.content
    content_preview.short_description = 'Содержимое'


@admin.register(SharedLink)
class SharedLinkAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'share_type', 'document', 'is_active', 'token_preview', 'created_at', 'expires_at']
    list_filter = ['share_type', 'is_active', 'created_at']
    search_fields = ['user__username', 'token']
    readonly_fields = ['created_at']
    raw_id_fields = ['user', 'document']
    list_per_page = 25

    def token_preview(self, obj):
        return obj.token[:16] + '...'
    token_preview.short_description = 'Токен'


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_email_verified', 'personal_api_key_preview', 'created_at']
    list_filter = ['is_email_verified', 'created_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'email_token_created_at']

    def personal_api_key_preview(self, obj):
        if obj.personal_api_key:
            return obj.personal_api_key[:12] + '...'
        return '-'
    personal_api_key_preview.short_description = 'API-ключ'


# Customize admin site
admin.site.site_header = 'ROoP Администрирование'
admin.site.site_title = 'ROoP'
admin.site.index_title = 'Управление ROoP системой'
