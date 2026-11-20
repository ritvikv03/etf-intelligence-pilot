"""Reporting windows [B, E) in the report timezone, converted to UTC; calendar-aware lookbacks."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LOOKBACKS = ["last_run", "daily", "weekly", "monthly", "quarterly", "semiannually", "annually",
             "3_year", "5_year", "10_year", "full_history", "custom"]
_MONTHS = {"monthly": 1, "quarterly": 3, "semiannually": 6, "annually": 12, "3_year": 36, "5_year": 60, "10_year": 120}


def subtract_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) - months
    y, m = divmod(total, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def local_midnight_utc(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc)


@dataclass(frozen=True)
class Window:
    lookback: str
    start_local: date          # B (inclusive local date)
    end_local: date            # E (exclusive local date)
    start_utc: datetime
    end_utc: datetime
    baseline_date: date        # day before B's calendar date
    current_date: date         # day before E's calendar date
    timezone: str

    def contains_utc(self, iso: str) -> bool:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return self.start_utc <= t < self.end_utc


def make_window(lookback: str, end_date: date, tzname: str, start_date: date | None = None) -> Window:
    """end_date is the exclusive local end (the report's boundary day, at its start)."""
    if lookback in ("last_run", "full_history"):
        raise NotImplementedError(f"lookback '{lookback}' needs report checkpoints/full history (Milestone 4)")
    if lookback not in LOOKBACKS:
        raise ValueError(f"unknown lookback '{lookback}'; choose from {LOOKBACKS}")
    tz = ZoneInfo(tzname)
    if lookback == "custom":
        if start_date is None:
            raise ValueError("custom lookback requires a start date")
        start = start_date
    elif lookback == "daily":
        start = end_date - timedelta(days=1)
    elif lookback == "weekly":
        start = end_date - timedelta(days=7)
    else:
        start = subtract_months(end_date, _MONTHS[lookback])
    if start >= end_date:
        raise ValueError("window start must be before end")
    return Window(lookback, start, end_date, local_midnight_utc(start, tz), local_midnight_utc(end_date, tz),
                  start - timedelta(days=1), end_date - timedelta(days=1), tzname)
