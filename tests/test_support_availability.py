"""Live aggregate availability in private local chat, using isolated databases."""
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_gate
import database
import support_knowledge
import support_live


class AvailabilityTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)
    setUp = test_gate.GateTests.setUp

    def post(self, text, client=None, path='/ai/test'):
        client = client or self.client
        token = client.get('/api/support/bootstrap').json['csrf_token']
        return client.post('/api/support' + path, json=dict(text=text, client_id=str(uuid4())),
                           headers={'X-Support-CSRF': token})

    def test_original_question_counts_only_usable_slots_and_exposes_no_vehicle_data(self):
        database.occupy_slot('A01', 'PRIVATE-PLATE-ONE')
        database.set_slot_maintenance('A02', True, 'Private maintenance note')
        database.add_entry_record('PRIVATE-PLATE-TWO', 'private-photo.jpg', 'A03')
        response = self.post('bãi xe còn đang trống bao nhiêu')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['matched'])
        self.assertEqual(response.json['source'], 'parking_data')
        self.assertIsNone(response.json['confidence'])
        self.assertEqual({key: response.json['data'][key] for key in ('total', 'available', 'occupied', 'maintenance')},
                         dict(total=18, available=15, occupied=2, maintenance=1))
        self.assertIn('15/18', response.json['answer'])
        self.assertIn('UTC+7', response.json['answer'])
        for secret in ('PRIVATE-PLATE', 'private-photo', 'Private maintenance note', 'password'):
            self.assertNotIn(secret, response.text)

    def test_natural_phrasings_work_with_or_without_accents_without_training(self):
        for question in ('bai xe con dang trong bao nhieu', 'Bãi xe còn bao nhiêu chỗ?', 'Còn mấy chỗ đỗ?',
                         'Bãi còn chỗ không?', 'Bãi đầy chưa?', 'Có chỗ gửi xe không?', 'Số chỗ đỗ còn lại',
                         'Bãi xe còn trống không?', 'Còn bao nhiêu ô đỗ trống?', 'chỗ trống', 'Bãi xe có bao nhiêu chỗ?'):
            with self.subTest(question=question):
                response = self.post(question)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['source'], 'parking_data')
                self.assertTrue(response.json['matched'])
                self.assertEqual(response.json['data']['available'], 18)
        self.assertFalse(support_knowledge.status()['needs_training'])
        self.assertEqual(self.client.get('/api/support/ai/history').json['messages'], [])

    def test_counts_refresh_after_entry_and_exit_and_customer_chat_can_read_aggregates(self):
        user_id = database.add_user('availability-user', 'Customer', 'private-password', 'user')
        customer = self.app.test_client()
        with customer.session_transaction() as session:
            session['user_id'] = user_id
        with patch('socket.socket.connect', side_effect=AssertionError('No network')):
            first = self.post('bãi xe còn đang trống bao nhiêu', customer, '/ai/messages')
            self.assertEqual(first.status_code, 200)
            self.assertIn('18/18', first.json['messages'][-1]['text'])
            database.occupy_slot('A01', 'PRIVATE-PLATE')
            second = self.post('bãi xe còn đang trống bao nhiêu', customer, '/ai/messages')
            self.assertIn('17/18', second.json['messages'][-1]['text'])
            database.free_slot('A01')
            third = self.post('bãi xe còn đang trống bao nhiêu', customer, '/ai/messages')
            self.assertIn('18/18', third.json['messages'][-1]['text'])
        self.assertEqual(self.client.get('/api/support/ai/history').json['messages'], [])

    def test_area_and_vehicle_type_filters_respect_restrictions_and_unknown_areas_clarify(self):
        area_a = next(area for area in database.get_areas() if area['name'] == 'A')
        area_b = next(area for area in database.get_areas() if area['name'] == 'B')
        motorcycle = next(item for item in database.get_vehicle_types() if item['name'] == 'Xe máy')
        car = next(item for item in database.get_vehicle_types() if item['name'] == 'Ô tô')
        database.save_area(area_a['id'], 'A', motorcycle['id'])
        database.save_area(area_b['id'], 'B', car['id'])
        database.occupy_slot('A01', 'PRIVATE-PLATE')
        self.assertEqual(self.post('Còn mấy chỗ đỗ?').json['data']['available'], 17)
        self.assertEqual(self.post('Khu A còn trống bao nhiêu?').json['data']['available'], 5)
        self.assertEqual(self.post('Bãi còn chỗ cho xe máy không?').json['data']['available'], 11)
        self.assertEqual(self.post('Bãi còn chỗ cho oto không?').json['data']['available'], 12)
        self.assertEqual(self.post('Khu A còn chỗ cho ô tô không?').json['data']['total'], 0)
        for question in ('Khu Z còn chỗ không?', 'Khu A và khu B còn trống bao nhiêu?', 'Bãi còn chỗ cho xe máy và ô tô không?'):
            result = self.post(question).json
            self.assertFalse(result['matched'])
            self.assertNotIn('data', result)
        database.save_area(None, 'Tầng hầm', slot_count=2)
        self.assertEqual(self.post('Tầng hầm còn trống bao nhiêu?').json['data']['available'], 2)

    def test_empty_lot_and_full_lot_report_zero_without_inventing_capacity(self):
        with support_knowledge.connection(write=True) as conn:
            conn.execute("UPDATE parking_slots SET status='maintenance'")
        result = self.post('Bãi còn trống bao nhiêu?').json
        self.assertEqual(result['data']['available'], 0)
        self.assertIn('không còn ô đỗ trống', result['answer'])
        with support_knowledge.connection(write=True) as conn:
            conn.execute('DELETE FROM parking_slots')
        result = self.post('Bãi còn trống bao nhiêu?').json
        self.assertEqual(result['data']['total'], 0)
        self.assertIn('chưa có ô đỗ', result['answer'])

    def test_live_lookup_is_read_only_and_database_failures_are_not_faked(self):
        statements = []
        original = database.get_connection
        def capture():
            connection = original()
            connection.set_trace_callback(statements.append)
            return connection
        with patch.object(database, 'get_connection', side_effect=capture):
            result = support_live.answer('Bãi xe còn trống bao nhiêu?')
        self.assertEqual(result['data']['available'], 18)
        self.assertIn('PRAGMA query_only=ON', statements)
        self.assertFalse(any(sql.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ')) for sql in statements))
        with support_knowledge.connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM support_ai_turns').fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM parking_slots WHERE status='available'").fetchone()[0], 18)
        with patch.object(support_live, '_read_snapshot', side_effect=sqlite3.OperationalError('private database detail')):
            response = self.post('Bãi xe còn trống bao nhiêu?')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private database detail', response.text)

    def test_guests_locked_accounts_and_disabled_assistant_cannot_use_lookup(self):
        guest = self.app.test_client()
        with patch.object(support_live, '_read_snapshot') as lookup:
            self.assertEqual(guest.post('/api/support/ai/messages', json={}).status_code, 401)
            support_knowledge.settings(dict(support_knowledge.status(), enabled=False))
            self.assertEqual(self.post('Bãi còn chỗ không?', path='/ai/messages').status_code, 503)
            database.toggle_user_status(1)
            self.assertEqual(self.client.post('/api/support/ai/messages', json={}).status_code, 401)
            lookup.assert_not_called()

    def test_future_questions_and_unrelated_or_mutating_requests_do_not_return_current_counts(self):
        for question in ('Ngày mai bãi còn bao nhiêu chỗ?', 'Bãi còn bao nhiêu chỗ lúc 18h?', 'Hôm qua bãi còn bao nhiêu chỗ?'):
            result = self.post(question).json
            self.assertFalse(result['matched'])
            self.assertNotIn('data', result)
        for question in ('Thời tiết hôm nay', 'Máy chủ còn trống bao nhiêu?', 'Bãi đầy phải làm gì?',
                         'Xóa tất cả ô đỗ trống', 'Bảng giá bao nhiêu tiền?', 'Xe tôi ở đâu?'):
            self.assertIsNone(support_live.answer(question))


if __name__ == '__main__':
    unittest.main()
