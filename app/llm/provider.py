"""LLMProvider abstraction. Business logic depends only on this interface.

GeminiProvider talks to the Gemini REST API. LocalProvider has no text generation
(available=False) but gives deterministic hashing embeddings, so the app degrades
gracefully (heuristic parsing/templates) when no API key is configured.
"""
import math
import re
import zlib
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import EmbeddingError, LLMError
from app.core.retry import with_retry

_GEMINI = "https://generativelanguage.googleapis.com/v1beta"
_TOKEN = re.compile(r"[a-z0-9+#.]{2,}")


class LLMProvider(ABC):
    name: str = "base"
    available: bool = False
    embedding_id: str = "none"

    @abstractmethod
    def generate_text(self, system: str, prompt: str) -> str: ...

    @abstractmethod
    def generate_json_text(self, system: str, prompt: str) -> str: ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def hash_embed(text: str, dims: int = 256) -> list[float]:
    vec = [0.0] * dims
    for tok in _TOKEN.findall(text.lower()):
        vec[zlib.crc32(tok.encode()) % dims] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class LocalProvider(LLMProvider):
    name = "local"
    available = False
    embedding_id = "hash-256"

    def generate_text(self, system: str, prompt: str) -> str:
        raise LLMError("LLM not configured (set GEMINI_API_KEY)")

    generate_json_text = generate_text

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [hash_embed(t) for t in texts]


class GeminiProvider(LLMProvider):
    name = "gemini"
    available = True

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=settings.llm_timeout_seconds)
        self.embedding_id = f"gemini:{settings.embedding_model}"

    def _post(self, url: str, body: dict) -> dict:
        def call() -> dict:
            try:
                r = self.client.post(url, json=body, headers={"x-goog-api-key": self.s.gemini_api_key or ""})
            except httpx.TimeoutException as exc:
                raise LLMError("LLM request timed out", transient=True) from exc
            except httpx.HTTPError as exc:
                raise LLMError("LLM network error", transient=True) from exc
            if r.status_code == 429 or r.status_code >= 500:
                raise LLMError(f"LLM temporary failure ({r.status_code})", transient=True)
            if r.status_code >= 400:
                raise LLMError(f"LLM request rejected ({r.status_code})")
            return r.json()
        return with_retry(call, max_retries=self.s.max_retries)

    def _generate(self, system: str, prompt: str, json_mode: bool) -> str:
        body: dict = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        data = self._post(f"{_GEMINI}/models/{self.s.llm_model}:generateContent", body)
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected LLM response shape") from exc

    def generate_text(self, system: str, prompt: str) -> str:
        return self._generate(system, prompt, False)

    def generate_json_text(self, system: str, prompt: str) -> str:
        return self._generate(system, prompt, True)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        m = self.s.embedding_model
        body = {"requests": [{"model": f"models/{m}", "content": {"parts": [{"text": t[:8000]}]}}
                             for t in texts]}
        try:
            data = self._post(f"{_GEMINI}/models/{m}:batchEmbedContents", body)
            return [e["values"] for e in data["embeddings"]]
        except LLMError as exc:
            raise EmbeddingError(exc.message, transient=exc.transient) from exc
        except (KeyError, TypeError) as exc:
            raise EmbeddingError("Unexpected embedding response") from exc


def build_provider(settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()
    return GeminiProvider(s) if s.gemini_api_key else LocalProvider()


_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = build_provider()
    return _provider
