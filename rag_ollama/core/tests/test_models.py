"""Tests for core models."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import ChatMessage, Chunk, Document, SharedLink, UserProfile


@pytest.fixture
def user(db):
    return User.objects.create_user(username='testuser', email='test@example.com', password='testpass123')


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(username='admin', email='admin@example.com', password='admin123')


@pytest.fixture
def document(user):
    return Document.objects.create(
        user=user,
        filename='test_abc123.pdf',
        original_filename='test.pdf',
        file_path='/tmp/test_abc123.pdf',
        file_type='pdf',
        size=1024,
        status='completed',
    )


@pytest.fixture
def shared_document(admin_user):
    return Document.objects.create(
        user=admin_user,
        filename='shared_doc.txt',
        original_filename='shared.txt',
        file_path='/tmp/shared_doc.txt',
        file_type='txt',
        size=512,
        status='completed',
        is_shared=True,
    )


# ============================================================================
# Document
# ============================================================================


class TestDocument:
    def test_create_document(self, document):
        assert document.pk is not None
        assert document.original_filename == 'test.pdf'
        assert document.file_type == 'pdf'
        assert document.status == 'completed'
        assert document.user.username == 'testuser'

    def test_document_str(self, document):
        s = str(document)
        assert 'test.pdf' in s

    def test_document_size_display(self, document):
        display = document.size_display
        assert display is not None
        assert isinstance(display, str)

    def test_document_chunks_count(self, document):
        assert document.chunks_count == 0
        Chunk.objects.create(
            document=document,
            content='test chunk',
            chunk_index=0,
            chroma_id='test_chunk_0',
        )
        assert document.chunks_count == 1

    def test_shared_document(self, shared_document):
        assert shared_document.is_shared is True
        assert shared_document.user.is_superuser is True

    def test_document_statuses(self, db, user):
        for status_value, _label in Document.Status.choices:
            doc = Document.objects.create(
                user=user,
                filename=f'f_{status_value}.txt',
                original_filename=f'f_{status_value}.txt',
                file_path=f'/tmp/f_{status_value}.txt',
                file_type='txt',
                size=100,
                status=status_value,
            )
            assert doc.status == status_value


# ============================================================================
# Chunk
# ============================================================================


class TestChunk:
    def test_create_chunk(self, document):
        chunk = Chunk.objects.create(
            document=document,
            content='This is test content for the chunk.',
            chunk_index=0,
            chroma_id='doc1_chunk0_abc',
        )
        assert chunk.pk is not None
        assert chunk.document == document
        assert chunk.chunk_index == 0

    def test_chunk_str(self, document):
        chunk = Chunk.objects.create(
            document=document,
            content='Short content',
            chunk_index=0,
            chroma_id='doc1_chunk0_abc',
        )
        s = str(chunk)
        assert 'test.pdf' in s or 'chunk' in s.lower()


# ============================================================================
# ChatMessage
# ============================================================================


class TestChatMessage:
    def test_create_message(self, user):
        msg = ChatMessage.objects.create(
            user=user,
            role='user',
            content='Hello, world!',
        )
        assert msg.pk is not None
        assert msg.role == 'user'
        assert msg.content == 'Hello, world!'

    def test_message_with_sources(self, user):
        sources = [{'filename': 'doc.pdf', 'chunk_index': 0, 'relevance': 0.95}]
        msg = ChatMessage.objects.create(
            user=user,
            role='assistant',
            content='Answer based on documents.',
            sources=sources,
        )
        assert msg.sources == sources
        assert len(msg.sources) == 1

    def test_message_str(self, user):
        msg = ChatMessage.objects.create(user=user, role='user', content='Test')
        s = str(msg)
        assert 'testuser' in s or 'user' in s.lower()

    def test_messages_ordering(self, user):
        m1 = ChatMessage.objects.create(user=user, role='user', content='First')
        m2 = ChatMessage.objects.create(user=user, role='assistant', content='Second')
        messages = list(ChatMessage.objects.filter(user=user).order_by('created_at'))
        assert messages[0].pk == m1.pk
        assert messages[1].pk == m2.pk


# ============================================================================
# SharedLink
# ============================================================================


class TestSharedLink:
    def test_create_chat_link(self, user):
        link = SharedLink.objects.create(
            user=user,
            share_type='chat',
            token=SharedLink.generate_token(),
        )
        assert link.pk is not None
        assert link.share_type == 'chat'
        assert link.is_active is True
        assert link.is_valid is True

    def test_create_document_link(self, user, document):
        link = SharedLink.objects.create(
            user=user,
            share_type='document',
            document=document,
            token=SharedLink.generate_token(),
        )
        assert link.document == document
        assert link.is_valid is True

    def test_inactive_link_not_valid(self, user):
        link = SharedLink.objects.create(
            user=user,
            share_type='chat',
            token=SharedLink.generate_token(),
            is_active=False,
        )
        assert link.is_valid is False

    def test_expired_link_not_valid(self, user):
        link = SharedLink.objects.create(
            user=user,
            share_type='chat',
            token=SharedLink.generate_token(),
            expires_at=timezone.now() - timedelta(hours=1),
        )
        assert link.is_valid is False

    def test_future_expiry_is_valid(self, user):
        link = SharedLink.objects.create(
            user=user,
            share_type='chat',
            token=SharedLink.generate_token(),
            expires_at=timezone.now() + timedelta(hours=24),
        )
        assert link.is_valid is True

    def test_generate_token_unique(self):
        t1 = SharedLink.generate_token()
        t2 = SharedLink.generate_token()
        assert t1 != t2
        assert len(t1) > 20

    def test_str(self, user):
        link = SharedLink.objects.create(
            user=user,
            share_type='chat',
            token=SharedLink.generate_token(),
        )
        s = str(link)
        assert 'testuser' in s


# ============================================================================
# UserProfile
# ============================================================================


class TestUserProfile:
    def test_create_profile(self, user):
        profile = UserProfile.objects.create(user=user)
        assert profile.pk is not None
        assert profile.is_email_verified is False
        assert profile.personal_api_key == ''

    def test_generate_verification_token(self, user):
        profile = UserProfile.objects.create(user=user)
        token = profile.generate_verification_token()
        assert token
        assert len(token) > 20
        assert profile.email_verification_token == token
        assert profile.email_token_created_at is not None

    def test_token_valid_within_24h(self, user):
        profile = UserProfile.objects.create(user=user)
        profile.generate_verification_token()
        assert profile.is_token_valid() is True

    def test_token_invalid_after_24h(self, user):
        profile = UserProfile.objects.create(user=user)
        profile.generate_verification_token()
        profile.email_token_created_at = timezone.now() - timedelta(hours=25)
        profile.save()
        assert profile.is_token_valid() is False

    def test_token_invalid_without_created_at(self, user):
        profile = UserProfile.objects.create(user=user)
        profile.email_verification_token = 'some-token'
        profile.email_token_created_at = None
        profile.save()
        assert profile.is_token_valid() is False

    def test_generate_api_key(self, user):
        profile = UserProfile.objects.create(user=user)
        key = profile.generate_api_key()
        assert key.startswith('roop_')
        assert len(key) > 10
        assert profile.personal_api_key == key

    def test_regenerate_api_key_changes(self, user):
        profile = UserProfile.objects.create(user=user)
        key1 = profile.generate_api_key()
        key2 = profile.generate_api_key()
        assert key1 != key2

    def test_str(self, user):
        profile = UserProfile.objects.create(user=user)
        s = str(profile)
        assert 'testuser' in s
        assert 'unverified' in s
