"""
Document and Chunk models for RAG system.
"""

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Document(models.Model):
    """Uploaded document model."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает обработки'
        PROCESSING = 'processing', 'Обрабатывается'
        COMPLETED = 'completed', 'Обработан'
        ERROR = 'error', 'Ошибка'

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='documents',
        null=True,
        blank=True,
        verbose_name='Владелец',
        help_text='null = общий документ (администратор)',
    )
    is_shared = models.BooleanField(
        default=False,
        verbose_name='Общий доступ',
        help_text='Доступен всем пользователям для RAG-поиска',
    )
    filename = models.CharField(
        max_length=500,
        verbose_name='Имя файла',
    )
    original_filename = models.CharField(
        max_length=500,
        verbose_name='Оригинальное имя',
    )
    file_path = models.CharField(
        max_length=1000,
        verbose_name='Путь к файлу',
    )
    file_type = models.CharField(
        max_length=20,
        verbose_name='Тип файла',
    )
    size = models.BigIntegerField(
        default=0,
        verbose_name='Размер (байт)',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Статус',
    )
    error_message = models.TextField(
        blank=True,
        default='',
        verbose_name='Сообщение об ошибке',
    )
    uploaded_at = models.DateTimeField(
        default=timezone.now,
        verbose_name='Дата загрузки',
    )
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата обработки',
    )

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Документ'
        verbose_name_plural = 'Документы'

    def __str__(self):
        owner = self.user.username if self.user else 'shared'
        return f"{self.original_filename} [{owner}] ({self.get_status_display()})"

    @property
    def chunks_count(self):
        return self.chunks.count()

    @property
    def size_display(self):
        """Human-readable file size."""
        size = self.size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class Chunk(models.Model):
    """Document chunk model for RAG processing."""

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='chunks',
        verbose_name='Документ',
    )
    content = models.TextField(
        verbose_name='Содержимое',
    )
    chunk_index = models.IntegerField(
        default=0,
        verbose_name='Индекс чанка',
    )
    chroma_id = models.CharField(
        max_length=200,
        unique=True,
        verbose_name='ChromaDB ID',
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Метаданные',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания',
    )

    class Meta:
        ordering = ['document', 'chunk_index']
        verbose_name = 'Чанк'
        verbose_name_plural = 'Чанки'

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.original_filename}"
