"""Account storage: Postgres in the chatbot database, or in process for tests."""

from auth.storage.in_memory_repository import InMemoryUserRepository
from auth.storage.postgres import PostgresUserRepository

UserRepository = InMemoryUserRepository | PostgresUserRepository

__all__ = ["InMemoryUserRepository", "PostgresUserRepository", "UserRepository"]
