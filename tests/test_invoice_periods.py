"""Calendar boundaries for the invoice period picker, including lunar leap months."""
from datetime import date, datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py'))
from invoice_periods import datetime_input, period_bounds


class InvoicePeriodTests(unittest.TestCase):
    def assert_period(self, key, today, first, following):
        start, end = period_bounds(key, date.fromisoformat(today))
        self.assertEqual((start, end), (datetime.fromisoformat(first), datetime.fromisoformat(following)))

    def test_quick_periods_use_full_calendar_boundaries(self):
        for key, first, following in (
            ('today', '2026-11-02', '2026-11-03'),
            ('yesterday', '2026-11-01', '2026-11-02'),
            ('week', '2026-11-02', '2026-11-09'),
            ('last_week', '2026-10-26', '2026-11-02'),
            ('7days', '2026-10-27', '2026-11-03'),
            ('month', '2026-11-01', '2026-12-01'),
            ('last_month', '2026-10-01', '2026-11-01'),
            ('30days', '2026-10-04', '2026-11-03'),
            ('quarter', '2026-10-01', '2027-01-01'),
            ('last_quarter', '2026-07-01', '2026-10-01'),
            ('year', '2026-01-01', '2027-01-01'),
            ('last_year', '2025-01-01', '2026-01-01'),
        ):
            with self.subTest(key=key):
                self.assert_period(key, '2026-11-02', first, following)

    def test_year_rollovers_and_leap_year_february(self):
        self.assert_period('week', '2026-01-01', '2025-12-29', '2026-01-05')
        self.assert_period('last_month', '2026-01-01', '2025-12-01', '2026-01-01')
        self.assert_period('last_quarter', '2026-01-01', '2025-10-01', '2026-01-01')
        self.assert_period('month', '2024-02-29', '2024-02-01', '2024-03-01')

    def test_lunar_year_switches_at_tet_instead_of_january_first(self):
        self.assert_period('lunar_year', '2026-02-16', '2025-01-29', '2026-02-17')
        self.assert_period('last_lunar_year', '2026-02-17', '2025-01-29', '2026-02-17')

    def test_lunar_leap_month_is_a_distinct_calendar_month(self):
        self.assert_period('lunar_month', '2025-08-05', '2025-07-25', '2025-08-23')
        self.assert_period('last_lunar_month', '2025-08-05', '2025-06-25', '2025-07-25')

    def test_custom_dates_and_datetimes_have_inclusive_end_boundaries(self):
        today = date(2026, 11, 2)
        self.assertEqual(period_bounds('custom', today, '2026-11-01', '2026-11-02'),
                         (datetime(2026, 11, 1), datetime(2026, 11, 3)))
        self.assertEqual(period_bounds('custom', today, '2026-11-02T08:30', '2026-11-02T09:45'),
                         (datetime(2026, 11, 2, 8, 30), datetime(2026, 11, 2, 9, 46)))

    def test_invalid_or_reversed_custom_ranges_are_rejected(self):
        for start, end in [('', ''), ('bad', '2026-11-02'), ('2026-11-03', '2026-11-02'),
                           ('2026-11-02T09:46', '2026-11-02T09:45')]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                period_bounds('custom', date(2026, 11, 2), start, end)

    def test_legacy_date_links_keep_the_complete_last_day_in_the_editor(self):
        self.assertEqual(datetime_input('2026-11-02', end=True), '2026-11-02T23:59')
        self.assertEqual(datetime_input('2026-11-02'), '2026-11-02T00:00')
        self.assertEqual(datetime_input('bad'), '')
