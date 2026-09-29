from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import ActiveConfig


class AppClock:
    """Timezone-aware clock. App zone defaults to Asia/Dubai."""

    @staticmethod
    def app_zone() -> ZoneInfo:
        return ZoneInfo(ActiveConfig.TIMEZONE)

    @staticmethod
    def now() -> datetime:
        return datetime.now(AppClock.app_zone())

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)
