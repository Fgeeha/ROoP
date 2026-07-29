"""
Tests for Sprint 3: configurable SEARCH_K, relevance threshold, empty-result edge case.

ChromaDB with hnsw:space=cosine returns cosine DISTANCE, not similarity:
  - distance = 1 - cosine_similarity  →  range [0, 1] (0 = identical)
  - relevance = 1 - distance = cosine_similarity  →  higher is better
  - threshold filters: keep chunks where relevance >= threshold

All external I/O is mocked — no ChromaDB, Ollama, or PostgreSQL required.
"""

from unittest.mock import MagicMock

from django.test import override_settings

from core.rag_pipeline import RAGPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline() -> RAGPipeline:
    """Directly instantiate RAGPipeline with mocked internals (bypasses _initialize)."""
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline._chroma_client = MagicMock()
    pipeline._collection = MagicMock()
    pipeline._llm_backend = MagicMock()
    return pipeline


def _chroma_result(docs: list[str], distances: list[float]) -> dict:
    """Build a ChromaDB-shaped query() return value."""
    metadatas = [
        {
            'document_id': str(i),
            'filename': f'doc{i}.txt',
            'chunk_index': i,
            'char_count': 200,
            'user_id': '',
            'is_shared': 'false',
        }
        for i in range(len(docs))
    ]
    return {
        'documents': [docs],
        'metadatas': [metadatas],
        'distances': [distances],
    }


# ---------------------------------------------------------------------------
# SEARCH_K from settings
# ---------------------------------------------------------------------------


