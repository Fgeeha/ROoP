"""
URL configuration for core app.
Includes both API endpoints and UI template views.
"""

from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # =========================================================================
    # UI Views (Django Templates + HTMX)
    # =========================================================================
    path('', views.index_view, name='index'),
    path('docs/', views.docs_view, name='docs'),

    # HTMX partials
    path('htmx/stats/', views.htmx_stats, name='htmx_stats'),
    path('htmx/chat/send/', views.htmx_chat_send, name='htmx_chat_send'),
    path('htmx/chat/history/', views.htmx_chat_history, name='htmx_chat_history'),
    path('htmx/chat/clear/', views.htmx_clear_chat, name='htmx_clear_chat'),
    path('htmx/upload/', views.htmx_upload, name='htmx_upload'),
    path('htmx/docs/', views.htmx_doc_list, name='htmx_doc_list'),
    path('htmx/docs/<int:doc_id>/delete/', views.htmx_doc_delete, name='htmx_doc_delete'),

    # =========================================================================
    # REST API Endpoints
    # =========================================================================
    path('api/upload/', views.api_upload, name='api_upload'),
    path('api/chat/', views.api_chat, name='api_chat'),
    path('api/chat/history/', views.api_chat_history, name='api_chat_history'),
    path('api/chat/clear/', views.api_chat_clear, name='api_chat_clear'),
    path('api/docs/', views.api_docs_list, name='api_docs_list'),
    path('api/docs/<int:doc_id>/', views.api_doc_delete, name='api_doc_delete'),
    path('api/stats/', views.api_stats, name='api_stats'),
]
