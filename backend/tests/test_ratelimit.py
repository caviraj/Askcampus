"""The sliding window, against a clock the test controls.

A real clock would make these tests either slow or flaky, and the boundary is
the whole point: the difference between a window that slides and one that resets
only shows up at the moment a hit ages out.
"""

from __future__ import annotations

from app.services.ratelimit import _MAX_TRACKED_KEYS, SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_allows_exactly_the_limit():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=3, clock=clock)

    assert [limiter.hit("ip:1.2.3.4")[0] for _ in range(3)] == [True, True, True]


def test_refuses_one_past_the_limit():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=3, clock=clock)
    for _ in range(3):
        limiter.hit("ip:1.2.3.4")

    allowed, retry_after = limiter.hit("ip:1.2.3.4")

    assert allowed is False
    assert retry_after == 60


def test_the_counter_advances_as_the_window_closes():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=1, clock=clock)
    limiter.hit("ip:1.2.3.4")

    clock.advance(20)
    allowed, retry_after = limiter.hit("ip:1.2.3.4")

    assert allowed is False
    # Forty seconds left on the first hit, not a fresh sixty.
    assert retry_after == 40


def test_a_slot_frees_at_the_boundary():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=1, clock=clock)
    limiter.hit("ip:1.2.3.4")

    clock.advance(60)

    assert limiter.hit("ip:1.2.3.4")[0] is True


def test_still_refused_one_instant_before_the_boundary():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=1, clock=clock)
    limiter.hit("ip:1.2.3.4")

    clock.advance(59.999)

    allowed, retry_after = limiter.hit("ip:1.2.3.4")
    assert allowed is False
    # Never zero: a client that honours Retry-After must not retry into the same
    # refusal.
    assert retry_after >= 1


def test_keys_do_not_share_a_counter():
    limiter = SlidingWindowRateLimiter(limit=1, clock=FakeClock())
    limiter.hit("ip:1.2.3.4")

    assert limiter.hit("session:abc")[0] is True
    assert limiter.hit("ip:1.2.3.4")[0] is False


def test_a_refused_key_is_not_recorded():
    """A rejection must not extend the window it is rejecting against.

    Recording it would mean a caller who keeps trying never gets back in: every
    attempt would push the oldest hit's expiry out of reach.
    """
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=1, clock=clock)
    limiter.hit("ip:1.2.3.4")
    for _ in range(5):
        assert limiter.hit("ip:1.2.3.4")[0] is False

    clock.advance(60)

    assert limiter.hit("ip:1.2.3.4")[0] is True


def test_reset_forgets_every_key():
    limiter = SlidingWindowRateLimiter(limit=1, clock=FakeClock())
    limiter.hit("ip:1.2.3.4")
    limiter.hit("session:abc")

    limiter.reset()

    assert limiter.hit("ip:1.2.3.4")[0] is True
    assert limiter.hit("session:abc")[0] is True


def test_the_table_stays_bounded():
    """Addresses that never come back must not accumulate for the process's life.

    Driven past the threshold deliberately, because the sweep only runs when the
    table is already large -- which is what makes its amortised cost negligible.
    """
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=5, clock=clock)
    for index in range(_MAX_TRACKED_KEYS + 1):
        limiter.hit(f"ip:10.0.{index // 256}.{index % 256}")
    assert len(limiter._hits) > _MAX_TRACKED_KEYS

    # Every one of them is now outside the window, so the next hit sweeps them.
    clock.advance(120)
    limiter.hit("ip:192.168.0.1")

    assert list(limiter._hits) == ["ip:192.168.0.1"]


def test_a_live_key_survives_a_sweep():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=5, clock=clock)
    for index in range(_MAX_TRACKED_KEYS + 1):
        limiter.hit(f"ip:10.0.{index // 256}.{index % 256}")

    clock.advance(30)
    # Inside the window, so the sweep must leave it alone.
    limiter.hit("ip:192.168.0.1")
    clock.advance(40)
    limiter.hit("ip:203.0.113.9")

    assert "ip:192.168.0.1" in limiter._hits
    assert limiter.hit("ip:192.168.0.1")[0] is True
