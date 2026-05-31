"""
LLM backend abstraction for the RAG system.

Supports two backends:
  - OllamaBackend:    direct connection to Ollama API
  - OpenWebUIBackend: connection via Open WebUI OpenAI-compatible API (Bearer token auth)

Use create_llm_backend() to instantiate the correct backend from Django settings.
"""

import logging

import httpx
import ollama
from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaBackend:
    """Direct Ollama API client."""

    def __init__(self, url: str):
        self.url = url
        self._client = ollama.Client(host=url)
        logger.info('Ollama backend initialized: %s', url)

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        response = self._client.embed(model=model, input=texts)
        return response['embeddings']

    def chat(self, model: str, prompt: str) -> str:
        response = self._client.chat(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.3, 'top_p': 0.9, 'num_predict': 2048},
        )
        return response['message']['content']

    def check_status(self) -> dict:
        try:
            models = self._client.list()
            model_names = [m.get('name', m.get('model', 'unknown')) for m in models.get('models', [])]
            return {'status': 'online', 'backend': 'ollama', 'models': model_names, 'url': self.url}
        except Exception as e:
            return {'status': 'offline', 'backend': 'ollama', 'error': str(e), 'url': self.url}


class OpenWebUIBackend:
    """
    Open WebUI API client.
    Uses Bearer token for authentication.
    Endpoints:
      - POST {base}/api/chat/completions       (chat, OpenAI-compatible)
      - POST {base}/ollama/api/embed           (embeddings, Ollama proxy)
      - GET  {base}/api/models                 (list models)

    Note: Open WebUI's /api/v1/embeddings has known bugs with batch input
    (returns 500 / NoneType errors). Instead, we use the Ollama API proxy
    at /ollama/api/embed which reliably supports batch embeddings.
    See: https://docs.openwebui.com/getting-started/api-endpoints/
    """

    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self._http = httpx.Client(
            base_url=self.url,
            headers=self._build_headers(),
            timeout=httpx.Timeout(300.0, connect=10.0),
        )
        logger.info('Open WebUI backend initialized: %s (key: %s)', url, 'set' if api_key else 'NOT SET')

    def _build_headers(self) -> dict:
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """
        Generate embeddings via Open WebUI Ollama proxy endpoint.
        Uses /ollama/api/embed (native Ollama format) which is more reliable
        than /api/v1/embeddings for batch requests.
        """
        try:
            response = self._http.post(
                '/ollama/api/embed',
                json={'model': model, 'input': texts},
            )
            response.raise_for_status()
            data = response.json()
            return data['embeddings']
        except (httpx.HTTPStatusError, KeyError) as primary_err:
            logger.warning('Ollama proxy embed failed (%s), falling back to /api/v1/embeddings one-by-one', primary_err)
            return self._embed_one_by_one(texts, model)

    def _embed_one_by_one(self, texts: list[str], model: str) -> list[list[float]]:
        """Fallback: send embedding requests one at a time via OpenAI-compatible endpoint."""
        embeddings = []
        for text in texts:
            response = self._http.post(
                '/api/v1/embeddings',
                json={'model': model, 'input': text},
            )
            response.raise_for_status()
            data = response.json()
            embeddings.append(data['data'][0]['embedding'])
        return embeddings

    def chat(self, model: str, prompt: str) -> str:
        """Generate chat response via Open WebUI OpenAI-compatible endpoint."""
        response = self._http.post(
            '/api/chat/completions',
            json={
                'model': model,
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.3,
                'top_p': 0.9,
                'max_tokens': 2048,
                'stream': False,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content']

    def check_status(self) -> dict:
        """Check Open WebUI availability and list models."""
        try:
            response = self._http.get('/api/models')
            response.raise_for_status()
            data = response.json()
            model_names = [m.get('id', m.get('name', 'unknown')) for m in data.get('data', data.get('models', []))]
            return {
                'status': 'online',
                'backend': 'openwebui',
                'models': model_names,
                'url': self.url,
                'auth': 'api_key' if self.api_key else 'none',
            }
        except httpx.HTTPStatusError as e:
            status = 'auth_error' if e.response.status_code in (401, 403) else 'error'
            return {
                'status': status,
                'backend': 'openwebui',
                'error': f'HTTP {e.response.status_code}: {e.response.text[:200]}',
                'url': self.url,
            }
        except Exception as e:
            return {'status': 'offline', 'backend': 'openwebui', 'error': str(e), 'url': self.url}


def create_llm_backend() -> OllamaBackend | OpenWebUIBackend:
    """Factory: instantiate the correct backend from settings.LLM_BACKEND."""
    backend_type = getattr(settings, 'LLM_BACKEND', 'ollama')

    if backend_type == 'openwebui':
        url = settings.OPENWEBUI_URL
        api_key = settings.OPENWEBUI_API_KEY
        if not api_key:
            logger.warning('OPENWEBUI_API_KEY is not set -- requests may be rejected')
        return OpenWebUIBackend(url=url, api_key=api_key)
    return OllamaBackend(url=settings.OLLAMA_URL)
