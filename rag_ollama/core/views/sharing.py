"""
Sharing views: create share links and public read-only pages.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from ..models import ChatMessage, Document, SharedLink


def create_share_chat(request):
    """Create a shared link for user's chat history."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    link, _created = SharedLink.objects.get_or_create(
        user=request.user,
        share_type='chat',
        is_active=True,
        document=None,
        defaults={'token': SharedLink.generate_token()},
    )

    scheme = 'https' if request.is_secure() else 'http'
    host = request.get_host()
    share_url = f"{scheme}://{host}/s/{link.token}/"

    return JsonResponse({'url': share_url, 'token': link.token})


def create_share_document(request, doc_id):
    """Create a shared link for a specific document."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    document = get_object_or_404(Document, id=doc_id, user=request.user)

    link, _created = SharedLink.objects.get_or_create(
        user=request.user,
        share_type='document',
        document=document,
        is_active=True,
        defaults={'token': SharedLink.generate_token()},
    )

    scheme = 'https' if request.is_secure() else 'http'
    host = request.get_host()
    share_url = f"{scheme}://{host}/s/{link.token}/"

    return JsonResponse({'url': share_url, 'token': link.token})


def shared_view(request, token):
    """Public read-only view for shared link (no login required)."""
    link = get_object_or_404(SharedLink, token=token)

    if not link.is_valid:
        return render(request, 'core/shared_expired.html', status=410)

    if link.share_type == 'chat':
        messages = ChatMessage.objects.filter(user=link.user).order_by('created_at')[:200]
        return render(request, 'core/shared_chat.html', {
            'messages': messages,
            'owner': link.user,
            'shared_link': link,
        })

    elif link.share_type == 'document':
        document = link.document
        if not document:
            return render(request, 'core/shared_expired.html', status=410)
        return render(request, 'core/shared_document.html', {
            'document': document,
            'owner': link.user,
            'shared_link': link,
        })

    return render(request, 'core/shared_expired.html', status=410)
