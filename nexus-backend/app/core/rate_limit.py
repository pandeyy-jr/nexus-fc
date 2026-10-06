"""Application-level rate limiting abstraction (Phase 09F).

Provides a bounded in-memory rate limiter with a clean interface that
can be replaced by a distributed Redis-backed implementation later.
Does not claim distributed guarantees.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol

from fastapi import HTTPException, status


class RateLimiter(Protocol):
    """Protocol for rate limiting implementations."""

    def check_limit(self, key: str) -> None:
        """Raise HTTPException(429) if limit exceeded."""
        ...

    def record_hit(self, key: str) -> None:
        """Record a successful request."""
        ...


@dataclass(slots=True)
class _Bucket:
    """Sliding window bucket for a single key."""

    timestamps: list[float] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)


class InMemoryRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter.

    Not distributed — suitable for single-process deployments.
    For multi-instance deployments, replace with a Redis-backed
    implementation adhering to the RateLimiter protocol.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: float,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._max_requests = max_requests
        self._window = window_seconds
        self._buckets: dict[str, _Bucket] = defaultdict(_Bucket)
        self._cleanup_lock = Lock()
        self._last_cleanup = time.monotonic()

    def check_limit(self, key: str) -> None:
        """Check if key has exceeded its limit. Raises 429 if so."""
        now = time.monotonic()
        bucket = self._buckets[key]
        with bucket.lock:
            self._prune(bucket, now)
            if len(bucket.timestamps) >= self._max_requests:
                oldest = bucket.timestamps[0]
                retry_after = int(oldest + self._window - now) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(max(1, retry_after))},
                )

    def record_hit(self, key: str) -> None:
        """Record a successful request for the key."""
        now = time.monotonic()
        bucket = self._buckets[key]
        with bucket.lock:
            self._prune(bucket, now)
            bucket.timestamps.append(now)
        self._maybe_cleanup(now)

    def _prune(self, bucket: _Bucket, now: float) -> None:
        """Remove timestamps outside the window."""
        cutoff = now - self._window
        while bucket.timestamps and bucket.timestamps[0] < cutoff:
            bucket.timestamps.pop(0)

    def _maybe_cleanup(self, now: float) -> None:
        """Periodically evict empty buckets to bound memory."""
        if now - self._last_cleanup < 60.0:
            return
        with self._cleanup_lock:
            if now - self._last_cleanup < 60.0:
                return
            empty = [k for k, b in self._buckets.items() if not b.timestamps]
            for k in empty:
                self._buckets.pop(k, None)
            self._last_cleanup = now


def build_copilot_rate_limiter() -> RateLimiter:
    """Build the configured Copilot rate limiter from settings.

    Uses application settings for limits. Safe to call at startup;
    does not require external services.
    """
    from app.core.config import get_settings

    settings = get_settings()
    return InMemoryRateLimiter(
        max_requests=settings.copilot_rate_limit_requests,
        window_seconds=settings.copilot_rate_limit_window_seconds,
    )
