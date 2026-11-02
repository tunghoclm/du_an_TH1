"""Receipt scope, recorded totals, filtering, exports and ownership on isolated databases."""
import csv
from datetime import date, timedelta
from io import StringIO
import unittest
from unittest.mock import patch

import test_gate
import database
from plate_utils import plate_key


class InvoiceTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)
    setUp = test_gate.GateTests.setUp
    park = test_gate.GateTests.park
    recognize = test_gate.GateTests.recognize

    def receipt(self, plate='51F-12345', fee=15000, day=None, status='OUT', note=None):
        day = day or date.today().isoformat()
        record_id = database.add_entry_record(plate, None, 'A01', self.type_id, 'Xe kiểm thử', note)
        database._exec('UPDATE parking_records SET status=?,entry_time=?,exit_time=?,fee=? WHERE id=?',
                       (status, day + 'T08:00:00', day + 'T10:15:00', fee, record_id))
        return record_id

    def csv_rows(self, url='/invoices/export'):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return list(csv.reader(StringIO(response.data.decode('utf-8-sig'))))

    def test_only_completed_sessions_with_recorded_fees_become_receipts(self):
        paid = self.receipt()
        free = self.receipt('59A-10000', 0)
        for status, fee in [('IN', 100), ('DELETED', 100), ('OUT', None)]:
            self.receipt('30A-99999', fee, status=status)
        response = self.client.get('/invoices')
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'data-toggle-invoice="{paid}"', response.text)
        self.assertIn(f'data-toggle-invoice="{free}"', response.text)
        self.assertNotIn('30A-99999', response.text)
        rows = self.csv_rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(sorted(row[9] for row in rows[1:]), ['0', '15000'])

    def test_filters_use_exit_date_area_vehicle_and_normalized_plate(self):
        self.receipt(day='2026-11-02')
        self.receipt('59A-10000', 0, '2026-11-01')
        args = dict(q='51f12345', range='custom', **{'from': '2026-11-02', 'to': '2026-11-02'},
                    area='A', vehicle_type='Xe kiểm thử', fee='paid')
        context = self.module.parking_invoices.invoice_context(args, 'admin', 1)
        self.assertEqual(context['total_count'], 1)
        self.assertEqual(context['total_fee'], 15000)
        self.assertEqual(context['items'][0]['duration'], '2 giờ 15 phút')
        context = self.module.parking_invoices.invoice_context({'range': 'yesterday'}, 'admin', 1,
                                                             today=date(2026, 11, 2))
        self.assertEqual([r['plate_number'] for r in context['items']], ['59A-10000'])

    def test_custom_time_includes_the_last_second_of_the_selected_minute(self):
        included = self.receipt('51F-11111')
        excluded = self.receipt('51F-22222')
        database._exec('UPDATE parking_records SET exit_time=? WHERE id=?', ('2026-11-02T10:15:59', included))
        database._exec('UPDATE parking_records SET exit_time=? WHERE id=?', ('2026-11-02T10:16:00', excluded))
        query = 'range=custom&from=2026-11-02T10:15&to=2026-11-02T10:15'
        rows = self.csv_rows('/invoices/export?' + query)
        self.assertEqual([r[1] for r in rows[1:]], ['51F-11111'])

    def test_customer_cannot_read_print_or_export_other_vehicles_receipts(self):
        own = self.receipt('51F-12345')
        other = self.receipt('59A-99999', 99000)
        conn = database.get_connection()
        try:
            customer = conn.execute("INSERT INTO users(username,fullname,password,role) VALUES ('owner','Chủ xe','test','user')").lastrowid
            conn.commit()
        finally:
            conn.close()
        database.add_user_vehicle(customer, '51F-12345', plate_key('51F-12345'), self.type_id, 'turn', None)
        with self.client.session_transaction() as session:
            session.update(role='user', user_id=customer, username='owner')
        response = self.client.get('/invoices')
        self.assertIn('51F-12345', response.text)
        self.assertNotIn('59A-99999', response.text)
        self.assertEqual(self.client.get(f'/invoices/{own}/print').status_code, 200)
        self.assertEqual(self.client.get(f'/invoices/{other}/print').status_code, 404)
        self.assertEqual(len(self.csv_rows(f'/invoices/export?ids={other}')), 1)
        self.assertEqual(len(self.csv_rows()), 2)

    def test_pagination_totals_export_and_selection_keep_the_same_scope(self):
        ids = [self.receipt(f'51F-{10000 + i}', i * 1000) for i in range(25)]
        context = self.module.parking_invoices.invoice_context({'page': '2'}, 'admin', 1)
        self.assertEqual(len(context['items']), 5)
        self.assertEqual(context['total_fee'], sum(i * 1000 for i in range(25)))
        self.assertEqual(len(self.csv_rows('/invoices/export?page=2')), 26)
        rows = self.csv_rows(f'/invoices/export?ids={ids[0]},{ids[1]}')
        self.assertEqual(len(rows), 3)
        self.assertEqual(self.client.get('/invoices/export?ids=bad').status_code, 400)

    def test_invalid_dates_do_not_silently_export_a_different_period(self):
        self.receipt()
        query = 'range=custom&from=2026-11-03&to=2026-11-01'
        response = self.client.get('/invoices?' + query)
        self.assertIn('role="alert"', response.text)
        self.assertNotIn('data-toggle-invoice="', response.text)
        self.assertEqual(self.client.get('/invoices/export?' + query).status_code, 400)

    def test_recorded_amounts_are_not_repriced_and_unsafe_text_is_escaped(self):
        record_id = self.receipt(fee=12345, note='=SUM(1,2)<script>alert(1)</script>')
        with patch.object(self.module, 'calc_fee', side_effect=AssertionError('must not recalculate receipts')):
            response = self.client.get(f'/invoices/{record_id}/print')
            self.assertEqual(response.status_code, 200)
            self.assertIn('12.345 đ', response.text)
            self.assertNotIn('<script>', response.text)
            rows = self.csv_rows()
            self.assertEqual(rows[1][9], '12345')
            self.assertTrue(rows[1][-1].startswith("'=SUM"))

    def test_invoice_routes_require_authentication(self):
        self.client.get('/logout')
        for path in ('/invoices', '/invoices/export', '/invoices/1/print'):
            self.assertEqual(self.client.get(path).status_code, 302)

    def test_payment_filter_and_export_use_recorded_methods(self):
        known = {}
        for index, method in enumerate(database.PAYMENT_METHODS):
            record_id = self.receipt(f'51F-{30000 + index}', fee=(index + 1) * 10000)
            database._exec('UPDATE parking_records SET payment_method=? WHERE id=?', (method, record_id))
            known[method] = record_id
        legacy = self.receipt('51F-39999', fee=5000)
        for method, record_id in known.items():
            with self.subTest(method=method):
                context = self.module.parking_invoices.invoice_context({'payment_method': method}, 'admin', 1)
                self.assertEqual([r['id'] for r in context['items']], [record_id])
                self.assertNotIn(legacy, [r['id'] for r in context['items']])
                rows = self.csv_rows('/invoices/export?payment_method=' + method)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[1][10], database.PAYMENT_METHODS[method])
                self.assertIn('payment_method=' + method, context['query_string'](page=2))
        response = self.client.get('/invoices')
        self.assertIn('Chọn phương thức', response.text)
        self.assertNotIn('invoice-status-filter', response.text)

    def test_close_record_saves_methods_and_rejects_invalid_values_atomically(self):
        for method in database.PAYMENT_METHODS:
            record_id = database.add_entry_record('51F-44444', None)
            database.close_record(record_id, 'out.jpg', 10000, payment_method=method)
            item = next(r for r in database.get_all_records() if r['id'] == record_id)
            self.assertEqual(item['payment_method'], method)
        record_id = database.add_entry_record('51F-55555', None)
        with self.assertRaises(ValueError):
            database.close_record(record_id, 'out.jpg', 10000, payment_method='invalid')
        self.assertIsNotNone(database.find_open_record('51F-55555'))
        database.close_record(record_id, 'out.jpg', 0, payment_method='cash')
        item = next(r for r in database.get_all_records() if r['id'] == record_id)
        self.assertIsNone(item['payment_method'])

    def test_legacy_records_keep_unknown_methods_after_migration(self):
        record_id = self.receipt(fee=5000)
        database._exec('ALTER TABLE parking_records DROP COLUMN payment_method')
        database.init_db()
        database.init_db()
        invoice = next(r for r in self.module.parking_invoices.get_invoices('admin', 1) if r['id'] == record_id)
        self.assertIsNone(invoice['payment_method'])
        self.assertEqual(invoice['payment_method_label'], 'Chưa ghi nhận')

    def test_exit_confirmation_records_the_selected_payment_method(self):
        record_id = self.park()
        with patch.object(self.module, 'calc_fee', return_value=(15000, timedelta(hours=1), 'Phí kiểm thử')):
            preview, token = self.recognize('/exit')
            self.assertIn('name="payment_method"', preview.text)
            data = dict(action='confirm', token=token, source='camera', plate='51F-12345',
                        checked_plate='51F-12345', payment_method='invalid')
            rejected = self.client.post('/exit', data=data)
            self.assertEqual(rejected.status_code, 200)
            self.assertIsNotNone(database.find_open_record('51F-12345'))
            data['payment_method'] = 'card'
            response = self.client.post('/exit', data=data)
        self.assertEqual(response.status_code, 302)
        record = next(r for r in database.get_all_records() if r['id'] == record_id)
        self.assertEqual((record['fee'], record['payment_method'], record['status']), (15000, 'card', 'OUT'))
        invoice = self.client.get(f'/invoices/{record_id}/print')
        self.assertIn('Thẻ', invoice.text)
