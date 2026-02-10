"""
Chat message model.
"""

from django.contrib.auth.models import User
from django.db import models


class ChatMessage(models.Model):
    """Chat history model."""

    class Role(models.TextChoices):
        USER = 'user', 'Пользователь'
        ASSISTANT = 'assistant', 'Ассистент'

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='chat_messages',
        null=True,
        blank=True,
        verbose_name='Пользователь',
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        verbose_name='Роль',
    )
    content = models.TextField(
        verbose_name='Содержимое',
    )
    sources = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Источники',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания',
    )

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Сообщение чата'
        verbose_name_plural = 'Сообщения чата'

    def __str__(self):
        owner = self.user.username if self.user else '?'
        return f'[{owner}/{self.get_role_display()}] {self.content[:80]}...'
