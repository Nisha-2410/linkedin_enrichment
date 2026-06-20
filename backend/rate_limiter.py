import asyncio
import time
from collections import deque


class SlidingWindowRateLimiter:
    def __init__(self, max_calls, window_seconds, clock=None, sleep=None):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._timestamps = deque()
        self._lock = asyncio.Lock()

    def usage(self):
        now = self._clock()
        self._prune(now)
        return len(self._timestamps)

    def _prune(self, now):
        while self._timestamps and now - self._timestamps[0] >= self.window_seconds:
            self._timestamps.popleft()

    async def acquire(self):
        async with self._lock:
            while True:
                now = self._clock()
                self._prune(now)
                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(now)
                    return now
                await self._sleep(max(0, self.window_seconds - (now - self._timestamps[0])))
