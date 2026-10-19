"""Pricing regressions: transitions, midnight, repeats, overlaps and missing rates."""
from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py'))
from parking_fees import calculate_turn_fee


def rate(identifier, name, start, end, amount):
    return dict(period_id=identifier, period_name=name, start=start, end=end, amount=amount)


class ParkingFeeTests(unittest.TestCase):
    def setUp(self):
        self.prices = [rate(1, 'Đêm', '00:00', '04:59', 300000),
                       rate(2, 'Sáng', '05:00', '12:59', 150000),
                       rate(3, 'Chiều', '13:00', '16:59', 150000),
                       rate(4, 'Tối', '17:00', '23:59', 250000)]

    def fee(self, entry, exit, prices=None):
        return calculate_turn_fee(self.prices if prices is None else prices,
                                  datetime.fromisoformat(entry), datetime.fromisoformat(exit), 5000)

    def test_reported_morning_to_afternoon_case_adds_both_rates(self):
        fee, note = self.fee('2026-10-19 11:37:47', '2026-10-19 16:13:49')
        self.assertEqual(fee, 300000)
        self.assertIn('Sáng', note)
        self.assertIn('Chiều', note)
        self.assertIn('= 300.000đ', note)

    def test_one_window_is_not_charged_repeatedly(self):
        self.assertEqual(self.fee('2026-10-19 05:01', '2026-10-19 12:59:59')[0], 150000)

    def test_end_minute_includes_its_seconds(self):
        self.assertEqual(self.fee('2026-10-19 12:59:01', '2026-10-19 12:59:59.999999')[0], 150000)

    def test_new_window_is_added_at_exact_start_time(self):
        self.assertEqual(self.fee('2026-10-19 12:59:59', '2026-10-19 13:00:00')[0], 300000)

    def test_entry_at_boundary_only_charges_new_window(self):
        self.assertEqual(self.fee('2026-10-19 13:00:00', '2026-10-19 16:00')[0], 150000)

    def test_every_intermediate_window_is_added(self):
        self.assertEqual(self.fee('2026-10-19 11:00', '2026-10-19 22:00')[0], 550000)

    def test_crossing_midnight_adds_separate_night_price(self):
        self.assertEqual(self.fee('2026-10-19 23:30', '2026-10-20 02:00')[0], 550000)

    def test_multiday_stay_counts_each_daily_occurrence(self):
        fee, note = self.fee('2026-10-19 11:37', '2026-10-20 11:37')
        self.assertEqual(fee, 1000000)
        self.assertIn('Sáng (05:00–12:59) × 2', note)

    def test_single_overnight_window_is_not_charged_twice_at_midnight(self):
        prices = [rate(1, 'Qua đêm', '22:00', '04:59', 30000),
                  rate(2, 'Ngày', '05:00', '21:59', 15000)]
        self.assertEqual(self.fee('2026-10-19 23:30', '2026-10-20 02:00', prices)[0], 30000)
        self.assertEqual(self.fee('2026-10-19 23:30', '2026-10-20 05:00', prices)[0], 45000)

    def test_next_night_is_a_new_occurrence(self):
        prices = [rate(1, 'Qua đêm', '22:00', '04:59', 30000),
                  rate(2, 'Ngày', '05:00', '21:59', 15000)]
        self.assertEqual(self.fee('2026-10-19 23:30', '2026-10-20 23:30', prices)[0], 75000)

    def test_all_day_window_repeats_on_next_date(self):
        prices = [rate(1, 'Cả ngày', '00:00', '23:59', 7000)]
        self.assertEqual(self.fee('2026-10-19 23:59', '2026-10-20 00:00', prices)[0], 14000)

    def test_first_created_window_wins_overlaps(self):
        prices = [rate(2, 'Sau', '11:00', '15:59', 990000),
                  rate(1, 'Trước', '05:00', '16:59', 150000)]
        self.assertEqual(self.fee('2026-10-19 11:00', '2026-10-19 15:30', prices)[0], 150000)

    def test_window_interrupted_by_priority_overlap_is_only_charged_once(self):
        prices = [rate(1, 'Cao điểm', '08:00', '08:59', 10000),
                  rate(2, 'Cả ngày', '00:00', '23:59', 5000)]
        self.assertEqual(self.fee('2026-10-19 07:30', '2026-10-19 09:30', prices)[0], 15000)

    def test_missing_window_adds_hourly_fallback_to_known_price(self):
        fee, note = self.fee('2026-10-19 16:30', '2026-10-19 18:01', self.prices[:3])
        self.assertEqual(fee, 160000)  # 150000 afternoon + ceil(61/60) * 5000
        self.assertIn('dự phòng', note)

    def test_missing_prices_keep_hourly_minimum_and_rounding(self):
        self.assertEqual(self.fee('2026-10-19 11:00', '2026-10-19 11:00', [])[0], 5000)
        self.assertEqual(self.fee('2026-10-19 11:00', '2026-10-19 12:00', [])[0], 5000)
        self.assertEqual(self.fee('2026-10-19 11:00', '2026-10-19 12:00:01', [])[0], 10000)

    def test_free_price_is_a_valid_price_not_an_hourly_fallback(self):
        self.assertEqual(self.fee('2026-10-19 11:00', '2026-10-19 12:00',
                                  [rate(1, 'Miễn phí', '00:00', '23:59', 0)])[0], 0)

    def test_zero_length_stay_with_price_charges_active_window(self):
        self.assertEqual(self.fee('2026-10-19 13:00', '2026-10-19 13:00')[0], 150000)
