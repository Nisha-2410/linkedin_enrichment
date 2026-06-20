import asyncio

from backend.rate_limiter import SlidingWindowRateLimiter


class FakeTime:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


def test_never_starts_more_than_15_calls_in_rolling_minute():
    async def scenario():
        fake = FakeTime()
        limiter = SlidingWindowRateLimiter(15, 60, fake.clock, fake.sleep)
        starts = [await limiter.acquire() for _ in range(31)]
        assert starts[:15] == [0.0] * 15
        assert starts[15:30] == [60.0] * 15
        assert starts[30] == 120.0
        for start in starts:
            assert sum(start - 60 < other <= start for other in starts) <= 15

    asyncio.run(scenario())

