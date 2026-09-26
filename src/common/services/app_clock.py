from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import ActiveConfig


class AppClock:
    """Timezone-aware datetime helpers. App zone defaults to Asia/Dubai."""

    @staticmethod
    def app_zone() -> ZoneInfo:
        return ZoneInfo(ActiveConfig.TIMEZONE)

    @staticmethod
    def now() -> datetime:
        return datetime.now(AppClock.app_zone())

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def today() -> date:
        return AppClock.now().date()

    @staticmethod
    def ensure_aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=AppClock.app_zone())
        return dt

    @staticmethod
    def to_timezone(dt: datetime, tz_name: str) -> datetime:
        return AppClock.ensure_aware(dt).astimezone(ZoneInfo(tz_name))

    @staticmethod
    def start_of_day(dt: datetime | None = None) -> datetime:
        current = dt or AppClock.now()
        return current.replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def end_of_day(dt: datetime | None = None) -> datetime:
        current = dt or AppClock.now()
        return current.replace(hour=23, minute=59, second=59, microsecond=999999)

    @staticmethod
    def parse_datetime(value: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> datetime:
        return datetime.strptime(value, fmt).replace(tzinfo=AppClock.app_zone())

    @staticmethod
    def parse_date(value: str, fmt: str = "%Y-%m-%d") -> date:
        return datetime.strptime(value, fmt).date()

    @staticmethod
    def days_between(left: datetime | date, right: datetime | date) -> int:
        left_date = left.date() if isinstance(left, datetime) else left
        right_date = right.date() if isinstance(right, datetime) else right
        return abs((left_date - right_date).days)

    @staticmethod
    def add_days(dt: datetime, days: int) -> datetime:
        return dt + timedelta(days=days)
