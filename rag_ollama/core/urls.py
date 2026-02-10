"""
URL configuration for core app.
Includes API endpoints, UI views and authentication.
"""

from django.contrib.auth.decorators import login_required
from django.urls import path

from . import auth_views, views

app_name = 'core'

urlpatterns = [
    # =========================================================================
    # Authentication
    # =========================================================================
    path('accounts/register/', auth_views.register_view, name='register'),
    path('accounts/login/', auth_views.login_view, name='login'),
    path('accounts/logout/', auth_views.logout_view, name='logout'),
    path('accounts/verify/<str:token>/', auth_views.verify_email_view, name='verify_email'),
    path('accounts/resend-verification/', auth_views.resend_verification_view, name='resend_verification'),
    path('accounts/password-reset/', auth_views.password_reset_request_view, name='password_reset'),
    path('accounts/password-reset/confirm/<str:token>/', auth_views.password_reset_confirm_view, name='password_reset_confirm'),
    path('accounts/profile/', auth_views.profile_view, name='profile'),

    # =========================================================================
    # UI Views (Django Templates + HTMX) - require login
    # =========================================================================
    path('', login_required(views.index_view), name='index'),
    path('docs/', login_required(views.docs_view), name='docs'),

    # HTMX partials (also require login)
    path('htmx/stats/', login_required(views.htmx_stats), name='htmx_stats'),
    path('htmx/chat/send/', login_required(views.htmx_chat_send), name='htmx_chat_send'),
    path('htmx/chat/history/', login_required(views.htmx_chat_history), name='htmx_chat_history'),
    path('htmx/chat/clear/', login_required(views.htmx_clear_chat), name='htmx_clear_chat'),
    path('htmx/upload/', login_required(views.htmx_upload), name='htmx_upload'),
    path('htmx/docs/', login_required(views.htmx_doc_list), name='htmx_doc_list'),
    path('htmx/docs/<int:doc_id>/delete/', login_required(views.htmx_doc_delete), name='htmx_doc_delete'),

    # =========================================================================
    # Sharing (create requires login, view is public)
    # =========================================================================
    path('share/chat/', login_required(views.create_share_chat), name='share_chat'),
    path('share/doc/<int:doc_id>/', login_required(views.create_share_document), name='share_document'),
    path('s/<str:token>/', views.shared_view, name='shared_view'),

    # =========================================================================
    # REST API Endpoints (auth handled by DRF permissions)
    # =========================================================================
    path('api/upload/', views.api_upload, name='api_upload'),
    path('api/chat/', views.api_chat, name='api_chat'),
    path('api/chat/history/', views.api_chat_history, name='api_chat_history'),
    path('api/chat/clear/', views.api_chat_clear, name='api_chat_clear'),
    path('api/docs/', views.api_docs_list, name='api_docs_list'),
    path('api/docs/<int:doc_id>/', views.api_doc_delete, name='api_doc_delete'),
    path('api/stats/', views.api_stats, name='api_stats'),
]
