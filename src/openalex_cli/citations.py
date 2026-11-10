"""Citation time series built from the publication dates of citing works.

OpenAlex's `counts_by_year` is yearly, too coarse to see a paper accelerating.
The works returned by the `cites:<id>` filter each carry a `publication_date`,
which gives a per-day series. This module holds the pure logic (no network).

Date quality caveats, handled here:
  - `YYYY-01-01` is the placeholder OpenAlex uses when only the year is known;
    those are counted apart and kept out of the series and the recent windows.
  - A first-of-month day is often a month-only date, so day/week buckets are
    noisier than month buckets.
  - Citing works dated in the future (journal issue dates) are counted apart.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

BUCKETS = ("day", "week", "month")

# Mean month length in days, to express a rate as citations per month.
DAYS_PER_MONTH = 30.44


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def is_placeholder(d: date) -> bool:
    """January 1st: almost always a year-only date rather than a real one."""
    return d.month == 1 and d.day == 1


def bucket_key(d: date, bucket: str) -> str:
    if bucket == "day":
        return d.isoformat()
    if bucket == "week":
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if bucket == "month":
        return f"{d.year}-{d.month:02d}"
    raise ValueError(f"Unknown bucket: {bucket}")


@dataclass
class CitationProfile:
    """Dated citation summary for one work."""

    n_citing: int  # citing works fetched
    n_dated: int  # with a usable date (in the series)
    n_placeholder: int  # dated YYYY-01-01
    n_undated: int
    n_future: int  # dated after `today`
    last_30d: int
    last_90d: int
    prev_90d: int  # the 90 days before the last 90
    first_citation: str | None
    series: dict[str, int] = field(default_factory=dict)  # bucket -> citations

    @property
    def acceleration(self) -> float | None:
        """Last 90 days over the previous 90; None when there is no baseline."""
        if not self.prev_90d:
            return None
        return self.last_90d / self.prev_90d


def build_profile(
    dates: list[str | None], today: date, bucket: str = "month"
) -> CitationProfile:
    """Summarize the publication dates of the works citing one paper."""
    if bucket not in BUCKETS:
        raise ValueError(f"Unknown bucket: {bucket}")

    usable: list[date] = []
    n_placeholder = n_undated = n_future = 0
    for raw in dates:
        d = parse_date(raw)
        if d is None:
            n_undated += 1
        elif d > today:
            n_future += 1
        elif is_placeholder(d):
            n_placeholder += 1
        else:
            usable.append(d)

    def _window(start_days: int, end_days: int) -> int:
        # Citations with today - start_days < date <= today - end_days.
        lo = today - timedelta(days=start_days)
        hi = today - timedelta(days=end_days)
        return sum(1 for d in usable if lo < d <= hi)

    counts = Counter(bucket_key(d, bucket) for d in usable)
    return CitationProfile(
        n_citing=len(dates),
        n_dated=len(usable),
        n_placeholder=n_placeholder,
        n_undated=n_undated,
        n_future=n_future,
        last_30d=_window(30, 0),
        last_90d=_window(90, 0),
        prev_90d=_window(180, 90),
        first_citation=min(usable).isoformat() if usable else None,
        series=dict(sorted(counts.items())),
    )


def cites_per_month(n_citations: int, published: date | None, today: date) -> float | None:
    """Average citations per month since publication (age floored at one month)."""
    if published is None or published > today:
        return None
    months = max((today - published).days / DAYS_PER_MONTH, 1.0)
    return n_citations / months


def series_str(series: dict[str, int]) -> str:
    """Compact series for CSV: '2026-05=15;2026-06=8'."""
    return ";".join(f"{k}={v}" for k, v in series.items())
