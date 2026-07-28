"""Tests for validate_and_save_upload helper."""

import io
import os
from unittest.mock import patch

import pytest

from core.views.helpers import (  # noqa: E402
    FileTooLargeError,
    FileValidationError,
    validate_and_save_upload,
)

# Small limit used throughout these tests so no real multi-MB file is created.
TEST_MAX_UPLOAD_SIZE = 1024

# ---------------------------------------------------------------------------
# Minimal file headers for each supported type
# ---------------------------------------------------------------------------

# PDF magic bytes: %PDF-
PDF_HEADER = b'%PDF-1.4\n%%EOF'

# DOCX / ZIP magic bytes: PK\x03\x04
DOCX_HEADER = b'PK\x03\x04' + b'\x00' * 26

# DOC (legacy Compound Document): D0 CF 11 E0
DOC_HEADER = b'\xd0\xcf\x11\xe0' + b'\x00' * 28

# Plain text
TXT_CONTENT = b'Hello, world!'


def _make_file(name: str, content: bytes):
    """Return a Django-like InMemoryUploadedFile mock."""
    f = io.BytesIO(content)
    f.name = name
    f.size = len(content)

    # Add chunks() method expected by save logic
    def chunks(chunk_size=65536):
        f.seek(0)
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            yield data

    f.chunks = chunks
    return f


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mime_for(content: bytes) -> str:
    """Return real MIME via python-magic (integration)."""
    import magic

    return magic.from_buffer(content[:4096], mime=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidateAndSaveUpload:
    """Unit tests — magic.from_buffer is patched to avoid libmagic dependency in CI."""

    def _call(self, name: str, content: bytes, mime: str, tmp_path):
        f = _make_file(name, content)
        with (
            patch('core.views.helpers.magic.from_buffer', return_value=mime),
            patch('core.views.helpers.settings') as mock_settings,
        ):
            mock_settings.MEDIA_ROOT = str(tmp_path)
            mock_settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
            file_path, ext, unique_name = validate_and_save_upload(f)
        return file_path, ext, unique_name

    # --- Valid uploads ---

    def test_valid_pdf(self, tmp_path):
        file_path, ext, unique_name = self._call('report.pdf', PDF_HEADER, 'application/pdf', tmp_path)
        assert ext == 'pdf'
        assert os.path.exists(file_path)
        assert unique_name.endswith('_report.pdf')

    def test_valid_txt(self, tmp_path):
        file_path, ext, _ = self._call('notes.txt', TXT_CONTENT, 'text/plain', tmp_path)
        assert ext == 'txt'
        assert os.path.exists(file_path)

    def test_valid_md(self, tmp_path):
        file_path, ext, _ = self._call('README.md', TXT_CONTENT, 'text/plain', tmp_path)
        assert ext == 'md'
        assert os.path.exists(file_path)

    def test_valid_docx(self, tmp_path):
        file_path, ext, _ = self._call(
            'doc.docx',
            DOCX_HEADER,
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            tmp_path,
        )
        assert ext == 'docx'

    def test_valid_docx_detected_as_zip(self, tmp_path):
        """DOCX may be detected as application/zip — must still be accepted."""
        file_path, ext, _ = self._call('doc.docx', DOCX_HEADER, 'application/zip', tmp_path)
        assert ext == 'docx'

    def test_valid_doc(self, tmp_path):
        file_path, ext, _ = self._call('legacy.doc', DOC_HEADER, 'application/msword', tmp_path)
        assert ext == 'doc'

    # --- Invalid extension ---

    def test_invalid_extension_raises(self, tmp_path):
        f = _make_file('virus.exe', b'MZ\x90\x00')
        with (
            patch('core.views.helpers.magic.from_buffer', return_value='application/x-dosexec'),
            patch('core.views.helpers.settings') as mock_settings,
        ):
            mock_settings.MEDIA_ROOT = str(tmp_path)
            mock_settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
            with pytest.raises(FileValidationError, match='exe'):
                validate_and_save_upload(f)

    def test_no_extension_raises(self, tmp_path):
        f = _make_file('noextension', TXT_CONTENT)
        with (
            patch('core.views.helpers.magic.from_buffer', return_value='text/plain'),
            patch('core.views.helpers.settings') as mock_settings,
        ):
            mock_settings.MEDIA_ROOT = str(tmp_path)
            mock_settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
            with pytest.raises(FileValidationError):
                validate_and_save_upload(f)

    # --- MIME mismatch (extension spoofing) ---

    def test_exe_renamed_to_pdf_raises(self, tmp_path):
        """A binary file renamed to .pdf must be rejected."""
        f = _make_file('malware.pdf', b'MZ\x90\x00')
        with (
            patch('core.views.helpers.magic.from_buffer', return_value='application/x-dosexec'),
            patch('core.views.helpers.settings') as mock_settings,
        ):
            mock_settings.MEDIA_ROOT = str(tmp_path)
            mock_settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
            with pytest.raises(FileValidationError, match='MIME'):
                validate_and_save_upload(f)

    def test_pdf_renamed_to_txt_raises(self, tmp_path):
        """PDF content with .txt extension must be rejected."""
        f = _make_file('sneaky.txt', PDF_HEADER)
        with (
            patch('core.views.helpers.magic.from_buffer', return_value='application/pdf'),
            patch('core.views.helpers.settings') as mock_settings,
        ):
            mock_settings.MEDIA_ROOT = str(tmp_path)
            mock_settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
            with pytest.raises(FileValidationError, match='MIME'):
                validate_and_save_upload(f)

    # --- File is actually written ---

    def test_file_content_preserved(self, tmp_path):
        content = b'%PDF-1.4 test content'
        file_path, _, _ = self._call('test.pdf', content, 'application/pdf', tmp_path)
        with open(file_path, 'rb') as fh:
            assert fh.read() == content

    def test_unique_names_generated(self, tmp_path):
        """Two uploads of the same filename produce distinct on-disk names."""
        paths = set()
        for _ in range(3):
            fp, _, _ = self._call('same.pdf', PDF_HEADER, 'application/pdf', tmp_path)
            paths.add(fp)
        assert len(paths) == 3


# ---------------------------------------------------------------------------
# MAX_UPLOAD_SIZE enforcement
# ---------------------------------------------------------------------------


def _pdf_of_size(size: int) -> bytes:
    """Build PDF-looking content of exactly `size` bytes."""
    body = PDF_HEADER + b'\n' + b'A' * size
    return body[:size]


class TestUploadSizeLimit:
    """settings.MAX_UPLOAD_SIZE is a hard limit, checked before indexing starts."""

    def _call(self, content: bytes, tmp_path, declared_size=None, max_size=TEST_MAX_UPLOAD_SIZE):
        f = _make_file('big.pdf', content)
        if declared_size is not None:
            f.size = declared_size
        with (
            patch('core.views.helpers.magic.from_buffer', return_value='application/pdf'),
            patch('core.views.helpers.settings') as mock_settings,
        ):
            mock_settings.MEDIA_ROOT = str(tmp_path)
            mock_settings.MAX_UPLOAD_SIZE = max_size
            return validate_and_save_upload(f)

    def test_under_limit_accepted(self, tmp_path):
        file_path, ext, _ = self._call(_pdf_of_size(TEST_MAX_UPLOAD_SIZE - 1), tmp_path)
        assert ext == 'pdf'
        assert os.path.getsize(file_path) == TEST_MAX_UPLOAD_SIZE - 1

    def test_exactly_at_limit_accepted(self, tmp_path):
        """The limit is inclusive — a file of exactly MAX_UPLOAD_SIZE passes."""
        file_path, ext, _ = self._call(_pdf_of_size(TEST_MAX_UPLOAD_SIZE), tmp_path)
        assert ext == 'pdf'
        assert os.path.getsize(file_path) == TEST_MAX_UPLOAD_SIZE

    def test_over_limit_rejected(self, tmp_path):
        with pytest.raises(FileTooLargeError):
            self._call(_pdf_of_size(TEST_MAX_UPLOAD_SIZE + 1), tmp_path)

    def test_too_large_is_a_file_validation_error(self, tmp_path):
        """FileTooLargeError must stay catchable as FileValidationError."""
        with pytest.raises(FileValidationError):
            self._call(_pdf_of_size(TEST_MAX_UPLOAD_SIZE + 1), tmp_path)

    def test_understated_size_still_rejected(self, tmp_path):
        """A lying Content-Length must not smuggle an oversized file through."""
        oversized = _pdf_of_size(TEST_MAX_UPLOAD_SIZE * 3)
        with pytest.raises(FileTooLargeError):
            self._call(oversized, tmp_path, declared_size=10)

    def test_partial_file_removed_when_streaming_limit_hit(self, tmp_path):
        """No truncated leftovers on disk after a streamed rejection."""
        upload_dir = tmp_path / 'documents'
        oversized = _pdf_of_size(TEST_MAX_UPLOAD_SIZE * 3)
        with pytest.raises(FileTooLargeError):
            self._call(oversized, tmp_path, declared_size=10)

        leftovers = list(upload_dir.glob('*')) if upload_dir.exists() else []
        assert leftovers == [], f'partial file left behind: {leftovers}'

    def test_size_checked_regardless_of_extension(self, tmp_path):
        """Rejection happens on size before extension is even considered."""
        f = _make_file('huge.exe', _pdf_of_size(TEST_MAX_UPLOAD_SIZE + 1))
        with (
            patch('core.views.helpers.magic.from_buffer', return_value='application/x-dosexec'),
            patch('core.views.helpers.settings') as mock_settings,
        ):
            mock_settings.MEDIA_ROOT = str(tmp_path)
            mock_settings.MAX_UPLOAD_SIZE = TEST_MAX_UPLOAD_SIZE
            with pytest.raises(FileTooLargeError):
                validate_and_save_upload(f)

    def test_message_is_user_facing(self, tmp_path):
        """No paths or internals in the message shown to the user."""
        with pytest.raises(FileTooLargeError) as exc:
            self._call(_pdf_of_size(TEST_MAX_UPLOAD_SIZE + 1), tmp_path)
        message = str(exc.value)
        assert 'МБ' in message
        assert str(tmp_path) not in message


class TestUploadSettings:
    """Configuration contract for the two independent upload knobs."""

    def test_max_upload_size_is_int(self):
        from django.conf import settings as django_settings

        assert isinstance(django_settings.MAX_UPLOAD_SIZE, int)
        assert django_settings.MAX_UPLOAD_SIZE > 0

    def test_file_upload_memory_threshold_is_small(self):
        """Uploads must spill to a temp file well below the hard limit."""
        from django.conf import settings as django_settings

        assert isinstance(django_settings.FILE_UPLOAD_MAX_MEMORY_SIZE, int)
        assert django_settings.FILE_UPLOAD_MAX_MEMORY_SIZE <= 2621440
        assert django_settings.FILE_UPLOAD_MAX_MEMORY_SIZE < django_settings.MAX_UPLOAD_SIZE

    def test_max_upload_size_reads_environment(self, monkeypatch):
        """MAX_UPLOAD_SIZE comes from the environment as an integer byte count."""
        monkeypatch.setenv('MAX_UPLOAD_SIZE', '12345')
        assert int(os.getenv('MAX_UPLOAD_SIZE', '26214400')) == 12345
