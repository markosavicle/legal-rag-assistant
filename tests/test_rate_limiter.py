import pytest

from app.llm import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def limiter(per_minute):
    fake = FakeClock()
    return RateLimiter(per_minute, clock=fake.clock, sleep=fake.sleep), fake


def test_no_limit_never_waits():
    rl, fake = limiter(0)
    for _ in range(10):
        rl.acquire(100)
    assert fake.sleeps == []


def test_within_limit_does_not_wait():
    rl, fake = limiter(90)
    rl.acquire(50)
    rl.acquire(40)
    assert fake.sleeps == []


def test_waits_until_window_frees_up():
    rl, fake = limiter(90)
    rl.acquire(90)
    fake.now = 10
    rl.acquire(90)
    # The first batch leaves the window 60 s after it was sent, i.e. 50 s from now.
    assert fake.sleeps == [pytest.approx(50.5)]
    assert fake.now == pytest.approx(60.5)


def test_large_upload_is_spread_over_minutes():
    rl, fake = limiter(90)
    for _ in range(5):  # 450 texts at 90 per minute
        rl.acquire(90)
    assert fake.now >= 4 * 60


def test_batch_larger_than_limit_is_rejected():
    rl, _ = limiter(90)
    with pytest.raises(ValueError):
        rl.acquire(100)
