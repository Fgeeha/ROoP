"""
Document text extraction and post-processing.

All functions are pure (no Django ORM, no class state).
extract_text() is the single public entry point; the _extract_* helpers
and _clean_extracted_text() are internal implementation details.
"""

import logging
import re

logger = logging.getLogger(__name__)


def extract_text(file_path: str, file_type: str) -> str:
    """Extract and clean text content from a file."""
    logger.info('Extracting text from: %s (type: %s)', file_path, file_type)

    if file_type == 'pdf':
        raw = _extract_pdf(file_path)
    elif file_type in ('txt', 'md'):
        raw = _extract_text_file(file_path)
    elif file_type == 'docx':
        raw = _extract_docx(file_path)
    elif file_type == 'doc':
        raw = _extract_doc(file_path)
    else:
        raise ValueError(f'Unsupported file type: {file_type}')

    cleaned = _clean_extracted_text(raw)
    logger.info('Text extracted and cleaned: %d -> %d chars', len(raw), len(cleaned))
    return cleaned


def _extract_pdf(file_path: str) -> str:
    """Extract text from PDF using pdfplumber (much better layout handling than PyPDF2)."""
    import pdfplumber

    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            page_text = page.extract_text(
                x_tolerance=2,  # merge chars closer than 2pt (fixes broken words)
                y_tolerance=3,  # merge lines closer than 3pt
            )
            if page_text:
                text_parts.append(page_text)
                logger.debug('Extracted page %d: %d chars', page_num + 1, len(page_text))

        full_text = '\n\n'.join(text_parts)
        logger.info('PDF extraction complete: %d chars from %d pages', len(full_text), len(pdf.pages))
    return full_text


def _extract_text_file(file_path: str) -> str:
    """Extract text from TXT/MD file with encoding detection."""
    import chardet

    with open(file_path, 'rb') as f:
        raw_data = f.read()

    detected = chardet.detect(raw_data)
    encoding = detected.get('encoding', 'utf-8') or 'utf-8'
    logger.debug('Detected encoding: %s (confidence: %.2f)', encoding, detected.get('confidence', 0))

    try:
        text = raw_data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        text = raw_data.decode('utf-8', errors='replace')

    return text


def _extract_docx(file_path: str) -> str:
    """Extract text from DOCX file using python-docx."""
    import docx

    doc = docx.Document(file_path)
    text_parts = []

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            text_parts.append(text)

    for table in doc.tables:
        for row in table.rows:
            row_text = '\t'.join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                text_parts.append(row_text)

    full_text = '\n\n'.join(text_parts)
    logger.info('DOCX extraction complete: %d chars', len(full_text))
    return full_text


def _extract_doc(file_path: str) -> str:
    """
    Extract text from legacy DOC file.
    Uses antiword (system utility) as primary method.
    Falls back to python-docx in case the file is actually DOCX with .doc extension.
    """
    import subprocess

    try:
        result = subprocess.run(  # noqa: S603
            ['/usr/bin/antiword', '-w', '0', file_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            logger.info('DOC extraction via antiword complete: %d chars', len(result.stdout))
            return result.stdout
        logger.warning('antiword returned code %d: %s', result.returncode, result.stderr.strip())
    except FileNotFoundError:
        logger.warning('antiword not installed, falling back to python-docx')
    except subprocess.TimeoutExpired:
        logger.warning('antiword timed out, falling back to python-docx')

    try:
        return _extract_docx(file_path)
    except Exception as e:
        raise ValueError(
            'Не удалось извлечь текст из DOC файла. '
            'Убедитесь, что antiword установлен (apt-get install antiword) '
            'или конвертируйте файл в DOCX формат.'
        ) from e


def _clean_extracted_text(text: str) -> str:
    """
    Post-process extracted text:
    - Remove repeated page headers/footers (address blocks, page numbers)
    - Fix broken words (letters separated by spaces within a word)
    - Normalize whitespace
    """
    lines = text.split('\n')

    # 1. Detect and remove repeated header/footer lines.
    page_blocks = text.split('\n\n')
    if len(page_blocks) >= 3:
        line_counts: dict[str, int] = {}
        for block in page_blocks:
            seen_in_block: set[str] = set()
            for line in block.split('\n'):
                stripped = line.strip()
                if stripped and stripped not in seen_in_block:
                    seen_in_block.add(stripped)
                    line_counts[stripped] = line_counts.get(stripped, 0) + 1

        # Lines that appear in >= 40% of page blocks are headers/footers
        threshold = max(3, len(page_blocks) * 0.4)
        header_footer_lines = {line for line, count in line_counts.items() if count >= threshold and len(line) < 200}

        if header_footer_lines:
            logger.info('Removing %d repeated header/footer patterns', len(header_footer_lines))
            lines = [line for line in lines if line.strip() not in header_footer_lines]

    # 2. Remove standalone page numbers (lines that are just a number)
    lines = [line for line in lines if not re.match(r'^\s*\d{1,4}\s*$', line)]

    # 3. Join lines
    text = '\n'.join(lines)

    # 4. Fix clearly broken words: only merge single isolated letter fragments.
    #    Single Cyrillic letters between spaces are almost never real words
    #    except prepositions (в, и, с, к, о, а, у).
    _prepositions = set('вискоау')

    def _merge_fragment(m):
        frag = m.group(2)
        if frag.lower() in _prepositions:
            return m.group(0)
        return m.group(1) + frag + ' '

    text = re.sub(r'([а-яА-ЯёЁ]{2,}) ([а-яёЁА-ЯЁ]) ', _merge_fragment, text)

    # 5. Normalize excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    return text.strip()
