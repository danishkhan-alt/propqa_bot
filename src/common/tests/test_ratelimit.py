from __future__ import annotations

import pytest

from common.errors.rate_limited import RateLimited
from common.ratelimit.limiter import RateLimiter
from common.schemas.rate_limit import RateLimit

RULE = RateLimit("test.burst", 3, 60)


def test_enforce_allows_up_to_the_limit(memory_cache):
    limiter = RateLimiter(backend=memory_cache)
    limiter.enforce("visitor:v1", RULE)
    limiter.enforce("visitor:v1", RULE)
    limiter.enforce("visitor:v1", RULE)


def test_enforce_refuses_once_over(memory_cache):
    limiter = RateLimiter(backend=memory_cache)
    for _ in range(3):
        limiter.enforce("visitor:v1", RULE)

    with pytest.raises(RateLimited) as captured:
        limiter.enforce("visitor:v1", RULE)
    assert captured.value.retry_after >= 1


def test_two_identities_do_not_share_a_counter(memory_cache):
    limiter = RateLimiter(backend=memory_cache)
    for _ in range(3):
        limiter.enforce("visitor:v1", RULE)
    limiter.enforce("registered:u1", RULE)


def test_recorded_failures_block_without_counting_the_check(memory_cache):
    limiter = RateLimiter(backend=memory_cache)
    limiter.record("ip:1.1.1.1", RULE)
    limiter.record("ip:1.1.1.1", RULE)
    limiter.enforce_without_counting("ip:1.1.1.1", RULE)
    limiter.enforce_without_counting("ip:1.1.1.1", RULE)

    limiter.record("ip:1.1.1.1", RULE)
    with pytest.raises(RateLimited):
        limiter.enforce_without_counting("ip:1.1.1.1", RULE)
