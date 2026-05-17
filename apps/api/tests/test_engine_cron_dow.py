"""Convention bridge between POSIX cron and APScheduler day_of_week.

Pinning down :func:`_posix_cron_to_apscheduler` so the silent-Sunday-shift
bug (5+ weeks of missed Trading-LoRA fires before the 2026-05-17 audit
caught it) can't regress.

POSIX cron:        0 = Sunday, 6 = Saturday
APScheduler:       0 = Monday, 6 = Sunday
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

apscheduler = pytest.importorskip("apscheduler")
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from services.automation_engine.engine import _posix_cron_to_apscheduler  # noqa: E402


# ── Pure-translator tests (no scheduler in the loop) ──────────────────


def test_sunday_zero_becomes_six():
    """POSIX `0` (Sun) → APScheduler `6` (Sun)."""
    assert _posix_cron_to_apscheduler("0 18 * * 0") == "0 18 * * 6"


def test_sunday_seven_also_becomes_six():
    """POSIX accepts `7` as Sunday too — same target."""
    assert _posix_cron_to_apscheduler("0 18 * * 7") == "0 18 * * 6"


def test_weekday_offsets():
    """POSIX 1..6 (Mon..Sat) shift down by one."""
    for posix_dow, ap_dow in [("1", "0"), ("2", "1"), ("3", "2"),
                              ("4", "3"), ("5", "4"), ("6", "5")]:
        assert _posix_cron_to_apscheduler(f"0 0 * * {posix_dow}") \
            == f"0 0 * * {ap_dow}"


def test_star_passes_through():
    """Wildcard isn't day-specific — must not be touched."""
    assert _posix_cron_to_apscheduler("*/15 * * * *") == "*/15 * * * *"


def test_named_days_pass_through():
    """APScheduler interprets named days the POSIX way already."""
    assert _posix_cron_to_apscheduler("0 18 * * sun") == "0 18 * * sun"
    assert _posix_cron_to_apscheduler("0 18 * * mon-fri") == "0 18 * * mon-fri"


def test_range_translates_both_endpoints():
    """`1-5` (Mon..Fri POSIX) → `0-4` (Mon..Fri APScheduler)."""
    assert _posix_cron_to_apscheduler("0 9 * * 1-5") == "0 9 * * 0-4"


def test_range_crossing_sunday():
    """`6-0` (Sat..Sun POSIX) — endpoints must each translate."""
    # 6 (Sat) → 5, 0 (Sun) → 6
    assert _posix_cron_to_apscheduler("0 0 * * 6-0") == "0 0 * * 5-6"


def test_list_translates_each_entry():
    """Comma-separated POSIX days each translate independently."""
    # 0 (Sun)=6, 3 (Wed)=2, 5 (Fri)=4
    assert _posix_cron_to_apscheduler("0 0 * * 0,3,5") == "0 0 * * 6,2,4"


def test_step_passes_through():
    """`*/2` means every-Nth-day; identical semantics under either convention."""
    assert _posix_cron_to_apscheduler("0 0 * * */2") == "0 0 * * */2"


def test_six_field_expression_unchanged():
    """Don't touch APScheduler-native 6-field (with seconds) input."""
    assert _posix_cron_to_apscheduler("0 0 18 * * 0") == "0 0 18 * * 0"


def test_garbage_returns_original():
    """Parse-failure path must not silently mangle the input."""
    assert _posix_cron_to_apscheduler("not a cron") == "not a cron"


def test_only_dow_field_changes():
    """Minute/hour/day-of-month/month fields must be untouched even when
    they contain digit literals that look like dow tokens."""
    assert _posix_cron_to_apscheduler("0 0 5 5 0") == "0 0 5 5 6"


# ── End-to-end tests: feed the translated string into APScheduler and
#   confirm the next fire lands on the intended POSIX weekday. ────────


def _next_weekday(expr: str) -> str:
    """Apply the bridge and ask APScheduler for the next fire's weekday."""
    trig = CronTrigger.from_crontab(_posix_cron_to_apscheduler(expr))
    # Anchor on a fixed UTC Sunday so the test is deterministic.
    anchor = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)  # Sunday 12:00 UTC
    nxt = trig.get_next_fire_time(None, anchor)
    return nxt.strftime("%A")


def test_e2e_posix_sunday_fires_on_sunday():
    """`0 18 * * 0` (POSIX Sunday) must fire on a Sunday end-to-end."""
    assert _next_weekday("0 18 * * 0") == "Sunday"


def test_e2e_posix_monday_fires_on_monday():
    assert _next_weekday("0 0 * * 1") == "Monday"


def test_e2e_posix_saturday_fires_on_saturday():
    assert _next_weekday("0 0 * * 6") == "Saturday"


def test_e2e_posix_friday_fires_on_friday():
    assert _next_weekday("0 0 * * 5") == "Friday"
