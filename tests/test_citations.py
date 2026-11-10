"""Unit tests for the pure citation-series logic (no network).

Run with: .venv/bin/python -m unittest discover -s tests
"""

import unittest
from datetime import date

from openalex_cli.citations import (
    bucket_key,
    build_profile,
    cites_per_month,
    series_str,
)
from openalex_cli.s2 import bare_doi, normalize_title

TODAY = date(2026, 11, 10)


class BucketKeyTest(unittest.TestCase):
    def test_buckets(self):
        d = date(2026, 5, 7)
        self.assertEqual(bucket_key(d, "day"), "2026-05-07")
        self.assertEqual(bucket_key(d, "week"), "2026-W19")
        self.assertEqual(bucket_key(d, "month"), "2026-05")

    def test_iso_week_uses_iso_year(self):
        # 2027-01-01 belongs to ISO week 53 of 2026.
        self.assertEqual(bucket_key(date(2027, 1, 1), "week"), "2026-W53")

    def test_unknown_bucket(self):
        with self.assertRaises(ValueError):
            bucket_key(TODAY, "quarter")


class BuildProfileTest(unittest.TestCase):
    def test_windows_and_quality_counts(self):
        dates = [
            "2026-11-10",  # today -> last 30d and 90d
            "2026-10-20",  # 21 days ago -> last 30d and 90d
            "2026-09-01",  # 70 days ago -> last 90d only
            "2026-08-12",  # exactly 90 days ago -> previous window
            "2026-06-15",  # previous 90d
            "2026-02-03",  # older than 180 days
            "2026-01-01",  # placeholder
            "2027-03-01",  # future
            None,  # undated
            "not-a-date",  # undated
        ]
        p = build_profile(dates, TODAY, "month")
        self.assertEqual(p.n_citing, 10)
        self.assertEqual(p.n_dated, 6)
        self.assertEqual(p.n_placeholder, 1)
        self.assertEqual(p.n_future, 1)
        self.assertEqual(p.n_undated, 2)
        self.assertEqual(p.last_30d, 2)
        self.assertEqual(p.last_90d, 3)
        self.assertEqual(p.prev_90d, 2)
        self.assertAlmostEqual(p.acceleration, 1.5)
        self.assertEqual(p.first_citation, "2026-02-03")
        self.assertEqual(
            p.series,
            {
                "2026-02": 1,
                "2026-06": 1,
                "2026-08": 1,
                "2026-09": 1,
                "2026-10": 1,
                "2026-11": 1,
            },
        )

    def test_no_baseline_means_no_acceleration(self):
        p = build_profile(["2026-11-01"], TODAY)
        self.assertEqual(p.prev_90d, 0)
        self.assertIsNone(p.acceleration)

    def test_empty(self):
        p = build_profile([], TODAY)
        self.assertEqual(p.n_citing, 0)
        self.assertIsNone(p.first_citation)
        self.assertEqual(p.series, {})


class RateTest(unittest.TestCase):
    def test_cites_per_month(self):
        # 2026-02-09 -> 2026-11-10 is 274 days = ~9.0 months.
        rate = cites_per_month(90, date(2026, 2, 9), TODAY)
        self.assertAlmostEqual(rate, 90 / (274 / 30.44))

    def test_age_floor_and_missing(self):
        self.assertEqual(cites_per_month(5, date(2026, 11, 5), TODAY), 5.0)
        self.assertIsNone(cites_per_month(5, None, TODAY))
        self.assertIsNone(cites_per_month(5, date(2027, 1, 1), TODAY))

    def test_series_str(self):
        self.assertEqual(series_str({"2026-05": 15, "2026-06": 8}), "2026-05=15;2026-06=8")


class S2HelpersTest(unittest.TestCase):
    def test_normalize_title(self):
        self.assertEqual(
            normalize_title("WorldArena: A unified benchmark"),
            normalize_title("WorldArena - A Unified Benchmark."),
        )

    def test_bare_doi(self):
        self.assertEqual(bare_doi("https://doi.org/10.1/abc"), "10.1/abc")
        self.assertEqual(bare_doi("10.1/abc"), "10.1/abc")
        self.assertIsNone(bare_doi(None))


if __name__ == "__main__":
    unittest.main()