class TestSearchKFromSettings:
    """SEARCH_K must be read from Django settings, not hardcoded."""

    def test_default_search_k_passed_as_n_results(self):
        """search() uses settings.SEARCH_K as n_results when no explicit k given."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 100
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        pipeline._collection.query.return_value = _chroma_result([], [])

        with override_settings(SEARCH_K=7, SEARCH_RELEVANCE_THRESHOLD=0.0):
            pipeline.search('test query')

        called_kwargs = pipeline._collection.query.call_args.kwargs
        assert called_kwargs['n_results'] == 7

    def test_explicit_k_overrides_settings(self):
        """Explicit k= parameter overrides settings.SEARCH_K."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 100
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        pipeline._collection.query.return_value = _chroma_result([], [])

        with override_settings(SEARCH_K=8, SEARCH_RELEVANCE_THRESHOLD=0.0):
            pipeline.search('test query', k=3)

        called_kwargs = pipeline._collection.query.call_args.kwargs
        assert called_kwargs['n_results'] == 3

    def test_n_results_capped_by_collection_size(self):
        """n_results is capped at collection.count() to avoid ChromaDB errors."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 2
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        pipeline._collection.query.return_value = _chroma_result([], [])

        with override_settings(SEARCH_K=10, SEARCH_RELEVANCE_THRESHOLD=0.0):
            pipeline.search('test query')

        called_kwargs = pipeline._collection.query.call_args.kwargs
        assert called_kwargs['n_results'] == 2


# ---------------------------------------------------------------------------
# Distance → relevance conversion
# ---------------------------------------------------------------------------


class TestRelevanceConversion:
    """ChromaDB cosine DISTANCE must be converted to similarity: relevance = 1 - distance."""

    def test_relevance_equals_one_minus_distance(self):
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 10
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        pipeline._collection.query.return_value = _chroma_result(['chunk A', 'chunk B'], [0.3, 0.7])

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.0):
            results = pipeline.search('query')

        assert len(results) == 2
        assert results[0]['relevance'] == round(1 - 0.3, 4)  # 0.7
        assert results[1]['relevance'] == round(1 - 0.7, 4)  # 0.3

    def test_distance_zero_gives_relevance_one(self):
        """Perfect match: distance=0 → relevance=1.0."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 5
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        pipeline._collection.query.return_value = _chroma_result(['exact'], [0.0])

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.0):
            results = pipeline.search('query')

        assert results[0]['relevance'] == 1.0

    def test_distance_one_gives_relevance_zero(self):
        """Orthogonal vectors: distance=1.0 → relevance=0.0."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 5
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        pipeline._collection.query.return_value = _chroma_result(['unrelated'], [1.0])

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.0):
            results = pipeline.search('query')

        assert results[0]['relevance'] == 0.0


# ---------------------------------------------------------------------------
# Relevance threshold filtering
# ---------------------------------------------------------------------------


class TestRelevanceThreshold:
    """Chunks with relevance < threshold must be dropped; relevance >= threshold kept."""

    def test_threshold_drops_low_relevance_chunk(self):
        """Chunk with relevance 0.15 is dropped when threshold=0.20."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 10
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        # distance=0.1 → relevance=0.90 (keep); distance=0.85 → relevance=0.15 (drop)
        pipeline._collection.query.return_value = _chroma_result(['relevant', 'noise'], [0.1, 0.85])

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.20):
            results = pipeline.search('query')

        assert len(results) == 1
        assert results[0]['content'] == 'relevant'

    def test_threshold_keeps_chunk_at_boundary(self):
        """Chunk exactly at threshold is kept (>= is inclusive)."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 10
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        # distance=0.80 → relevance=0.20 exactly at threshold=0.20 → keep
        pipeline._collection.query.return_value = _chroma_result(['boundary'], [0.80])

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.20):
            results = pipeline.search('query')

        assert len(results) == 1
        assert results[0]['relevance'] == 0.20

    def test_threshold_direction_low_distance_passes(self):
        """LOW distance (near-identical vectors) must PASS the threshold, not be dropped.

        A common implementation bug is filtering distance <= threshold instead of
        relevance >= threshold.  That would invert the logic: near-identical chunks
        (distance ≈ 0) would be dropped and irrelevant ones (distance ≈ 1) kept.
        """
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 10
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        # distance=0.05 → relevance=0.95 (very relevant, must PASS)
        # distance=0.90 → relevance=0.10 (very irrelevant, must be DROPPED)
        pipeline._collection.query.return_value = _chroma_result(['very relevant', 'very irrelevant'], [0.05, 0.90])

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.20):
            results = pipeline.search('query')

        contents = [r['content'] for r in results]
        assert 'very relevant' in contents
        assert 'very irrelevant' not in contents

    def test_threshold_zero_disables_filtering(self):
        """SEARCH_RELEVANCE_THRESHOLD=0.0 keeps all results regardless of distance."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 10
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        pipeline._collection.query.return_value = _chroma_result(['a', 'b', 'c'], [0.1, 0.5, 0.99])

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.0):
            results = pipeline.search('query')

        assert len(results) == 3

    def test_all_above_threshold_all_kept(self):
        """When all chunks are above threshold, none are dropped."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 10
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        # All distances <= 0.5 → relevance >= 0.5 → all pass threshold=0.20
        pipeline._collection.query.return_value = _chroma_result(['a', 'b', 'c'], [0.1, 0.3, 0.5])

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.20):
            results = pipeline.search('query')

        assert len(results) == 3


# ---------------------------------------------------------------------------
# Empty-result edge case
# ---------------------------------------------------------------------------


class TestEmptyResultEdgeCase:
    """After threshold filtering, empty list must be returned cleanly (no exception)."""

    def test_all_chunks_filtered_returns_empty_list(self):
        """If every chunk is below threshold, return [] without raising."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 5
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        # All distances > 0.8 → relevance < 0.2 → all dropped
        pipeline._collection.query.return_value = _chroma_result(['chunk1', 'chunk2'], [0.9, 0.95])

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.20):
            results = pipeline.search('completely unrelated query')

        assert results == []

    def test_empty_collection_returns_empty_list(self):
        """Empty ChromaDB collection returns [] without querying."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 0

        with override_settings(SEARCH_K=6, SEARCH_RELEVANCE_THRESHOLD=0.20):
            results = pipeline.search('any query')

        pipeline._collection.query.assert_not_called()
        assert results == []


# ---------------------------------------------------------------------------
# chat() edge cases: threshold vs no documents
# ---------------------------------------------------------------------------


class TestChatEdgeCases:
    """chat() must distinguish between empty collection and threshold-filtered results."""

    def test_chat_threshold_filtered_no_llm_call(self):
        """When docs exist but threshold filtered all → static message, LLM not called."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 10
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        # All chunks below threshold
        pipeline._collection.query.return_value = _chroma_result(['irrelevant chunk'], [0.95])

        with override_settings(
            SEARCH_K=6,
            SEARCH_RELEVANCE_THRESHOLD=0.20,
            LLM_MODEL='mistral',
            LLM_BACKEND='ollama',
        ):
            result = pipeline.chat('specialized question')

        pipeline._llm_backend.chat.assert_not_called()
        assert result['sources'] == []
        assert 'Релевантного контекста не найдено' in result['answer']

    def test_chat_empty_collection_calls_llm(self):
        """When collection is empty → LLM is called to generate 'upload docs' response."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 0
        pipeline._llm_backend.chat.return_value = 'Загрузите документы'

        with override_settings(
            SEARCH_K=6,
            SEARCH_RELEVANCE_THRESHOLD=0.20,
            LLM_MODEL='mistral',
            LLM_BACKEND='ollama',
        ):
            result = pipeline.chat('some question')

        pipeline._llm_backend.chat.assert_called_once()
        assert result['sources'] == []

    def test_chat_threshold_answer_mentions_threshold_value(self):
        """The 'no context' message must include the actual threshold value."""
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = 5
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        pipeline._collection.query.return_value = _chroma_result(['noise'], [0.99])

        with override_settings(
            SEARCH_K=6,
            SEARCH_RELEVANCE_THRESHOLD=0.35,
            LLM_MODEL='mistral',
            LLM_BACKEND='ollama',
        ):
            result = pipeline.chat('question')

        assert '0.35' in result['answer']


# ---------------------------------------------------------------------------
# Context budget (MAX_CONTEXT_CHARS)
# ---------------------------------------------------------------------------


class TestContextBudget:
    """Retrieved chunks must fit MAX_CONTEXT_CHARS before reaching the LLM.

    Ollama silently truncates a prompt longer than num_ctx, so an unbounded
    context produces an answer built from part of the evidence with nothing to
    indicate the rest was cut.
    """

    @staticmethod
    def _pipeline_with(chunks: list[str]) -> RAGPipeline:
        pipeline = _make_pipeline()
        pipeline._collection.count.return_value = len(chunks)
        pipeline._llm_backend.embed.return_value = [[0.1] * 768]
        pipeline._llm_backend.chat.return_value = 'ответ'
        # Ascending distance = descending relevance, matching ChromaDB's order.
        distances = [0.1 + 0.05 * i for i in range(len(chunks))]
        pipeline._collection.query.return_value = _chroma_result(chunks, distances)
        return pipeline

    @staticmethod
    def _prompt_of(pipeline) -> str:
        return pipeline._llm_backend.chat.call_args.kwargs['prompt']

    def test_all_chunks_used_when_within_budget(self):
        chunks = ['a' * 100, 'b' * 100, 'c' * 100]
        pipeline = self._pipeline_with(chunks)

        with override_settings(
            SEARCH_K=6,
            SEARCH_RELEVANCE_THRESHOLD=0.0,
            MAX_CONTEXT_CHARS=10000,
            LLM_MODEL='gemma3:4b',
            LLM_BACKEND='ollama',
        ):
            result = pipeline.chat('вопрос')

        assert len(result['sources']) == 3
        assert result['context_truncated'] is False
        prompt = self._prompt_of(pipeline)
        for chunk in chunks:
            assert chunk in prompt

    def test_least_relevant_chunks_dropped_when_over_budget(self):
        chunks = ['a' * 400, 'b' * 400, 'c' * 400, 'd' * 400]
        pipeline = self._pipeline_with(chunks)

        # Fits two chunks plus one separator, not three.
        with override_settings(
            SEARCH_K=6,
            SEARCH_RELEVANCE_THRESHOLD=0.0,
            MAX_CONTEXT_CHARS=900,
            LLM_MODEL='gemma3:4b',
            LLM_BACKEND='ollama',
        ):
            result = pipeline.chat('вопрос')

        assert result['context_truncated'] is True
        assert len(result['sources']) == 2
        prompt = self._prompt_of(pipeline)
        assert 'a' * 400 in prompt
        assert 'b' * 400 in prompt
        assert 'c' * 400 not in prompt
        assert 'd' * 400 not in prompt

    def test_sources_list_only_the_chunks_actually_used(self):
        """A source the answer was not built from must not be shown as one."""
        chunks = ['a' * 400, 'b' * 400, 'c' * 400]
        pipeline = self._pipeline_with(chunks)

        with override_settings(
            SEARCH_K=6,
            SEARCH_RELEVANCE_THRESHOLD=0.0,
            MAX_CONTEXT_CHARS=450,
            LLM_MODEL='gemma3:4b',
            LLM_BACKEND='ollama',
        ):
            result = pipeline.chat('вопрос')

        assert [s['chunk_index'] for s in result['sources']] == [0]

    def test_first_chunk_kept_even_when_alone_over_budget(self):
        """Answering from no context at all would be worse than one long chunk."""
        pipeline = self._pipeline_with(['a' * 5000])

        with override_settings(
            SEARCH_K=6,
            SEARCH_RELEVANCE_THRESHOLD=0.0,
            MAX_CONTEXT_CHARS=100,
            LLM_MODEL='gemma3:4b',
            LLM_BACKEND='ollama',
        ):
            result = pipeline.chat('вопрос')

        assert len(result['sources']) == 1
        assert result['context_truncated'] is False
        assert 'a' * 5000 in self._prompt_of(pipeline)

    def test_raising_search_k_does_not_grow_context_without_bound(self):
        """The regression: SEARCH_K used to size the prompt directly."""
        chunks = ['x' * 1000] * 20
        pipeline = self._pipeline_with(chunks)

        with override_settings(
            SEARCH_K=20,
            SEARCH_RELEVANCE_THRESHOLD=0.0,
            MAX_CONTEXT_CHARS=7040,
            LLM_MODEL='gemma3:4b',
            LLM_BACKEND='ollama',
        ):
            result = pipeline.chat('вопрос')

        assert result['context_truncated'] is True
        # 6 x 1000 chars + 5 separators = 6035; a seventh would overflow 7040.
        assert len(result['sources']) == 6
        # Context, excluding the fixed instruction block, stays inside budget.
        context_chars = sum(len(c) for c in chunks[: len(result['sources'])])
        context_chars += len('\n\n---\n\n') * (len(result['sources']) - 1)
        assert context_chars <= 7040
