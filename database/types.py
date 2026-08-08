# TradePilot AI — a datetime column type that actually survives SQLite.
#
# In plain terms: SQLite has no real datetime type. SQLAlchemy's default
# DateTime column works around that by storing dates as plain text, but it
# throws away the "+00:00" (UTC) part when it writes and never adds it
# back when it reads. So a value that starts out correctly timezone-aware
# comes back out of the database as if it had no timezone at all.
#
# That matters a lot for TradePilot: a later guardrail will need to
# compare "how old is this screenshot?" by subtracting captured_at from
# right now. Python refuses to subtract a timezone-aware time from a
# naive one (it raises an error), and if it didn't refuse, comparing them
# directly would silently be wrong whenever the two aren't in the same
# timezone. TZDateTime closes that gap: every timestamp in this project
# goes in as UTC and comes back out as UTC, always.

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class TZDateTime(TypeDecorator):
    """A DateTime column that requires UTC-aware input and always returns UTC-aware output."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "TZDateTime received a naive datetime; pass a timezone-aware "
                "one (e.g. datetime.now(timezone.utc))."
            )
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)
