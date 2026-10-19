"""Area/slot permissions, staff operations, migrations and history time filters.

All writes use isolated SQLite databases and photo directories.
"""
from datetime import datetime, timedelta
import sys
import unittest
from unittest.mock import patch

import test_gate
import database
from plate_utils import plate_key


class ParkingManagementTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)
    setUp = test_gate.GateTests.setUp
    park = test_gate.GateTests.park
    recognize = test_gate.GateTests.recognize
    confirm = test_gate.GateTests.confirm

    def role(self, role):
        with self.client.session_transaction() as session:
            session['role'] = role
            session['username'] = 'staff-test' if role == 'manager' else role + '-test'

    def slot(self, name):
        return next(s for s in database.get_all_slots() if s['slot_name'] == name)

    def area(self, name):
        return next(a for a in database.get_areas() if a['name'] == name)

    def test_admin_staff_and_user_see_only_their_controls(self):
        for role in ('admin', 'manager', 'user'):
            with self.subTest(role=role):
                self.role(role)
                response = self.client.get('/parking')
                self.assertEqual(response.status_code, 200)
                self.assertEqual('id="area-dialog"' in response.text, role == 'admin')
                self.assertEqual('id="slot-add-dialog"' in response.text, role == 'admin')
                self.assertEqual('id="vehicle-dialog"' in response.text, role != 'user')
                self.assertEqual('data-open-slot' in response.text, role != 'user')

    def test_staff_and_users_cannot_call_admin_mutations_directly(self):
        area = self.area('A')
        for role in ('manager', 'user'):
            self.role(role)
            for url, data in [('/parking/areas/save', {'name': 'Forbidden'}),
                              ('/parking/areas/save', {'area_id': area['id'], 'name': 'Changed'}),
                              ('/parking/slots/add', {'area_id': area['id'], 'slot_name': 'A99'}),
                              ('/parking/A01/delete', {})]:
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.post(url, data=data).status_code, 302)
                    self.assertEqual(len(database.get_areas()), 3)
                    self.assertEqual(database.slot_counts()['total'], 60)
                    self.assertEqual(self.area('A')['name'], 'A')

    def test_admin_can_add_rename_restrict_area_and_manage_empty_slots(self):
        self.client.post('/parking/areas/save', data={'name': 'D', 'vehicle_type_id': self.type_id, 'slot_count': '1'})
        area = self.area('D')
        self.client.post('/parking/slots/add', data={'area_id': area['id'], 'slot_name': 'd01'})
        self.assertEqual(self.slot('D01')['area'], 'D')
        self.assertEqual(self.slot('D01')['allowed_vehicle_type_id'], self.type_id)
        self.client.post('/parking/areas/save', data={'area_id': area['id'], 'name': 'Tầng hầm', 'vehicle_type_id': self.type_id})
        self.assertEqual(self.slot('D01')['area'], 'Tầng hầm')
        self.assertIn('Tầng hầm', database.area_stats())
        self.assertNotIn('D', database.area_stats())
        self.assertIn('Khu Tầng hầm', self.client.get('/parking').text)
        self.client.post('/parking/D01/delete')
        self.assertFalse(database.get_available_slots_by_area()['Tầng hầm'])

    def test_invalid_area_and_slot_changes_do_not_modify_configuration(self):
        for data in ({'name': 'a'}, {'name': ' '}, {'name': 'D', 'vehicle_type_id': '99999'}, {'area_id': 'bad', 'name': 'D'}):
            self.client.post('/parking/areas/save', data=data)
        self.assertEqual(len(database.get_areas()), 3)
        for name in ('A01', '../outside', '', 'A' * 33):
            self.client.post('/parking/slots/add', data={'area_id': self.area('A')['id'], 'slot_name': name})
        self.assertEqual(database.slot_counts()['total'], 60)

    def test_admin_can_explicitly_allow_all_types_when_editing_an_area(self):
        area_id = self.area('A')['id']
        database.save_area(area_id, 'A', self.type_id)
        self.client.post('/parking/areas/save', data={'area_id': area_id, 'name': 'A changed'})
        self.assertEqual(self.area('A')['vehicle_type_id'], self.type_id)
        self.client.post('/parking/areas/save', data={'area_id': area_id, 'name': 'A changed', 'vehicle_type_id': 'all'})
        self.assertIsNone(self.area('A changed')['vehicle_type_id'])

    def test_restricting_area_with_incompatible_occupied_car_is_rejected_atomically(self):
        self.park()
        other_type = next(t['id'] for t in database.get_vehicle_types() if t['id'] != self.type_id)
        self.client.post('/parking/areas/save', data={'area_id': self.area('A')['id'], 'name': 'Renamed', 'vehicle_type_id': other_type})
        self.assertIsNone(self.area('A')['vehicle_type_id'])
        self.assertEqual(self.slot('A01')['area'], 'A')
        self.client.post('/parking/A01/delete')
        self.assertEqual(self.slot('A01')['status'], 'occupied')

    def test_manual_and_automatic_entry_enforce_area_vehicle_type(self):
        other_type = next(t['id'] for t in database.get_vehicle_types() if t['id'] != self.type_id)
        database.save_area(self.area('A')['id'], 'A', other_type)
        _, token = self.recognize()
        self.assertEqual(self.confirm('/entry', token).status_code, 200)
        self.assertEqual(database.count_open(), 0)
        database.set_user_setting(1, 'entry_mode', 'auto')
        self.assertEqual(self.confirm('/entry', token).status_code, 302)
        record = database.find_open_record('51F-12345')
        self.assertEqual(record['slot_name'], 'B01')
        self.assertEqual(self.slot('A01')['status'], 'available')

    def test_new_area_works_in_gate_when_no_abc_slots_remain(self):
        database._exec('DELETE FROM parking_slots')
        area_id = database.save_area(None, 'D', self.type_id)
        database.add_slot(area_id, 'D01')
        response, token = self.recognize()
        self.assertIn('label="Khu D"', response.text)
        response = self.client.post('/entry', data={'action': 'confirm', 'source': 'camera', 'token': token,
                    'plate': '51F-12345', 'checked_plate': '51F-12345', 'slot_name': 'D01', 'vehicle_type_id': self.type_id})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(database.find_open_record('51F-12345')['slot_name'], 'D01')
        self.assertEqual(database.area_stats()['D']['occupied'], 1)

    def test_migration_preserves_legacy_slots_and_records_and_is_idempotent(self):
        record_id = self.park()
        database._exec('DROP TABLE parking_areas')
        database._exec('ALTER TABLE parking_slots DROP COLUMN maintenance_reason')
        database.init_db()
        self.assertEqual(len(database.get_areas()), 3)
        self.assertEqual(self.slot('A01')['status'], 'occupied')
        self.assertEqual(database.find_open_record('51F-12345')['id'], record_id)
        database.save_area(self.area('A')['id'], 'A renamed', self.type_id)
        database._exec('DELETE FROM parking_slots')
        database.init_db()
        self.assertEqual(database.slot_counts()['total'], 0)  # do not recreate admin-deleted slots
        self.assertEqual(self.area('A renamed')['vehicle_type_id'], self.type_id)

    def test_admin_and_staff_move_vehicle_with_actor_and_both_slots_in_history(self):
        record_id = self.park()
        database._exec('UPDATE parking_records SET note=? WHERE id=?', ('Ghi chú gốc', record_id))
        original_time = database.find_open_record('51F-12345')['entry_time']
        for role, source, target in [('admin', 'A01', 'A02'), ('manager', 'A02', 'A03')]:
            self.role(role)
            response = self.client.post(f'/parking/{source}/move', data={'target_slot': target, 'record_id': record_id})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.slot(source)['status'], 'available')
            self.assertEqual(self.slot(target)['status'], 'occupied')
        record = database.find_open_record('51F-12345')
        self.assertEqual(record['slot_name'], 'A03')
        self.assertEqual(record['entry_time'], original_time)
        for text in ('Ghi chú gốc', 'A01 sang ô A02', 'A02 sang ô A03', 'staff-test'):
            self.assertIn(text, record['note'])
            self.assertIn(text, self.client.get('/history').text)

    def test_invalid_moves_preserve_car_and_target_states(self):
        record_id = self.park()
        database.create_parking_entry('30A-54321', 'other.jpg', 'A02', self.type_id, 'Test')
        database.set_slot_maintenance('A03', True, 'Sửa nền')
        for target, expected in [('A01', record_id), ('B01', record_id), ('A02', record_id),
                                 ('A03', record_id), ('missing', record_id), ('A04', record_id + 999)]:
            self.client.post('/parking/A01/move', data={'target_slot': target, 'record_id': expected})
            self.assertEqual(database.find_open_record('51F-12345')['slot_name'], 'A01')
            self.assertIsNone(database.find_open_record('51F-12345')['note'])
        self.assertEqual(self.slot('A03')['status'], 'maintenance')
        self.assertEqual(self.slot('A02')['plate_number'], '30A-54321')

    def test_exit_after_move_releases_new_slot_without_affecting_car_in_old_slot(self):
        record_id = self.park()
        database.move_parked_vehicle('A01', 'A02', record_id, 'test')
        database.create_parking_entry('30A-54321', 'other.jpg', 'A01', self.type_id, 'Test')
        _, token = self.recognize('/exit')
        self.assertEqual(self.confirm('/exit', token).status_code, 302)
        self.assertEqual(self.slot('A02')['status'], 'available')
        self.assertEqual(self.slot('A01')['plate_number'], '30A-54321')
        record = next(r for r in database.get_all_records() if r['id'] == record_id)
        self.assertEqual(record['status'], 'OUT')
        self.assertIn('A01 sang ô A02', record['note'])

    def test_removal_requires_reason_preserves_history_and_does_not_add_revenue(self):
        record_id = self.park()
        self.role('manager')
        for reason in ('', '   ', 'x' * 501):
            self.client.post('/parking/A01/remove', data={'record_id': record_id, 'reason': reason})
            self.assertIsNotNone(database.find_open_record('51F-12345'))
        self.client.post('/parking/A01/remove', data={'record_id': record_id, 'reason': 'Ghi nhầm xe <script>alert(1)</script>'})
        record = database.get_all_records()[0]
        self.assertEqual(record['status'], 'DELETED')
        self.assertIsNone(record['fee'])
        self.assertTrue(record['exit_time'])
        self.assertIn('staff-test', record['note'])
        self.assertIn('Ghi nhầm xe', record['note'])
        self.assertEqual(self.slot('A01')['status'], 'available')
        self.assertEqual(database.count_open(), 0)
        self.assertEqual(database.get_statistics()['parking_revenue'], 0)
        history = self.client.get('/history?status=DELETED').text
        self.assertIn('Đã xóa', history)
        self.assertIn('&lt;script&gt;', history)
        self.assertNotIn('<script>alert(1)</script>', history)
        import export_stats
        payload = export_stats.make_payload(database.get_statistics(), database.area_stats(), database.get_all_records(),
                                           'test', '2026-01-01', '2026-12-31', 'test')
        self.assertEqual(payload['records'][0][4], 'Đã xóa')

    def test_stale_vehicle_action_cannot_remove_or_move_replacement_car(self):
        old_id = self.park()
        database.remove_parked_vehicle('A01', old_id, 'Test', 'test')
        new_id, _ = database.create_parking_entry('30A-54321', 'other.jpg', 'A01', self.type_id, 'Test')
        self.client.post('/parking/A01/remove', data={'record_id': old_id, 'reason': 'Old dialog'})
        self.client.post('/parking/A01/move', data={'record_id': old_id, 'target_slot': 'A02'})
        self.assertEqual(database.find_open_record('30A-54321')['id'], new_id)
        self.assertEqual(self.slot('A01')['plate_number'], '30A-54321')
        self.assertEqual(self.slot('A02')['status'], 'available')

    def test_exit_race_does_not_revive_deleted_record_or_free_replacement_car(self):
        old_id = self.park()
        _, token = self.recognize('/exit')
        close_record = database.close_record

        def delete_then_close(*args, **kwargs):
            database.remove_parked_vehicle('A01', old_id, 'Test race', 'test')
            database.create_parking_entry('30A-54321', 'other.jpg', 'A01', self.type_id, 'Test')
            return close_record(*args, **kwargs)

        with patch.object(database, 'close_record', side_effect=delete_then_close):
            self.assertEqual(self.confirm('/exit', token).status_code, 302)
        self.assertEqual(self.slot('A01')['plate_number'], '30A-54321')
        old_record = next(r for r in database.get_all_records() if r['id'] == old_id)
        self.assertEqual(old_record['status'], 'DELETED')

    def test_user_cannot_mutate_vehicles_or_maintenance_even_by_direct_post(self):
        record_id = self.park()
        self.role('user')
        for url, data in [('/parking/A01/remove', {'record_id': record_id, 'reason': 'Not allowed'}),
                          ('/parking/A01/move', {'record_id': record_id, 'target_slot': 'A02'}),
                          ('/parking/A02/maintenance', {'maintenance_action': 'start', 'reason': 'Not allowed'})]:
            self.assertEqual(self.client.post(url, data=data).status_code, 302)
        self.assertEqual(database.find_open_record('51F-12345')['slot_name'], 'A01')
        self.assertEqual(self.slot('A02')['status'], 'available')

    def test_maintenance_requires_reason_can_update_and_finish_without_flipping_stale_state(self):
        self.role('manager')
        self.client.post('/parking/A02/maintenance', data={'maintenance_action': 'start', 'reason': ' '})
        self.assertEqual(self.slot('A02')['status'], 'available')
        self.client.post('/parking/A02/maintenance', data={'maintenance_action': 'start', 'reason': 'Nền bị hỏng'})
        self.assertEqual(self.slot('A02')['maintenance_reason'], 'Nền bị hỏng')
        self.assertIn('Nền bị hỏng', self.client.get('/parking').text)
        self.client.post('/parking/A02/maintenance', data={'maintenance_action': 'update', 'reason': 'Đang lát lại nền'})
        self.assertEqual(self.slot('A02')['maintenance_reason'], 'Đang lát lại nền')
        self.client.post('/parking/A02/maintenance', data={'maintenance_action': 'finish'})
        self.client.post('/parking/A02/maintenance', data={'maintenance_action': 'finish'})
        self.assertEqual(self.slot('A02')['status'], 'available')
        self.assertIsNone(self.slot('A02')['maintenance_reason'])
        self.park()
        self.client.post('/parking/A01/maintenance', data={'maintenance_action': 'start', 'reason': 'Cannot override car'})
        self.assertEqual(self.slot('A01')['status'], 'occupied')

    def history_samples(self):
        for plate, entry, exit, status in [
            ('51F-11111', '2026-10-19T06:30:00', '2026-10-19T07:10:00', 'OUT'),
            ('51F-22222', '2026-10-19T13:00:00', '2026-10-19T16:59:59', 'OUT'),
            ('51F-33333', '2026-10-19T23:30:00', '2026-10-20T00:10:00', 'DELETED'),
            ('51F-44444', '2026-10-20T02:00:00', None, 'IN'),
            ('51F-55555', '2026-10-19T02:00:00', '2026-10-19T04:00:00', 'OUT')]:
            database._exec('INSERT INTO parking_records(plate_number,entry_time,exit_time,status) VALUES (?,?,?,?)',
                           (plate, entry, exit, status))

    def test_history_time_range_and_date_filter_by_entry(self):
        self.history_samples()
        response = self.client.get('/history?date=2026-10-19&time_from=05:00&time_to=12:59')
        self.assertIn('51F-11111', response.text)
        for plate in ('51F-22222', '51F-33333', '51F-44444', '51F-55555'):
            self.assertNotIn(plate, response.text)
        self.assertIn('Chọn khung giờ', response.text)
        self.assertNotIn('name="time_field"', response.text)

    def test_history_filters_exit_time_including_final_minute_and_deleted_records(self):
        self.history_samples()
        response = self.client.get('/history?date=2026-10-19&time_field=exit&time_from=16:00&time_to=16:59')
        self.assertIn('51F-22222', response.text)
        self.assertNotIn('51F-11111', response.text)
        response = self.client.get('/history?date=2026-10-20&time_field=exit&time_from=00:00&time_to=03:00&status=DELETED')
        self.assertIn('51F-33333', response.text)
        self.assertNotIn('51F-44444', response.text)

    def test_history_overnight_window_uses_next_date_for_early_hours(self):
        self.history_samples()
        response = self.client.get('/history?date=2026-10-19&time_from=22:00&time_to=03:00')
        self.assertIn('51F-33333', response.text)
        self.assertIn('51F-44444', response.text)
        self.assertNotIn('51F-55555', response.text)

    def test_history_user_scope_remains_enforced_with_new_filters(self):
        self.history_samples()
        database._exec('INSERT INTO user_vehicles(user_id,plate_number,plate_key,created_at) VALUES (?,?,?,?)',
                       (1, '51F-33333', plate_key('51F-33333'), datetime.now().isoformat()))
        self.role('user')
        response = self.client.get('/history?time_from=22:00&time_to=03:00')
        self.assertIn('51F-33333', response.text)
        self.assertNotIn('51F-44444', response.text)
        response = self.client.get('/history?time_from=bad&date=not-a-date')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('51F-11111', response.text)

    def test_deleted_record_is_exported_on_removal_date_even_if_entry_was_earlier(self):
        record_id = self.park()
        yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
        database._exec('UPDATE parking_records SET entry_time=? WHERE id=?', (yesterday + 'T12:00:00', record_id))
        database.remove_parked_vehicle('A01', record_id, 'Test', 'test')
        today = datetime.now().date().isoformat()
        self.assertEqual(len(database.get_records_between(today, today)), 1)
        self.assertEqual(database.get_statistics(today, today)['period_records'], 1)
        self.assertEqual(database.get_statistics(today, today)['period_exits'], 0)

    def test_new_area_creates_requested_number_of_sequential_slots(self):
        self.client.post('/parking/areas/save', data={'name': 'D', 'slot_count': '10', 'vehicle_type_id': self.type_id})
        slots = database.get_available_slots_by_area()['D']
        self.assertEqual([s['slot_name'] for s in slots], [f'D{i:02d}' for i in range(1, 11)])
        self.assertEqual(database.slot_counts()['total'], 70)
        self.client.post('/parking/areas/save', data={'area_id': self.area('D')['id'], 'name': 'D renamed', 'vehicle_type_id': 'all'})
        self.assertEqual(len(database.get_available_slots_by_area()['D renamed']), 10)

    def test_creation_requires_valid_count_and_rolls_back_name_collisions(self):
        for count in ('', '0', '-1', '10.5', '1001', 'invalid'):
            self.client.post('/parking/areas/save', data={'name': 'D', 'slot_count': count})
            self.assertFalse(any(a['name'] == 'D' for a in database.get_areas()))
        database.add_slot(self.area('A')['id'], 'D03')
        self.client.post('/parking/areas/save', data={'name': 'D', 'slot_count': '10'})
        self.assertFalse(any(a['name'] == 'D' for a in database.get_areas()))
        self.assertFalse(any(s['slot_name'] == 'D01' for s in database.get_all_slots()))
        self.assertEqual(database.slot_counts()['total'], 61)

    def test_admin_can_delete_unoccupied_area_and_its_slots_without_erasing_history(self):
        record_id = self.park()
        database.close_record(record_id, 'out.jpg', 7000)
        area_id = self.area('A')['id']
        response = self.client.post(f'/parking/areas/{area_id}/delete')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(any(a['name'] == 'A' for a in database.get_areas()))
        self.assertEqual(database.slot_counts()['total'], 40)
        record = next(r for r in database.get_all_records() if r['id'] == record_id)
        self.assertEqual((record['status'], record['fee'], record['slot_name']), ('OUT', 7000, 'A01'))

    def test_area_deletion_rejects_occupied_area_and_non_admin_callers(self):
        self.park()
        area_id = self.area('A')['id']
        for role in ('admin', 'manager', 'user'):
            self.role(role)
            self.client.post(f'/parking/areas/{area_id}/delete')
            self.assertEqual(len(database.get_areas()), 3)
            self.assertEqual(self.slot('A01')['status'], 'occupied')
        empty_id = self.area('B')['id']
        for role in ('manager', 'user'):
            self.role(role)
            self.client.post(f'/parking/areas/{empty_id}/delete')
            self.assertEqual(len(database.get_areas()), 3)

    def test_deleted_last_area_is_not_reseeded_on_restart(self):
        for area in database.get_areas():
            database.delete_area(area['id'])
        database.init_db()
        self.assertEqual(database.get_areas(), [])
        self.assertEqual(database.slot_counts()['total'], 0)
        self.assertEqual(self.client.get('/parking').status_code, 200)
        self.client.post('/parking/areas/save', data={'name': 'D', 'slot_count': 10})
        self.assertEqual(database.slot_counts()['total'], 10)

    def test_admin_renames_empty_or_occupied_slot_and_preserves_car_tracking(self):
        self.client.post('/parking/A02/save', data={'slot_name': 'A99', 'expected_status': 'available'})
        self.assertEqual(self.slot('A99')['area'], 'A')
        record_id = self.park()
        entry = database.find_open_record('51F-12345')['entry_time']
        self.client.post('/parking/A01/save', data={'slot_name': 'A98', 'expected_status': 'occupied', 'record_id': record_id})
        record = database.find_open_record('51F-12345')
        self.assertEqual((record['slot_name'], record['entry_time']), ('A98', entry))
        self.assertIn('A01 thành A98', record['note'])
        _, token = self.recognize('/exit')
        self.assertEqual(self.confirm('/exit', token).status_code, 302)
        self.assertEqual(self.slot('A98')['status'], 'available')

    def test_slot_rename_checks_permission_duplicates_and_stale_vehicle(self):
        record_id = self.park()
        for role in ('manager', 'user'):
            self.role(role)
            self.client.post('/parking/A01/save', data={'slot_name': 'A99', 'expected_status': 'occupied', 'record_id': record_id})
            self.assertEqual(database.find_open_record('51F-12345')['slot_name'], 'A01')
        self.role('admin')
        for name, status, record in [('A02', 'occupied', record_id), ('A99', 'available', None),
                                     ('A99', 'occupied', record_id + 1), ('../bad', 'occupied', record_id)]:
            self.client.post('/parking/A01/save', data={'slot_name': name, 'expected_status': status, 'record_id': record})
            self.assertEqual(database.find_open_record('51F-12345')['slot_name'], 'A01')

    def test_history_hides_hour_inputs_until_requested_and_keeps_active_values_visible(self):
        from html.parser import HTMLParser

        class Controls(HTMLParser):
            def __init__(self):
                super().__init__()
                self.nodes = {}

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if attrs.get('id'):
                    self.nodes[attrs['id']] = attrs

        for query, active in [('', False), ('?time_from=05:00&time_to=12:59', True)]:
            response = self.client.get('/history' + query)
            controls = Controls()
            controls.feed(response.text)
            self.assertNotIn('time-field', controls.nodes)
            self.assertNotIn('Chọn nhanh khung giờ', response.text)
            self.assertEqual('hidden' in controls.nodes['history-time-fields'], not active)
            self.assertEqual('disabled' in controls.nodes['time-from'], not active)


if __name__ == '__main__':
    unittest.main()
