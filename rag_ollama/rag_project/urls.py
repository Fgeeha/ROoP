"""
URL configuration for RAG Ollama project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]

# Media files (WhiteNoise handles static, but media needs Django serving)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
