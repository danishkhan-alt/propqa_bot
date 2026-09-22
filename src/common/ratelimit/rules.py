from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimit:
    """How many, how often, and under what name.

    ``scope`` is part of the cache key, so two limits never share a counter
    even when they measure the same caller.
    """

    scope: str
    limit: int
    window_seconds: int

    @property
    def description(self) -> str:
        return f"{self.limit} per {self.window_seconds}s"


# Sign-in: counted on failure only, so a good password does not eat quota
# and an attacker cannot lock someone out by succeeding against their address.
SIGN_IN_CALLER_BURST = RateLimit("auth.sign_in.caller.burst", 10, 300)
SIGN_IN_CALLER_HOURLY = RateLimit("auth.sign_in.caller.hourly", 50, 3600)
SIGN_IN_ACCOUNT_BURST = RateLimit("auth.sign_in.account.burst", 5, 900)
SIGN_IN_ACCOUNT_HOURLY = RateLimit("auth.sign_in.account.hourly", 20, 3600)

SIGN_IN_CALLER = (SIGN_IN_CALLER_BURST, SIGN_IN_CALLER_HOURLY)
SIGN_IN_ACCOUNT = (SIGN_IN_ACCOUNT_BURST, SIGN_IN_ACCOUNT_HOURLY)

TOKEN_REFRESH = RateLimit("auth.token_refresh", 30, 300)
REGISTER = RateLimit("auth.register", 5, 3600)

# Default ceilings. Visitors are cheaper to flood; registered users share an
# office NAT so they get a higher per-person cap.
API_VISITOR = RateLimit("api.visitor", 60, 60)
API_REGISTERED = RateLimit("api.registered", 300, 60)

# Agent turns cost LLM + warehouse work. Separate from generic API traffic.
CHAT_VISITOR = RateLimit("chat.visitor", 20, 60)
CHAT_REGISTERED = RateLimit("chat.registered", 60, 60)
