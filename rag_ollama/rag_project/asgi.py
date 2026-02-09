"""
ASGI config for RAG Ollama project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rag_project.settings')

application = get_asgi_application()
