"""
Sharing views: create share links, revoke them, and public read-only pages.
"""

import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..models import ChatMessage, Document, SharedLink

logger = logging.getLogger('core')


def _share_url(request, link):
    scheme = 'https' if request.is_secure() else 'http'
    return f'{scheme}://{request.get_host()}/s/{link.token}/'


def _share_response(request, link):
    return JsonResponse(
        {
            'url': _share_url(request, link),
            'token': link.token,
            'expires_at': link.expires_at.isoformat() if link.expires_at else None,
        }
    )


def create_share_chat(request):
    """Create a shared link for user's chat history."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    link = SharedLink.issue(request.user, SharedLink.ShareType.CHAT)
    return _share_response(request, link)


def create_share_document(request, doc_id):
    """Create a shared link for a specific document."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    document = get_object_or_404(Document, id=doc_id, user=request.user)

    link = SharedLink.issue(request.user, SharedLink.ShareType.DOCUMENT, document=document)
    return _share_response(request, link)


def revoke_share(request, token):
    """
    Revoke a share link. Only its owner.

    The lookup is scoped to request.user, so a token belonging to somebody else
    answers 404 — a 403 would confirm that the token exists.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    link = get_object_or_404(SharedLink, token=token, user=request.user)
    link.revoke()
    # Tokens are credentials: log the prefix only, never the whole value.
    logger.info('Share link revoked: type=%s, token=%s...', link.share_type, link.token[:8])

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'revoked': True})

    messages.success(request, 'Ссылка отозвана.')
    return redirect('core:profile')


def shared_view(request, token):
    """Public read-only view for shared link (no login required)."""
    link = get_object_or_404(SharedLink, token=token)

    if not link.is_valid:
        return render(request, 'core/shared_expired.html', status=410)

    if link.share_type == 'chat':
        messages_qs = ChatMessage.objects.filter(user=link.user).order_by('created_at')[:200]
        return render(
            request,
            'core/shared_chat.html',
            {
                'messages': messages_qs,
                'owner': link.user,
                'shared_link': link,
            },
        )

    elif link.share_type == 'document':
        document = link.document
        if not document:
            return render(request, 'core/shared_expired.html', status=410)
        return render(
            request,
            'core/shared_document.html',
            {
                'document': document,
                'owner': link.user,
                'shared_link': link,
            },
        )

    return render(request, 'core/shared_expired.html', status=410)
