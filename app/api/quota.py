"""
Question quotas, shared by every server instance (counters live in the app database).

    quota = QuestionQuota(engine, settings)
    ticket = quota.reserve(actor="u:<user id>" or "g:<ip>", signed_in=True)   # QuotaExceeded if over
    ...                                       # ask the model
    quota.refund(ticket)                      # only if the AI provider was unusable (nothing spent)
    ticket.left_today                         # questions this actor has left today (None = unlimited)

Limits (0 disables one):
    QUESTIONS_PER_MINUTE      per account (guests: per IP)                       default 10
    QUESTIONS_PER_DAY_USER    per signed-in account                              default 35
    QUESTIONS_PER_DAY_GUEST   per guest IP                                       default 5
    QUESTIONS_PER_DAY_SITE    everyone together: protects the AI budget          default 250

Days run midnight to midnight India time (UTC+05:30). Reserving increments all counters in one
transaction and rolls back if any limit is passed, so rejected questions are never counted.
Admins (ADMIN_EMAILS) are not limited and not counted.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import Engine, delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.app_tables import usage_counters

IST = timezone(timedelta(hours=5, minutes=30))


class QuotaExceeded(Exception):
    """A limit was reached. `code` tells the UI which message to show."""

    def __init__(self, code: str, message: str, retry_after: int):
        super().__init__(message)
        self.code = code  # rate_minute | daily_user | daily_guest | daily_site
        self.retry_after = retry_after  # seconds until it resets


@dataclass
class Ticket:
    keys: list[str] = field(default_factory=list)
    left_today: int | None = None


def _seconds_to_midnight(now: datetime) -> int:
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds()) + 1


class QuestionQuota:
    def __init__(self, engine: Engine, per_minute: int, per_day_user: int, per_day_guest: int, per_day_site: int):
        self.engine = engine
        self.per_minute = per_minute
        self.per_day_user = per_day_user
        self.per_day_guest = per_day_guest
        self.per_day_site = per_day_site
        self._insert = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert

    @property
    def enabled(self) -> bool:
        return any((self.per_minute, self.per_day_user, self.per_day_guest, self.per_day_site))

    def _bump(self, conn, key: str, day: str) -> int:
        c = usage_counters.c
        stmt = self._insert(usage_counters).values(key=key, day=day, count=1)
        stmt = stmt.on_conflict_do_update(index_elements=[c.key], set_={"count": c.count + 1}).returning(c.count)
        return conn.execute(stmt).scalar_one()

    def reserve(self, actor: str, signed_in: bool, now: datetime | None = None) -> Ticket:
        if not self.enabled:
            return Ticket()
        now = (now or datetime.now(UTC)).astimezone(IST)
        day = now.strftime("%Y-%m-%d")
        daily = self.per_day_user if signed_in else self.per_day_guest
        checks = [  # (key, limit, code, message, seconds until reset)
            (
                f"m:{actor}:{now:%Y%m%d%H%M}",
                self.per_minute,
                "rate_minute",
                f"you can ask {self.per_minute} questions a minute",
                60 - now.second,
            ),
            (
                f"d:{actor}:{day}",
                daily,
                "daily_user" if signed_in else "daily_guest",
                f"{'accounts' if signed_in else 'guests'} can ask {daily} questions a day",
                _seconds_to_midnight(now),
            ),
            (
                f"s:{day}",
                self.per_day_site,
                "daily_site",
                f"the demo answers {self.per_day_site} questions a day in total",
                _seconds_to_midnight(now),
            ),
        ]
        checks = [ch for ch in checks if ch[1] > 0]
        ticket = Ticket(keys=[ch[0] for ch in checks])
        with self.engine.connect() as conn:
            tx = conn.begin()
            counts = {}
            for key, limit, code, message, retry in checks:
                counts[key] = n = self._bump(conn, key, day)
                if n > limit:
                    tx.rollback()  # nothing is counted for a rejected question
                    raise QuotaExceeded(code, message, retry)
            if counts.get(f"s:{day}") == 1:  # first question of the day: drop old counters
                conn.execute(delete(usage_counters).where(usage_counters.c.day < day))
            tx.commit()
        daily_key = f"d:{actor}:{day}"
        if daily > 0:
            ticket.left_today = daily - counts[daily_key]
        return ticket

    def refund(self, ticket: Ticket) -> None:
        """Give a question back (the AI provider failed before doing any work)."""
        if not ticket.keys:
            return
        c = usage_counters.c
        with self.engine.begin() as conn:
            conn.execute(update(usage_counters).where(c.key.in_(ticket.keys), c.count > 0).values(count=c.count - 1))
