from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int = 0


class RateLimitBackend(Protocol):
    async def allow(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision: ...


class InMemorySlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.monotonic()
        threshold = now - max(1, int(window_seconds))
        async with self._lock:
            events = self._events[str(key)]
            while events and events[0] <= threshold:
                events.popleft()
            if len(events) >= max(1, int(limit)):
                retry_after = max(1, int(window_seconds - (now - events[0])))
                return RateLimitDecision(False, 0, retry_after)
            events.append(now)
            return RateLimitDecision(True, max(0, int(limit) - len(events)), 0)


class RedisFixedWindowRateLimiter:
    """Optional distributed limiter; imported only when AGENT_REDIS_URL is configured."""

    def __init__(self, redis_url: str) -> None:
        try:
            from redis.asyncio import from_url
        except ImportError as exc:  # pragma: no cover - optional deployment dependency
            raise RuntimeError("redis package is required when AGENT_REDIS_URL is set") from exc
        self._client = from_url(redis_url, encoding="utf-8", decode_responses=True)

    async def allow(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        bucket = int(time.time()) // max(1, int(window_seconds))
        redis_key = f"agent_api:rate:{key}:{bucket}"
        count = int(await self._client.incr(redis_key))
        if count == 1:
            await self._client.expire(redis_key, max(1, int(window_seconds)) + 1)
        ttl = max(1, int(await self._client.ttl(redis_key)))
        return RateLimitDecision(
            allowed=count <= int(limit),
            remaining=max(0, int(limit) - count),
            retry_after_seconds=0 if count <= int(limit) else ttl,
        )


def build_rate_limiter(redis_url: str = "") -> RateLimitBackend:
    return RedisFixedWindowRateLimiter(redis_url) if redis_url else InMemorySlidingWindowRateLimiter()
