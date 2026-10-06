"""Retry with exponential backoff + jitter, for transient failures only."""
import random
import time
from typing import Callable, TypeVar

from app.core.exceptions import AppError

T = TypeVar("T")


def with_retry(fn: Callable[[], T], *, max_retries: int, base_delay: float = 0.5,
               max_delay: float = 8.0, sleep: Callable[[float], None] = time.sleep) -> T:
    """Retry only AppErrors flagged transient. Never loops forever."""
    attempt = 0
    while True:
        try:
            return fn()
        except AppError as exc:
            if not exc.transient or attempt >= max_retries:
                raise
            delay = min(max_delay, base_delay * (2 ** attempt)) * (0.5 + random.random() / 2)
            sleep(delay)
            attempt += 1
