"""Shared test fixtures and configuration."""

from unittest.mock import MagicMock, patch

import pytest


def _create_mock_pipeline():
    """Create a mocked RAGPipeline instance."""
    mock_pipeline = MagicMock()
    mock_pipeline.check_ollama_status.return_value = {'status': 'ok', 'models': []}
    mock_pipeline.check_chroma_status.return_value = {'status': 'ok', 'documents_in_collection': 0}
    mock_pipeline.process_document.return_value = 5
    mock_pipeline.chat.return_value = {
        'answer': 'Mock answer',
        'sources': [],
        'question': 'Mock question',
    }
    mock_pipeline.delete_document_from_chroma.return_value = None
    mock_pipeline.search.return_value = []
    return mock_pipeline


@pytest.fixture(autouse=True)
def mock_rag_pipeline():
    """Mock RAGPipeline.get_instance for all tests to avoid ChromaDB/Ollama dependencies."""
    mock_pipeline = _create_mock_pipeline()
    with patch('core.rag_pipeline.RAGPipeline.get_instance', return_value=mock_pipeline):
        yield mock_pipeline
