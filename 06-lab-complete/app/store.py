import logging
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rate_limit_events: Dict[str, List[float]] = defaultdict(list)
        self._values: Dict[str, float] = {}
        self._expires_at: Dict[str, float] = {}

    def _cleanup_expired_locked(self) -> None:
        now = time.time()
        expired = [key for key, expires_at in self._expires_at.items() if expires_at <= now]
        for key in expired:
            self._values.pop(key, None)
            self._expires_at.pop(key, None)

    def count_recent_requests(self, key: str, window_seconds: int) -> int:
        now = time.time()
        with self._lock:
            events = [event for event in self._rate_limit_events[key] if event > now - window_seconds]
            self._rate_limit_events[key] = events
            return len(events)

    def add_request(self, key: str, ttl_seconds: int) -> None:
        now = time.time()
        with self._lock:
            events = [event for event in self._rate_limit_events[key] if event > now - ttl_seconds]
            events.append(now)
            self._rate_limit_events[key] = events

    def get_float(self, key: str) -> float:
        with self._lock:
            self._cleanup_expired_locked()
            return float(self._values.get(key, 0.0))

    def incrbyfloat(self, key: str, amount: float, ttl_seconds: int) -> float:
        with self._lock:
            self._cleanup_expired_locked()
            new_value = float(self._values.get(key, 0.0)) + amount
            self._values[key] = new_value
            self._expires_at[key] = time.time() + ttl_seconds
            return new_value


class Store:
    def __init__(self) -> None:
        self.backend = "memory"
        self.redis_client: Optional[redis.Redis] = None
        self.memory = InMemoryStore()
        self._connect()

    def _connect(self) -> None:
        if not settings.redis_url:
            logger.warning("REDIS_URL not set. Using in-memory store.")
            return

        try:
            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            client.ping()
            self.redis_client = client
            self.backend = "redis"
            logger.info("Connected to Redis.")
        except Exception as exc:
            logger.warning("Redis unavailable, using in-memory store: %s", exc)

    def count_recent_requests(self, key: str, window_seconds: int) -> int:
        if self.redis_client:
            now = time.time()
            pipe = self.redis_client.pipeline()
            pipe.zremrangebyscore(key, 0, now - window_seconds)
            pipe.zcard(key)
            pipe.expire(key, max(window_seconds * 2, 1))
            results = pipe.execute()
            return int(results[1])

        return self.memory.count_recent_requests(key, window_seconds)

    def add_request(self, key: str, ttl_seconds: int) -> None:
        if self.redis_client:
            now = time.time()
            member = f"{now}-{time.monotonic_ns()}"
            pipe = self.redis_client.pipeline()
            pipe.zadd(key, {member: now})
            pipe.expire(key, max(ttl_seconds, 1))
            pipe.execute()
            return

        self.memory.add_request(key, ttl_seconds)

    def get_float(self, key: str) -> float:
        if self.redis_client:
            value = self.redis_client.get(key)
            return float(value or 0.0)

        return self.memory.get_float(key)

    def incrbyfloat(self, key: str, amount: float, ttl_seconds: int) -> float:
        if self.redis_client:
            pipe = self.redis_client.pipeline()
            pipe.incrbyfloat(key, amount)
            pipe.expire(key, max(ttl_seconds, 1))
            results = pipe.execute()
            return float(results[0])

        return self.memory.incrbyfloat(key, amount, ttl_seconds)


store = Store()
