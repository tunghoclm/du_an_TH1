"""Customer contact data, vehicle statistics, filter/export scope and permissions."""
import csv
from datetime import date, timedelta
from io import StringIO
import re
import unittest

import test_gate
import database
from plate_utils import plate_key


class CustomerDirectoryTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)
    setUp = test_gate.GateTests.setUp

    def customer(self, username='owner', **profile):
        user_id = database.add_user(username, profile.pop('fullname', 'Nguyễn Minh Anh'), 'private-test-password', 'user')
        database.update_customer_profile(user_id, database.get_user_by_id(user_id)['fullname'], **profile)
        return user_id

    def vehicle(self, user_id, plate='51F-12345', ticket='turn', expires=None, paid=None):
        database.add_user_vehicle(user_id, plate, plate_key(plate), self.type_id, ticket, expires,
                                  date.today().isoformat() if ticket == 'month' else None,
                                  1 if ticket == 'month' else None, paid)

    def context(self, **args):
        return self.module.parking_customers.customer_context(args)

    def csv_rows(self, url='/customers/export'):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return list(csv.reader(StringIO(response.data.decode('utf-8-sig'))))

    def test_totals_combine_recorded_exit_fees_and_month_payments_once(self):
        user_id = self.customer()
        self.vehicle(user_id, ticket='month', expires=(date.today() + timedelta(days=4)).isoformat(), paid=100000)
        record = database.add_entry_record('51F-12345', None, 'A01', self.type_id, 'Xe kiểm thử')
        database._exec("UPDATE parking_records SET status='OUT',fee=15000,exit_time=entry_time WHERE id=?", (record,))
        database.add_entry_record('51F12345', None, 'A02', self.type_id, 'Xe kiểm thử')
        self.customer('empty')
        context = self.context()
        owner = next(c for c in context['customers'] if c['id'] == user_id)
        self.assertEqual((owner['parking_fee'], owner['monthly_fee'], owner['total_fee']), (15000, 100000, 115000))
        self.assertEqual((owner['visit_count'], owner['vehicle_count'], owner['monthly_count'], owner['parking_count']), (2, 1, 1, 1))
        self.assertIn('expiring', owner['groups'])
        self.assertEqual(context['total_customer_fee'], 115000)
        self.assertNotIn('password', owner)

    def test_search_finds_contacts_codes_and_normalized_plate_numbers(self):
        owner = self.customer(phone='0901 234 567', email='owner@example.com')
        self.vehicle(owner)
        self.customer('other', fullname='Khách khác')
        for keyword in ('minh anh', '0901234567', 'OWNER@EXAMPLE.COM', '51f12345', f'KH{owner:06d}'):
            with self.subTest(keyword=keyword):
                self.assertEqual([c['id'] for c in self.context(q=keyword)['customers']], [owner])

    def test_groups_status_and_vehicle_filters_do_not_mix_staff_accounts(self):
        valid = self.customer('valid')
        self.vehicle(valid, ticket='month', expires=(date.today() + timedelta(days=20)).isoformat())
        expired = self.customer('expired')
        self.vehicle(expired, '51F-99999', ticket='month', expires=(date.today() - timedelta(days=1)).isoformat())
        empty = self.customer('empty')
        database.toggle_user_status(expired)
        self.assertEqual([c['id'] for c in self.context(group='month')['customers']], [valid])
        self.assertEqual([c['id'] for c in self.context(group='expired', status='locked')['customers']], [expired])
        self.assertEqual([c['id'] for c in self.context(group='no_vehicle')['customers']], [empty])
        self.assertEqual({c['id'] for c in self.context(vehicle_type=str(self.type_id))['customers']}, {valid, expired})

    def test_new_contact_fields_are_saved_and_invalid_forms_keep_entered_values(self):
        data = dict(username='new-contact', fullname='Khách Mới', password='test1234',
                    phone='0901234567', email='new@example.com', address='Bãi xe A', customer_note='Cần vé tháng')
        response = self.client.post('/customers/add', data=data)
        self.assertEqual(response.status_code, 302)
        saved = next(u for u in database.get_customer_users() if u['username'] == 'new-contact')
        self.assertEqual((saved['phone'], saved['email'], saved['address']), ('0901234567', 'new@example.com', 'Bãi xe A'))
        self.assertTrue(saved['created_at'])
        response = self.client.post('/customers/add', data=data)
        self.assertEqual(response.status_code, 200)
        add_tag = re.search(r'<dialog id="add-customer-dialog"[^>]*>', response.text).group()
        self.assertIn('data-open-on-load', add_tag)
        self.assertIn('new@example.com', response.text)
        data.update(username='invalid-contact', phone='invalid', email='invalid')
        self.assertEqual(self.client.post('/customers/add', data=data).status_code, 200)
        self.assertFalse(database.username_exists('invalid-contact'))

    def test_customer_forms_are_closed_on_initial_page_load(self):
        self.customer()
        response = self.client.get('/customers')
        for tag in re.findall(r'<dialog\b[^>]*>', response.text):
            self.assertNotIn('data-open-on-load', tag)

    def test_profile_edit_cannot_change_roles_passwords_or_staff_profiles(self):
        owner = self.customer()
        with self.client.session_transaction() as session:
            session.update(role='manager', user_id=2)
        response = self.client.post(f'/customers/{owner}/profile', data=dict(fullname='Tên mới', phone='0901234567',
                                     email='valid@example.com', role='admin', password='changed'))
        self.assertEqual(response.status_code, 302)
        saved = database.get_user_by_id(owner)
        self.assertEqual((saved['role'], saved['password'], saved['phone']), ('user', 'private-test-password', '0901234567'))
        self.assertEqual(self.client.post('/customers/1/profile', data={'fullname':'Forbidden'}).status_code, 403)
        with self.client.session_transaction() as session:
            session.update(role='user', user_id=owner)
        for path in ('/customers', '/customers/export'):
            self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.client.post(f'/customers/{owner}/profile', data={'fullname':'Forbidden'}).status_code, 302)

    def test_dates_ignore_unknown_legacy_creation_times_and_filter_real_visits(self):
        first, second = self.customer('first'), self.customer('second')
        database._exec('UPDATE users SET created_at=? WHERE id=?', ('2026-11-02T09:00:00', first))
        database._exec('UPDATE users SET created_at=NULL WHERE id=?', (second,))
        self.vehicle(first)
        record = database.add_entry_record('51F-12345', None)
        database._exec('UPDATE parking_records SET entry_time=? WHERE id=?', ('2026-11-02T10:00:59', record))
        context = self.context(created_range='custom', created_from='2026-11-02', created_to='2026-11-02',
                               visit_range='custom', visit_from='2026-11-02T10:00', visit_to='2026-11-02T10:00')
        self.assertEqual([c['id'] for c in context['customers']], [first])
        self.assertEqual(self.client.get('/customers/export?created_range=custom&created_from=bad').status_code, 400)

    def test_pagination_exports_all_filtered_customers_and_only_selected_customer_ids(self):
        ids = [self.customer('owner' + str(i)) for i in range(23)]
        context = self.context(page='2')
        self.assertEqual((len(context['customers']), context['customer_count']), (3, 23))
        rows = self.csv_rows('/customers/export?page=2')
        self.assertEqual(len(rows), 24)
        selected = self.csv_rows(f'/customers/export?ids={ids[0]},{ids[1]},1')
        self.assertEqual(len(selected), 3)
        self.assertNotIn('private-test-password', str(rows))
        self.assertEqual(self.client.get('/customers/export?ids=invalid').status_code, 400)

    def test_legacy_profile_migration_preserves_unknown_dates_and_customer_identity(self):
        owner = self.customer()
        for field in ('phone','email','address','customer_note','created_at'):
            database._exec(f'ALTER TABLE users DROP COLUMN {field}')
        database.init_db()
        database.init_db()
        saved = database.get_user_by_id(owner)
        self.assertEqual(saved['username'], 'owner')
        self.assertIsNone(saved['created_at'])
        self.assertIsNone(saved['phone'])

    def test_notes_are_html_escaped_and_export_cannot_create_spreadsheet_formulas(self):
        self.customer(fullname='=SUM(1,2)', customer_note='<script>alert(1)</script>')
        response = self.client.get('/customers')
        self.assertNotIn('<script>alert(1)</script>', response.text)
        self.assertIn('&lt;script&gt;', response.text)
        self.assertEqual(self.csv_rows()[1][1], "'=SUM(1,2)")
