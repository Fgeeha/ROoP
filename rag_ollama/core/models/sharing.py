"""
SharedLink model for public read-only access to chat or documents.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .document import Document


class SharedLink(models.Model):
    """Shared link for read-only access to chat or document."""

    class ShareType(models.TextChoices):
        CHAT = 'chat', 'Чат'
        DOCUMENT = 'document', 'Документ'

    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name='Токен',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='shared_links',
        verbose_name='Владелец',
    )
    share_type = models.CharField(
        max_length=20,
        choices=ShareType.choices,
        verbose_name='Тип',
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='shared_links',
        verbose_name='Документ',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активна',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания',
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Срок действия',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Публичная ссылка'
        verbose_name_plural = 'Публичные ссылки'

    def __str__(self):
        return f'{self.get_share_type_display()} by {self.user.username} ({self.token[:8]}...)'

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(32)

    @staticmethod
    def default_expiry():
        """Expiry for a newly issued link, or None when SHARE_LINK_TTL_DAYS <= 0."""
        days = settings.SHARE_LINK_TTL_DAYS
        if days <= 0:
            return None
        return timezone.now() + timedelta(days=days)

    @classmethod
    def issue(cls, user, share_type, document=None):
        """
        Return a usable share link for this target, creating one if needed.

        An existing link is reused only while it is still valid.  Handing back
        a revoked or expired one would give the user a URL that answers 410.
        """
        link = (
            cls.objects.filter(
                user=user,
                share_type=share_type,
                document=document,
                is_active=True,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
            .order_by('-created_at')
            .first()
        )
        if link is not None:
            return link

        return cls.objects.create(
            user=user,
            share_type=share_type,
            document=document,
            token=cls.generate_token(),
            expires_at=cls.default_expiry(),
        )

    def revoke(self):
        """Deactivate the link. Idempotent."""
        if self.is_active:
            self.is_active = False
            self.save(update_fields=['is_active'])

    @property
    def is_valid(self):
        if not self.is_active:
            return False
        return not (self.expires_at and timezone.now() > self.expires_at)
