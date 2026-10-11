from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Callable


class ChatLimitError(RuntimeError):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = max(1, retry_after)


class ChatLimiter:
    """Single-process limits, keyed by an Identity-verified user, never by raw JWT."""

    def __init__(self, requests: int = 10, window_seconds: int = 60,
                 max_concurrent: int = 1, clock: Callable[[], float] = time.monotonic):
        self.requests = requests
        self.window = window_seconds
        self.max_concurrent = max_concurrent
        self.clock = clock
        self._buckets: dict[int, deque[float]] = {}
        self._active: set[int] = set()
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, user_id: int) -> AsyncIterator[None]:
        async with self._lock:
            now = self.clock()
            # Prune inactive users so the limiter itself cannot grow indefinitely.
            for key in list(self._buckets):
                bucket = self._buckets[key]
                while bucket and now - bucket[0] >= self.window:
                    bucket.popleft()
                if not bucket:
                    del self._buckets[key]
            bucket = self._buckets.setdefault(user_id, deque())
            if len(bucket) >= self.requests:
                raise ChatLimitError("Bạn đã gửi quá nhiều câu hỏi. Vui lòng chờ trước khi thử lại.",
                                     math.ceil(self.window - (now - bucket[0])))
            if user_id in self._active or len(self._active) >= self.max_concurrent:
                raise ChatLimitError("Trợ lý đang xử lý câu hỏi khác. Vui lòng thử lại sau.", 5)
            if len(self._buckets) > 10000:
                self._buckets.pop(user_id, None)
                raise ChatLimitError("Trợ lý đang bận. Vui lòng thử lại sau.", self.window)
            bucket.append(now)
            self._active.add(user_id)
        try:
            yield
        finally:
            async with self._lock:
                self._active.discard(user_id)
