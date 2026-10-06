"""Fixed-window rate limiter: Redis when configured (shared across workers), else in-memory."""
import time
from collections import defaultdict

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    def __init__(self) -> None:
        self._mem: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        self._redis = None
        url = get_settings().redis_url
        if url:
            try:
                import redis
                self._redis = redis.Redis.from_url(url, socket_timeout=1)
            except Exception:  # graceful degradation
                logger.warning("Redis unavailable for rate limiting; using in-memory")

    def allow(self, key: str, limit: int) -> bool:
        window = int(time.time() // 60)
        if self._redis is not None:
            try:
                k = f"rl:{key}:{window}"
                n = self._redis.incr(k)
                if n == 1:
                    self._redis.expire(k, 70)
                return n <= limit
            except Exception:
                logger.warning("Redis rate-limit error; falling back to memory")
        w, n = self._mem[key]
        if w != window:
            w, n = window, 0
        n += 1
        self._mem[key] = (w, n)
        if len(self._mem) > 50_000:  # bound memory
            self._mem.clear()
        return n <= limit
