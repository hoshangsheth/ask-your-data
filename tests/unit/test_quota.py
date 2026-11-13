"""
Question quotas (app/api/quota.py): counters shared through the database, India-time days,
rejected questions not counted, refunds, and old counters cleaned up.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select

from app.api.quota import QuestionQuota, QuotaExceeded
from app.db.app_tables import app_metadata, usage_counters


@pytest.fixture
def engine():
    e = create_engine("sqlite://")
    app_metadata.create_all(e)
    return e


def quota(engine, minute=0, user=0, guest=0, site=0):
    return QuestionQuota(engine, minute, user, guest, site)


def counts(engine):
    with engine.connect() as conn:
        return {r.key: r.count for r in conn.execute(select(usage_counters))}


AT = datetime(2026, 11, 13, 10, 0, 30, tzinfo=UTC)  # 15:30:30 in India


def test_disabled_limits_count_nothing(engine):
    t = quota(engine).reserve("g:1.2.3.4", signed_in=False, now=AT)
    assert t.left_today is None and counts(engine) == {}


def test_daily_guest_limit_and_rejections_are_not_counted(engine):
    q = quota(engine, guest=2)
    assert q.reserve("g:ip", False, now=AT).left_today == 1
    assert q.reserve("g:ip", False, now=AT).left_today == 0
    with pytest.raises(QuotaExceeded) as e:
        q.reserve("g:ip", False, now=AT)
    assert e.value.code == "daily_guest"
    assert e.value.retry_after == 8 * 3600 + 29 * 60 + 31  # to midnight India time, rounded up
    assert counts(engine) == {"d:g:ip:2026-11-13": 2}  # the rejected one rolled back
    assert q.reserve("g:other-ip", False, now=AT).left_today == 1  # another guest is separate


def test_minute_limit_resets_next_minute(engine):
    q = quota(engine, minute=1)
    q.reserve("u:a", True, now=AT)
    with pytest.raises(QuotaExceeded) as e:
        q.reserve("u:a", True, now=AT)
    assert e.value.code == "rate_minute" and e.value.retry_after == 30
    q.reserve("u:a", True, now=AT.replace(minute=1))


def test_site_limit_covers_everyone(engine):
    q = quota(engine, user=10, guest=10, site=2)
    q.reserve("u:a", True, now=AT)
    q.reserve("g:ip", False, now=AT)
    with pytest.raises(QuotaExceeded) as e:
        q.reserve("u:b", True, now=AT)
    assert e.value.code == "daily_site"


def test_day_follows_india_time(engine):
    q = quota(engine, user=1)
    q.reserve("u:a", True, now=datetime(2026, 11, 13, 18, 29, tzinfo=UTC))  # 23:59 IST on the 13th
    q.reserve("u:a", True, now=datetime(2026, 11, 13, 18, 31, tzinfo=UTC))  # 00:01 IST on the 14th
    assert set(counts(engine)) == {"d:u:a:2026-11-13", "d:u:a:2026-11-14"}


def test_refund_and_cleanup(engine):
    q = quota(engine, user=1, site=5)
    t = q.reserve("u:a", True, now=datetime(2026, 11, 12, 9, tzinfo=UTC))
    q.refund(t)
    assert counts(engine)["d:u:a:2026-11-12"] == 0
    q.reserve("u:a", True, now=AT)  # first question on a new day removes older counters
    assert all("2026-11-12" not in k for k in counts(engine))
