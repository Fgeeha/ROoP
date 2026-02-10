"""
Add per-user isolation to Document and ChatMessage,
and SharedLink model for sharing.
"""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0002_userprofile'),
    ]

    operations = [
        # --- Document: add user and is_shared ---
        migrations.AddField(
            model_name='document',
            name='user',
            field=models.ForeignKey(
                blank=True,
                help_text='null = общий документ (администратор)',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='documents',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Владелец',
            ),
        ),
        migrations.AddField(
            model_name='document',
            name='is_shared',
            field=models.BooleanField(
                default=False,
                help_text='Доступен всем пользователям для RAG-поиска',
                verbose_name='Общий доступ',
            ),
        ),
        # --- ChatMessage: add user ---
        migrations.AddField(
            model_name='chatmessage',
            name='user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='chat_messages',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Пользователь',
            ),
        ),
        # --- SharedLink: new model ---
        migrations.CreateModel(
            name='SharedLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, max_length=64, unique=True, verbose_name='Токен')),
                ('share_type', models.CharField(
                    choices=[('chat', 'Чат'), ('document', 'Документ')],
                    max_length=20,
                    verbose_name='Тип',
                )),
                ('is_active', models.BooleanField(default=True, verbose_name='Активна')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')),
                ('expires_at', models.DateTimeField(blank=True, null=True, verbose_name='Срок действия')),
                ('document', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='shared_links',
                    to='core.document',
                    verbose_name='Документ',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='shared_links',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Владелец',
                )),
            ],
            options={
                'verbose_name': 'Публичная ссылка',
                'verbose_name_plural': 'Публичные ссылки',
                'ordering': ['-created_at'],
            },
        ),
    ]
