"""Tests for validate_and_save_upload helper."""

import io
import os
from unittest.mock import patch

import pytest

from core.views.helpers import FileValidationError, validate_and_save_upload  # noqa: E402

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
            with pytest.raises(FileValidationError, match='exe'):
                validate_and_save_upload(f)

    def test_no_extension_raises(self, tmp_path):
        f = _make_file('noextension', TXT_CONTENT)
        with (
            patch('core.views.helpers.magic.from_buffer', return_value='text/plain'),
            patch('core.views.helpers.settings') as mock_settings,
        ):
            mock_settings.MEDIA_ROOT = str(tmp_path)
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
