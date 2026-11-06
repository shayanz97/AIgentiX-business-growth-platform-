"""Login abuse protection: per-account failure throttling and a cap on concurrent password hashing.

In-process state, which is correct for the single API process of Sprint 1. When the API runs with several
processes or replicas, also add an IP-based limit at the reverse proxy (see docs/ARCHITECTURE.md).
"""

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from aigentix.core.errors import AppError


class TooManyAttempts(AppError):
    status_code = 429
    code = "too_many_attempts"


class ServiceBusy(AppError):
    status_code = 503
    code = "service_busy"


class LoginThrottle:
    def __init__(
        self,
        *,
        max_failures: int = 10,
        window_seconds: float = 15 * 60,
        max_concurrent_hashes: int = 4,
        max_tracked_accounts: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self.max_tracked = max_tracked_accounts
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        # Argon2id is memory-hard (~64 MiB per hash): bound how many run at once.
        self._hash_slots = threading.BoundedSemaphore(max_concurrent_hashes)

    def _recent(self, key: str, now: float) -> deque[float]:
        attempts = self._failures.get(key, deque())
        while attempts and attempts[0] <= now - self.window:
            attempts.popleft()
        return attempts

    def check(self, key: str) -> None:
        with self._lock:
            if len(self._recent(key, self._clock())) >= self.max_failures:
                raise TooManyAttempts("Too many failed sign-in attempts. Try again later.")

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            attempts = self._recent(key, now)
            attempts.append(now)
            self._failures[key] = attempts
            if len(self._failures) > self.max_tracked:
                # Drop the entry with the oldest latest failure to keep memory bounded.
                oldest = min(self._failures, key=lambda k: self._failures[k][-1] if self._failures[k] else 0.0)
                self._failures.pop(oldest, None)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    @contextmanager
    def hashing_slot(self, timeout: float = 5.0) -> Iterator[None]:
        if not self._hash_slots.acquire(timeout=timeout):
            raise ServiceBusy("Sign-in is temporarily busy. Please retry.")
        try:
            yield
        finally:
            self._hash_slots.release()


login_throttle = LoginThrottle()
