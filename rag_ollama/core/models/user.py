"""
UserProfile model for extended user data, email verification and API keys.
"""

import secrets

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class UserProfile(models.Model):
    """Extended user profile with email verification and API key."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='Пользователь',
    )
    is_email_verified = models.BooleanField(
        default=False,
        verbose_name='Email подтверждён',
    )
    email_verification_token = models.CharField(
        max_length=128,
        blank=True,
        default='',
        verbose_name='Токен верификации',
    )
    email_token_created_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Токен создан',
    )
    personal_api_key = models.CharField(
        max_length=64,
        blank=True,
        default='',
        verbose_name='Персональный API ключ',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата регистрации',
    )

    class Meta:
        verbose_name = 'Профиль пользователя'
        verbose_name_plural = 'Профили пользователей'

    def __str__(self):
        verified = 'verified' if self.is_email_verified else 'unverified'
        return f"{self.user.username} ({verified})"

    def generate_verification_token(self):
        """Generate a new email verification token."""
        self.email_verification_token = secrets.token_urlsafe(48)
        self.email_token_created_at = timezone.now()
        self.save(update_fields=['email_verification_token', 'email_token_created_at'])
        return self.email_verification_token

    def is_token_valid(self):
        """Check if the verification token is still valid (24h)."""
        if not self.email_token_created_at:
            return False
        delta = timezone.now() - self.email_token_created_at
        return delta.total_seconds() < 86400  # 24 hours

    def generate_api_key(self):
        """Generate a new personal API key."""
        self.personal_api_key = f"roop_{secrets.token_hex(24)}"
        self.save(update_fields=['personal_api_key'])
        return self.personal_api_key
