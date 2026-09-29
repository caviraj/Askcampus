"""In-process rate limiting for the chat endpoint.

`AGENTS.md` section 10 requires `/chat` to be limited per IP and per session, and
`ARCHITECTURE.md` section 9 suggests "for example 20 per minute". Neither says
where the counters live. They live in this process, decided with the user: no new
table, no write on the request path, and no new way for a slow database to refuse
a question.

The cost is stated plainly rather than hidden. Counters are per process, so with
`--workers 2` each worker allows the full limit and the effective rate is double;
they also reset on restart. That is the same single-instance assumption the
startup reaper documents.

`hit` never awaits, so on one event loop it cannot interleave with itself and no
lock is needed.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

# A public endpoint sees traffic from addresses that never come back, and every
# one of them would otherwise leave a deque behind for the life of the process. A
# sweep happens only once the table is larger than this, so the amortised cost is
# negligible and the memory stays bounded.
_MAX_TRACKED_KEYS = 10_000


class SlidingWindowRateLimiter:
    """Counts hits per key over a trailing window."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    @property
    def limit(self) -> int:
        return self._limit

    def hit(self, key: str) -> tuple[bool, int]:
        """Record an attempt against `key`, returning (allowed, retry_after_seconds).

        A sliding window rather than a fixed one: a fixed window lets a caller
        spend the whole allowance at the end of one minute and again at the start
        of the next, which is twice the intended rate at exactly the moment it
        matters.
        """
        now = self._clock()
        cutoff = now - self._window

        queue = self._hits.setdefault(key, deque())
        while queue and queue[0] <= cutoff:
            queue.popleft()

        if len(queue) >= self._limit:
            # The oldest hit in the window is the one whose expiry frees a slot.
            # Rounded up, and never below 1, so a client that honours the header
            # cannot retry into the same rejection.
            return False, max(1, math.ceil(queue[0] - cutoff))

        queue.append(now)
        if len(self._hits) > _MAX_TRACKED_KEYS:
            self._sweep(cutoff)
        return True, 0

    def reset(self) -> None:
        """Forget every counter. Used by tests to isolate one from the next."""
        self._hits.clear()

    def _sweep(self, cutoff: float) -> None:
        stale = [key for key, queue in self._hits.items() if not queue or queue[-1] <= cutoff]
        for key in stale:
            del self._hits[key]
