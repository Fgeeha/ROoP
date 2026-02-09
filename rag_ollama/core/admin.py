"""
Django Admin configuration for RAG system models.
"""

from django.contrib import admin
from .models import Document, Chunk, ChatMessage


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'original_filename', 'file_type', 'size_display',
        'status', 'chunks_count', 'uploaded_at', 'processed_at',
    ]
    list_filter = ['status', 'file_type', 'uploaded_at']
    search_fields = ['original_filename', 'filename']
    readonly_fields = ['uploaded_at', 'processed_at', 'chunks_count', 'size_display']
    list_per_page = 25

    fieldsets = (
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
    list_display = ['id', 'role', 'content_preview', 'created_at']
    list_filter = ['role', 'created_at']
    search_fields = ['content']
    readonly_fields = ['created_at']
    list_per_page = 50

    def content_preview(self, obj):
        return obj.content[:120] + '...' if len(obj.content) > 120 else obj.content
    content_preview.short_description = 'Содержимое'


# Customize admin site
admin.site.site_header = 'ROoP Admin'
admin.site.site_title = 'ROoP'
admin.site.index_title = 'Управление ROoP системой'
