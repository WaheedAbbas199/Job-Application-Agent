"""Embedding helpers. Vectors are tagged with the model id so incompatible vectors are never mixed."""
import math

from app.llm.provider import LLMProvider


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def ensure_embedding(provider: LLMProvider, stored: dict | None, text: str) -> tuple[dict, bool]:
    """Return (embedding, changed). Recomputes if missing or produced by a different model."""
    if stored and stored.get("m") == provider.embedding_id and stored.get("v"):
        return stored, False
    vec = provider.embed([text[:8000] or " "])[0]
    return {"m": provider.embedding_id, "v": vec}, True
