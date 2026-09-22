from enum import Enum


class UserKind(str, Enum):
    """Who is talking to the agent.

    Registered users have an account. Visitors do not; they are still first-class
    callers with their own session, cache, and rate-limit identity.
    """

    REGISTERED = "registered"
    VISITOR = "visitor"
