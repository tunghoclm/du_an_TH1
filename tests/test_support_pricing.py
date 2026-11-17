"""Natural-language fee estimates match checkout, with explicit missing-information prompts."""
from datetime import datetime
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_gate
import database
import support_pricing


class SupportPricingTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)
    setUp = test_gate.GateTests.setUp
    park = test_gate.GateTests.park
    set_car_prices_and_entry = test_gate.GateTests.set_car_prices_and_entry

    def post(self, text, client=None, path='/ai/test'):
        client = client or self.client
        token = client.get('/api/support/bootstrap').json['csrf_token']
        return client.post('/api/support' + path, json=dict(text=text, client_id=str(uuid4())),
                           headers={'X-Support-CSRF': token})

    def test_original_question_understands_21_hours_and_asks_vehicle_type(self):
        result = self.post('gửi xe từ 1h sáng đến 10h đêm hết bao nhiêu').json
        self.assertEqual(result['intent'], 'parking_fee')
        self.assertFalse(result['matched'])
        self.assertIn('01:00–22:00', result['answer'])
        self.assertIn('21 giờ', result['answer'])
        self.assertIn('loại xe nào', result['answer'])
        self.assertNotIn('data', result)

    def test_time_formats_and_nighttime_are_interpreted_consistently(self):
        for text, expected in (
            ('từ 1h sáng đến 10h đêm', (60, 1320)), ('tu 1 gio sang den 10 gio toi', (60, 1320)),
            ('01:00–22:00', (60, 1320)), ('1h30 sáng tới 10h15 tối', (90, 1335)),
            ('từ 10h tối đến 1h sáng', (1320, 1500)), ('từ 10h đêm đến 12h đêm', (1320, 1440)),
            ('từ 12h trưa đến 1h chiều', (720, 780)), ('1am đến 10pm', (60, 1320)),
            ('từ 1h sáng đến 10h đêm hôm sau', (60, 2760))):
            with self.subTest(text=text):
                self.assertEqual(support_pricing.parse_interval(text), expected)

    def test_explicit_type_uses_all_applicable_windows_and_matches_actual_checkout(self):
        self.set_car_prices_and_entry(datetime(2026, 11, 11, 1))
        response = self.post('gửi xe kiểm thử từ 1h sáng đến 10h đêm hết bao nhiêu')
        self.assertEqual(response.status_code, 200)
        result = response.json
        self.assertTrue(result['matched'])
        self.assertEqual(result['data']['duration_minutes'], 1260)
        self.assertEqual(result['data']['amount'], 850000)
        record = database.find_open_record('51F-12345')
        actual, _, _ = self.module.calc_fee(record, datetime(2026, 11, 11, 22))
        self.assertEqual(result['data']['amount'], actual)
        for window in ('Đêm', 'Sáng', 'Chiều', 'Tối'):
            self.assertIn(window, result['answer'])

    def test_customer_can_reply_with_vehicle_type_without_repeating_time(self):
        user_id = database.add_user('fee-customer', 'Customer', 'secret-password', 'user')
        customer = self.app.test_client()
        with customer.session_transaction() as session:
            session['user_id'] = user_id
        first = self.post('gửi xe từ 1h sáng đến 10h đêm hết bao nhiêu', customer, '/ai/messages')
        self.assertIn('loại xe nào', first.json['messages'][-1]['text'])
        second = self.post('Xe máy', customer, '/ai/messages')
        self.assertEqual(second.status_code, 200)
        self.assertIn('Ước tính phí gửi Xe máy', second.json['messages'][-1]['text'])
        self.assertIn('01:00–22:00', second.json['messages'][-1]['text'])
        self.assertEqual(self.client.get('/api/support/ai/history').json['messages'], [])

    def test_missing_times_can_be_provided_in_followup_and_unrelated_text_is_not_hijacked(self):
        first = support_pricing.answer('Tính phí gửi xe máy hết bao nhiêu?')
        history = [dict(user_text='Tính phí gửi xe máy hết bao nhiêu?', answer=first['answer'])]
        second = support_pricing.answer('từ 1h sáng đến 10h đêm', history)
        self.assertTrue(second['matched'])
        self.assertEqual(second['data']['duration_minutes'], 1260)
        resumed = support_pricing.answer('Ô tô thì sao', history + [dict(user_text='từ 1h sáng đến 10h đêm', answer=second['answer'])])
        self.assertTrue(resumed['matched'])
        self.assertEqual(resumed['data']['vehicle_type'], 'Ô tô')
        self.assertIsNone(support_pricing.answer('Thời tiết hôm nay', history))
        quote_history = [dict(user_text='gửi xe máy từ 1h đến 22h hết bao nhiêu', answer=second['answer'])]
        fresh = support_pricing.answer('gửi xe máy từ 2h đến 3h hết bao nhiêu', quote_history)
        self.assertEqual(fresh['data']['duration_minutes'], 60)
        self.assertIsNone(support_pricing.answer('Xem lịch sử', quote_history))
        for question in ('Tôi có chỗ gửi xe không?', 'Bãi còn bao nhiêu chỗ gửi xe?', 'Bãi xe còn đang trống bao nhiêu?'):
            self.assertIsNone(support_pricing.answer(question, quote_history))

    def test_block_prices_free_minutes_cap_and_overnight_match_checkout_algorithm(self):
        database.save_vehicle_type(self.type_id, 'Xe kiểm thử', first_block_hours=2,
                                   first_block_amount=30000, next_hour_amount=10000, daily_cap=150000, free_minutes=10)
        for hours, expected in (('1h sáng đến 10h đêm', 150000), ('22h đến 1h sáng', 40000),
                                ('1h đến 1h10', 0)):
            result = self.post('gửi xe kiểm thử từ ' + hours + ' hết bao nhiêu').json
            self.assertTrue(result['matched'])
            self.assertEqual(result['data']['amount'], expected)

    def test_missing_prices_are_explicit_fallback_and_prices_refresh_on_every_request(self):
        for price in database.get_prices():
            if price['vehicle_type_id'] == self.type_id:
                database.delete_price(price['id'])
        question = 'gửi xe kiểm thử từ 01:00 đến 22:00 hết bao nhiêu'
        result = self.post(question).json
        self.assertEqual(result['data']['amount'], 105000)
        self.assertIn('dự phòng', result['answer'])
        period = next(p for p in database.get_periods() if p['name'] == 'Cả ngày kiểm thử')
        database.save_price(None, self.type_id, period['id'], 9000, 'turn')
        self.assertEqual(self.post(question).json['data']['amount'], 9000)

    def test_invalid_times_duration_only_and_monthly_tickets_do_not_produce_guessed_amounts(self):
        for question in ('gửi xe máy từ 25h đến 22h hết bao nhiêu', 'gửi xe máy từ 1h90 đến 22h hết bao nhiêu',
                         'gửi xe máy 21 tiếng hết bao nhiêu', 'gửi xe máy từ 1 đến 10 hết bao nhiêu',
                         'gửi xe máy từ 1h ngày 11/11 đến 22h ngày 13/11 hết bao nhiêu',
                         'gửi xe máy có vé tháng từ 1h sáng đến 10h đêm hết bao nhiêu'):
            with self.subTest(question=question):
                result = self.post(question).json
                self.assertFalse(result['matched'])
                self.assertNotIn('data', result)

    def test_read_only_no_network_no_private_records_and_sanitized_database_errors(self):
        with patch('socket.socket.connect', side_effect=AssertionError('No external AI')):
            result = self.post('gửi xe kiểm thử từ 1h đến 22h hết bao nhiêu')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(database.count_open(), 0)
        self.assertNotIn('secret-password', result.text)
        with patch.object(support_pricing, '_read_pricing', side_effect=sqlite3.OperationalError('private database detail')):
            result = self.post('gửi xe từ 1h sáng đến 10h đêm hết bao nhiêu')
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('private database detail', result.text)


if __name__ == '__main__':
    unittest.main()
