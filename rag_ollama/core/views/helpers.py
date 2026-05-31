"""
Shared helpers for views.
"""

import os
import uuid

import magic
from django.conf import settings
from django.db.models import Q

# ---------------------------------------------------------------------------
# Allowed file types: extension → set of acceptable MIME types.
# DOCX is a ZIP archive internally, so application/zip is also accepted.
# DOC (legacy binary) may be detected as application/octet-stream on some
# systems that lack full magic byte databases.
# ---------------------------------------------------------------------------
_ALLOWED_TYPES: dict[str, set[str]] = {
    'pdf': {'application/pdf'},
    'txt': {'text/plain'},
    'md': {'text/plain', 'text/x-markdown', 'text/markdown'},
    'docx': {
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/zip',
    },
    'doc': {'application/msword', 'application/octet-stream'},
}

_ALLOWED_EXTENSIONS = frozenset(_ALLOWED_TYPES)


class FileValidationError(ValueError):
    """Raised when an uploaded file fails extension or MIME validation."""


def validate_and_save_upload(uploaded_file) -> tuple[str, str, str]:
    """
    Validate uploaded file (extension + MIME signature) and write it to disk.

    Returns:
        (file_path, ext, unique_name)  — absolute path, lower-cased extension,
        uuid-prefixed filename stored on disk.

    Raises:
        FileValidationError: when extension or MIME type is not allowed.
    """
    # --- Extension check ---
    name = uploaded_file.name or ''
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in _ALLOWED_EXTENSIONS:
        allowed = ', '.join(sorted(_ALLOWED_EXTENSIONS, key=str.upper))
        raise FileValidationError(f'Неподдерживаемый формат ".{ext}". Допустимые: {allowed.upper()}')

    # --- MIME check via magic bytes (first 4 KB, file pointer reset afterwards) ---
    header = uploaded_file.read(4096)
    uploaded_file.seek(0)
    detected_mime = magic.from_buffer(header, mime=True)

    allowed_mimes = _ALLOWED_TYPES[ext]
    if detected_mime not in allowed_mimes:
        raise FileValidationError(
            f'Содержимое файла не соответствует расширению ".{ext}" (обнаружен MIME: {detected_mime})'
        )

    # --- Save to disk ---
    unique_name = f'{uuid.uuid4().hex[:12]}_{name}'
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'documents')
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, unique_name)

    with open(file_path, 'wb+') as dest:
        for chunk in uploaded_file.chunks():
            dest.write(chunk)

    return file_path, ext, unique_name


def user_docs_q(user):
    """Q filter: documents owned by user OR marked as shared."""
    return Q(user=user) | Q(is_shared=True)


def format_size(size_bytes):
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f'{size_bytes:.1f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.1f} TB'
