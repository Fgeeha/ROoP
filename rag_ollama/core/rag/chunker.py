"""
Text chunking for RAG ingestion.

Hierarchical strategy:
  1. Split by section headings.
  2. If a section fits within chunk_size — keep as one chunk.
  3. If too long — split by paragraphs with overlap.
  4. If a paragraph is still too long — split by sentence boundaries with overlap.

All functions are pure (no Django ORM, no class state).
chunk_text() reads CHUNK_SIZE / CHUNK_OVERLAP from Django settings at call time.
"""

import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)

# Heading patterns for Russian technical documents.
# Examples: "Социальная защита", "Модуль интеграции", "Расписание"
HEADING_RE = re.compile(r'^(?:' r'(?:Модуль|Раздел|Глава|Часть|Блок)\s+.+' r'|[А-ЯЁ][а-яёА-ЯЁ\s\-]{2,60}' r')$')


def chunk_text(text: str) -> list[str]:
    """
    Split text into chunks respecting section boundaries.

    Reads settings.CHUNK_SIZE and settings.CHUNK_OVERLAP.
    """
    chunk_size = settings.CHUNK_SIZE
    chunk_overlap = settings.CHUNK_OVERLAP

    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    sections = _split_by_headings(text)

    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= chunk_size:
            chunks.append(section)
        else:
            chunks.extend(_split_by_paragraphs(section, chunk_size, chunk_overlap))

    chunks = [c for c in chunks if len(c.strip()) > 50]

    logger.info('Text chunked: %d chars -> %d chunks', len(text), len(chunks))
    return chunks


def _split_by_headings(text: str) -> list[str]:
    """
    Split text into sections at heading boundaries.
    A heading is a short line (<= 80 chars) that either matches HEADING_RE
    or is followed by a numbered list ("1. ...").
    """
    lines = text.split('\n')
    sections: list[str] = []
    current_lines: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        is_heading = False

        if stripped and len(stripped) <= 80:
            if HEADING_RE.match(stripped):
                is_heading = True
            elif not stripped[0].isdigit():
                for j in range(i + 1, min(i + 3, len(lines))):
                    next_stripped = lines[j].strip()
                    if next_stripped:
                        if re.match(r'^1[\.\)]\s', next_stripped):
                            is_heading = True
                        break

        if is_heading and current_lines:
            section_text = '\n'.join(current_lines).strip()
            if section_text:
                sections.append(section_text)
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        section_text = '\n'.join(current_lines).strip()
        if section_text:
            sections.append(section_text)

    logger.debug('Split into %d sections by headings', len(sections))
    return sections


def _split_by_paragraphs(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split a section into chunks by paragraph boundaries with overlap."""
    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = ''

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(current_chunk) + len(paragraph) + 2 <= chunk_size:
            current_chunk = current_chunk + '\n\n' + paragraph if current_chunk else paragraph
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            if len(paragraph) > chunk_size:
                chunks.extend(_split_long_text(paragraph, chunk_size, chunk_overlap))
                current_chunk = ''
            else:
                if chunks:
                    overlap_text = chunks[-1][-chunk_overlap:]
                    current_chunk = overlap_text + '\n\n' + paragraph
                else:
                    current_chunk = paragraph

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split a long text block by sentence boundaries with overlap."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            search_start = max(end - 100, start)
            last_period = max(
                text.rfind('. ', search_start, end),
                text.rfind('! ', search_start, end),
                text.rfind('? ', search_start, end),
                text.rfind('\n', search_start, end),
            )
            if last_period > start:
                end = last_period + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap if end < len(text) else len(text)

    return chunks
