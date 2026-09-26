"""Which environment the app runs in."""

from enum import StrEnum


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production(self) -> bool:
        return self is AppEnvironment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self is AppEnvironment.DEVELOPMENT

    @property
    def is_test(self) -> bool:
        return self is AppEnvironment.TEST

    @property
    def is_deployed(self) -> bool:
        return self in (AppEnvironment.STAGING, AppEnvironment.PRODUCTION)
