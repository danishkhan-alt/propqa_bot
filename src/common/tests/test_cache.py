from __future__ import annotations

from common.cache.user_cache import CallerScopedCache
from common.enums.user_kind import UserKind
from common.identity import Caller


def _cache(kind: UserKind, subject_id: str, backend) -> CallerScopedCache:
    return CallerScopedCache(Caller(kind=kind, subject_id=subject_id), backend=backend)


def test_registered_and_visitor_do_not_share_keys(memory_cache):
    registered = _cache(UserKind.REGISTERED, "user-1", memory_cache)
    visitor = _cache(UserKind.VISITOR, "visitor-1", memory_cache)

    registered.set("chat:last", "registered answer", ttl=60)

    assert registered.get("chat:last") == "registered answer"
    assert visitor.get("chat:last") is None


def test_two_registered_users_are_isolated(memory_cache):
    alice = _cache(UserKind.REGISTERED, "alice", memory_cache)
    bob = _cache(UserKind.REGISTERED, "bob", memory_cache)

    alice.set("chat:last", "alice", ttl=60)

    assert alice.get("chat:last") == "alice"
    assert bob.get("chat:last") is None


def test_it_refuses_to_exist_without_a_caller():
    try:
        CallerScopedCache(None)  # type: ignore[arg-type]
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_cached_none_is_not_a_miss(memory_cache):
    cache = _cache(UserKind.VISITOR, "v1", memory_cache)
    cache.set("chat:empty", None, ttl=60)

    sentinel = object()
    assert cache.get("chat:empty", sentinel) is None
    assert cache.get("chat:never-set", sentinel) is sentinel


def test_get_or_set_computes_once(memory_cache):
    cache = _cache(UserKind.REGISTERED, "user-1", memory_cache)
    calls = []

    def factory():
        calls.append(1)
        return "computed"

    assert cache.get_or_set("chat:1", factory, ttl=60) == "computed"
    assert cache.get_or_set("chat:1", factory, ttl=60) == "computed"
    assert len(calls) == 1


def test_invalidating_a_category_stays_on_one_caller(memory_cache):
    alice = _cache(UserKind.REGISTERED, "alice", memory_cache)
    bob = _cache(UserKind.REGISTERED, "bob", memory_cache)

    alice.set("chat:last", 1, ttl=60)
    alice.set("session:summary", 2, ttl=60)
    bob.set("chat:last", 3, ttl=60)

    alice.invalidate_category("chat")

    assert alice.get("chat:last") is None
    assert alice.get("session:summary") == 2
    assert bob.get("chat:last") == 3


def test_invalidating_everything_stays_on_one_caller(memory_cache):
    alice = _cache(UserKind.REGISTERED, "alice", memory_cache)
    visitor = _cache(UserKind.VISITOR, "v1", memory_cache)

    alice.set("chat:last", 1, ttl=60)
    alice.set("session:summary", 2, ttl=60)
    visitor.set("chat:last", 3, ttl=60)

    alice.invalidate_all()

    assert alice.get("chat:last") is None
    assert alice.get("session:summary") is None
    assert visitor.get("chat:last") == 3


def test_generations_advance_rather_than_reset(memory_cache):
    cache = _cache(UserKind.VISITOR, "v1", memory_cache)
    first = cache.scoped_key("chat:last")
    cache.invalidate_category("chat")
    second = cache.scoped_key("chat:last")
    cache.invalidate_category("chat")
    third = cache.scoped_key("chat:last")

    assert len({first, second, third}) == 3


def test_writes_after_invalidation_are_readable_again(memory_cache):
    cache = _cache(UserKind.REGISTERED, "user-1", memory_cache)
    cache.set("chat:last", 1, ttl=60)
    cache.invalidate_all()
    cache.set("chat:last", 2, ttl=60)
    assert cache.get("chat:last") == 2
