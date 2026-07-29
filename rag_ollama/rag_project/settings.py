"""
Django settings for RAG Ollama project.
Production-ready configuration for local closed-circuit RAG system.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Security
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-me-in-production')
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,0.0.0.0').split(',')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'corsheaders',
    # Local
    'core.apps.CoreConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.RequestLoggingMiddleware',
]

ROOT_URLCONF = 'rag_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'rag_project.wsgi.application'
ASGI_APPLICATION = 'rag_project.asgi.application'

# Database - PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB', 'roop'),
        'USER': os.getenv('POSTGRES_USER', 'roop'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'roop'),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'),
        'OPTIONS': {
            'connect_timeout': 5,
        },
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Volgograd'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# Media files (uploaded documents)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'core.authentication.APIKeyAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/minute',
        'user': '60/minute',
    },
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ],
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
}

# CORS settings
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

# CSRF - build trusted origins from ALLOWED_HOSTS automatically.
# For closed-circuit / corporate networks this is safe.
_csrf_origins = set()
for _host in ALLOWED_HOSTS:
    if _host in ('*', '0.0.0.0'):  # noqa: S104
        continue  # skip wildcards, handled below
    _csrf_origins.add(f'http://{_host}')
    _csrf_origins.add(f'http://{_host}:8000')
    _csrf_origins.add(f'https://{_host}')

# Also trust origins from CSRF_EXTRA_ORIGINS env var (comma-separated)
for _origin in os.getenv('CSRF_EXTRA_ORIGINS', '').split(','):
    _origin = _origin.strip()
    if _origin:
        _csrf_origins.add(_origin)

CSRF_TRUSTED_ORIGINS = (
    sorted(_csrf_origins)
    if _csrf_origins
    else [
        'http://localhost',
        'http://localhost:8000',
        'http://127.0.0.1',
        'http://127.0.0.1:8000',
    ]
)

# If ALLOWED_HOSTS contains '*', we're on a local/corporate network.
# Disable Origin check so any host is trusted.
if '*' in ALLOWED_HOSTS:
    CSRF_TRUSTED_ORIGINS = ['http://*', 'https://*']

# File upload settings
#
# Two different knobs — do not confuse them:
#
#   FILE_UPLOAD_MAX_MEMORY_SIZE — Django's buffering threshold.  An upload
#       larger than this is streamed to a temporary file instead of being held
#       entirely in RAM.  Keeping it low is what bounds memory during upload.
#   MAX_UPLOAD_SIZE — the hard, user-facing limit.  Enforced in
#       core.views.helpers.validate_and_save_upload before indexing starts.
#
FILE_UPLOAD_MAX_MEMORY_SIZE = 2621440  # 2.5 MiB — spill to a temp file beyond this
# Applies to the non-file part of a request body; file uploads are excluded.
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50MB

# Hard limit for a single uploaded document, in bytes.  Default 25 MiB, chosen
# for a 16 GB machine: extraction + chunking + embeddings peak at several times
# the source size, and indexing is serialized to one document at a time.
MAX_UPLOAD_SIZE = int(os.getenv('MAX_UPLOAD_SIZE', '26214400'))  # 25 MiB

# LLM Backend: "ollama" (direct) or "openwebui" (via Open WebUI OpenAI-compatible API)
LLM_BACKEND = os.getenv('LLM_BACKEND', 'ollama').lower()

# Ollama settings (used when LLM_BACKEND=ollama)
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434')
EMBED_MODEL = os.getenv('EMBED_MODEL', 'nomic-embed-text')
LLM_MODEL = os.getenv('LLM_MODEL', 'mistral')
# Per-request timeout for Ollama API calls (embed + chat).
# CPU machines can take minutes per request; 300s is generous but finite.
OLLAMA_REQUEST_TIMEOUT = int(os.getenv('OLLAMA_REQUEST_TIMEOUT', '300'))

# Open WebUI settings (used when LLM_BACKEND=openwebui)
OPENWEBUI_URL = os.getenv('OPENWEBUI_URL', 'http://localhost:3000')
OPENWEBUI_API_KEY = os.getenv('OPENWEBUI_API_KEY', '')

# ChromaDB settings
CHROMA_PERSIST_DIR = os.getenv('CHROMA_PERSIST_DIR', str(BASE_DIR / 'chroma_data'))
CHROMA_COLLECTION = os.getenv('CHROMA_COLLECTION', 'rag_documents')

# RAG settings
CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', '1000'))
CHUNK_OVERLAP = int(os.getenv('CHUNK_OVERLAP', '200'))
# Number of text chunks per single embed() request to Ollama.
# Smaller batches = shorter per-request wall time on CPU, finer progress granularity.
EMBED_BATCH_SIZE = int(os.getenv('EMBED_BATCH_SIZE', '10'))
# SEARCH_K: number of chunks retrieved before relevance filtering.
# nomic-embed-text chunks at ~1000 chars; Mistral context window is 32k tokens.
# 6-8 chunks gives ~6-8k chars of context -- well within the window.
SEARCH_K = int(os.getenv('SEARCH_K', '6'))
# SEARCH_RELEVANCE_THRESHOLD: cosine similarity floor [0.0, 1.0].
# ChromaDB returns cosine DISTANCE; relevance = 1 - distance.
# Chunks below this threshold are dropped before sending context to the LLM.
# 0.0 = no filtering; 0.20 = conservative (drops clearly irrelevant chunks).
SEARCH_RELEVANCE_THRESHOLD = float(os.getenv('SEARCH_RELEVANCE_THRESHOLD', '0.20'))

# SHARE_LINK_TTL_DAYS: lifetime of a newly issued public share link, in days.
# A public link needs no authentication, so an unlimited one keeps a chat or a
# document readable by anyone who ever saw the URL.  0 = links never expire.
SHARE_LINK_TTL_DAYS = int(os.getenv('SHARE_LINK_TTL_DAYS', '30'))

# API key for external API access
API_KEY = os.getenv('API_KEY', 'your-secret-api-key-change-me')

# Authentication
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Email / SMTP
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'ROoP <noreply@example.com>')
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '30'))

# TLS / SSL -- always determined by port number.
# Port 465 = implicit SSL (EMAIL_USE_SSL=True).
# Port 587 = STARTTLS (EMAIL_USE_TLS=True).
# Port 25  = no encryption.
# These are MUTUALLY EXCLUSIVE in Django. We auto-detect to prevent misconfiguration.
# To override, set EMAIL_ENCRYPTION=ssl or EMAIL_ENCRYPTION=tls or EMAIL_ENCRYPTION=none.
_email_encryption = os.getenv('EMAIL_ENCRYPTION', '').lower()
if _email_encryption == 'ssl':
    EMAIL_USE_SSL = True
    EMAIL_USE_TLS = False
elif _email_encryption == 'tls':
    EMAIL_USE_SSL = False
    EMAIL_USE_TLS = True
elif _email_encryption == 'none':
    EMAIL_USE_SSL = False
    EMAIL_USE_TLS = False
else:
    # Auto-detect from port
    EMAIL_USE_SSL = EMAIL_PORT == 465
    EMAIL_USE_TLS = EMAIL_PORT == 587

# For development/testing without real SMTP, use console backend:
# EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# Create logs directory (may fail in Docker if volume is root-owned)
LOGS_DIR = BASE_DIR / 'logs'
try:
    LOGS_DIR.mkdir(exist_ok=True)
    _log_file_path = str(LOGS_DIR / 'rag_system.log')
    # Test write access
    with open(_log_file_path, 'a'):
        pass
    _file_handler_available = True
except (PermissionError, OSError):
    _file_handler_available = False

_log_handlers = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'verbose',
    },
}

if _file_handler_available:
    _log_handlers['file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': _log_file_path,
        'maxBytes': 10485760,  # 10MB
        'backupCount': 5,
        'formatter': 'verbose',
    }

_core_log_handlers = ['console', 'file'] if _file_handler_available else ['console']

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {module}: {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname}: {message}',
            'style': '{',
        },
    },
    'handlers': _log_handlers,
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'core': {
            'handlers': _core_log_handlers,
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}
