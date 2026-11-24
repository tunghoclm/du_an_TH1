"""Kiểm tra luồng vào / ra bằng DB và ảnh tạm riêng, không nạp model OCR hay sửa dữ liệu thật.

Chạy: python -m unittest discover -s tests -v
"""
import importlib.util
from io import BytesIO
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py'))
import config
import database


class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='parking-gate-tests-')
        cls.root = Path(cls.temp.name)
        cls.original_paths = {key: getattr(config, key) for key in ('DB_PATH', 'TMP_DIR', 'IN_DIR', 'OUT_DIR')}
        config.DB_PATH = str(cls.root / 'initial.db')
        database.DB_PATH = config.DB_PATH
        for key in ('TMP_DIR', 'IN_DIR', 'OUT_DIR'):
            path = cls.root / key
            path.mkdir()
            setattr(config, key, str(path))
        cls.frame = np.full((80, 200, 3), 220, dtype=np.uint8)
        cls.jpg = cv2.imencode('.jpg', cls.frame)[1].tobytes()
        recognition = types.ModuleType('plate_recognition')
        recognition.recognize_plate_annotated = lambda path: ('51F-12345', cls.frame)
        recognition.recognize_plate = lambda path: ('51F-12345', cls.frame)
        recognition.recognize_plate_live = lambda path, **kw: ('51F-12345', cls.frame, (10, 10, 100, 40), 200, 80,
                                                            dict(confidence=0.95, elapsed_ms=200, engine='easyocr-rows'))
        spec = importlib.util.spec_from_file_location('parking_gate_test_app', ROOT / 'app.py')
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'easyocr': types.ModuleType('easyocr'), 'plate_recognition': recognition}):
            spec.loader.exec_module(cls.module)
        cls.app = cls.module.app
        cls.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        for key, value in cls.original_paths.items():
            setattr(config, key, value)
        database.DB_PATH = config.DB_PATH
        cls.temp.cleanup()

    def test_pricing_policy_save_render_and_validation(self):
        vt = database.get_vehicle_types()[0]
        response = self.client.post('/pricing/type/save', data=dict(
            id=vt['id'], name=vt['name'], grace_minutes=15, daily_cap=50000), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        saved = dict(database.get_vehicle_types()[0])
        self.assertEqual((saved['grace_minutes'], saved['daily_cap']), (15, 50000))
        self.assertIn(b'data-grace="15"', response.data)
        for value in ('-1', '1.5', 'abc', '1441'):
            self.client.post('/pricing/type/save', data=dict(
                id=vt['id'], name=vt['name'], grace_minutes=value, daily_cap=1))
            self.assertEqual(database.get_vehicle_types()[0]['daily_cap'], 50000)

    def test_core_vehicle_pricing_and_monthly_lookup(self):
        vt = database.get_vehicle_types()[0]
        response = self.client.post('/pricing/type/save', data=dict(
            id=vt['id'], name=vt['name'], free_minutes=10, first_block_hours=2,
            first_block_amount=30000, next_hour_amount=10000, daily_cap=150000,
            monthly_price=700000), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(database.find_month_price(vt['id'], datetime.now().date())['amount'], 700000)
        self.assertEqual(database.find_turn_price(vt['id'], datetime.now())['amount'], 30000)
        entry = datetime(2026, 11, 1, 8)
        record = dict(entry_time=entry.isoformat(), plate_number='99X-99999',
                      vehicle_type_id=vt['id'], vehicle_type_name=vt['name'])
        self.assertEqual(self.module.calc_fee(record, entry.replace(hour=10, minute=1))[0], 40000)
        database.save_vehicle_type(vt['id'], vt['name'], monthly_price=0)
        self.assertEqual(database.find_month_price(vt['id'], entry.date())['amount'], 0)

    def test_existing_database_migrates_policy_columns(self):
        conn = database.get_connection()
        try:
            conn.execute('ALTER TABLE vehicle_types DROP COLUMN grace_minutes')
            conn.execute('ALTER TABLE vehicle_types DROP COLUMN daily_cap')
            conn.commit()
        finally:
            conn.close()
        database.init_db()
        database.init_db()
        vt = database.get_vehicle_types()[0]
        self.assertEqual((vt['grace_minutes'], vt['daily_cap']), (0, 0))

    def setUp(self):
        database.DB_PATH = str(self.root / (self._testMethodName + '.db'))
        database.init_db()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session.update(user_id=1, username='admin', fullname='Admin', role='admin')
        database.save_vehicle_type(None, 'Xe kiểm thử')
        self.type_id = next(t['id'] for t in database.get_vehicle_types() if t['name'] == 'Xe kiểm thử')
        database.save_period(None, 'Cả ngày kiểm thử', 'time', '00:00', '23:59')
        period_id = next(p['id'] for p in database.get_periods() if p['name'] == 'Cả ngày kiểm thử')
        database.save_price(None, self.type_id, period_id, 7000, 'turn')

    def recognize(self, route='/entry', plate='51F-12345', source='camera'):
        with patch.object(self.module, 'recognize_plate_annotated', return_value=(plate, self.frame)):
            response = self.client.post(route, data={
                'action': 'recognize', 'source': source, 'note': 'Ảnh kiểm thử',
                'image': (BytesIO(self.jpg), 'camera.jpg'),
            })
        self.assertEqual(response.status_code, 200)
        match = re.search(r'name="token"[^>]*value="([0-9a-f]{12})"', response.text)
        self.assertIsNotNone(match)
        return response, match.group(1)

    def confirm(self, route, token, plate='51F-12345'):
        return self.client.post(route, data={
            'action': 'confirm', 'source': 'camera', 'token': token,
            'plate': plate, 'checked_plate': plate, 'slot_name': 'A01',
            'vehicle_type_id': str(self.type_id),
        })

    def park(self, plate='51F-12345'):
        record_id = database.add_entry_record(plate, 'old.jpg', 'A01', self.type_id, 'Xe kiểm thử')
        database.occupy_slot('A01', plate)
        return record_id

    def set_car_prices_and_entry(self, entry_time):
        for price in database.get_prices():
            if price['vehicle_type_id'] == self.type_id:
                database.delete_price(price['id'])
        periods = {p['name']: p['id'] for p in database.get_periods()}
        for name, amount in [('Sáng', 150000), ('Chiều', 150000), ('Tối', 250000), ('Đêm', 300000)]:
            database.save_price(None, self.type_id, periods[name], amount, 'turn')
        record_id = self.park()
        database._exec('UPDATE parking_records SET entry_time = ? WHERE id = ?', (entry_time, record_id))

    def test_exit_preview_and_saved_fee_add_all_windows_from_reported_case(self):
        self.set_car_prices_and_entry('2026-10-19T11:37:47')

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 19, 16, 13, 49)

        with patch.object(self.module, 'datetime', Clock), patch.object(database, 'datetime', Clock):
            preview, token = self.recognize('/exit')
            self.assertIn('300.000 VNĐ', preview.text)
            self.assertIn('Sáng', preview.text)
            self.assertIn('Chiều', preview.text)
            self.assertEqual(self.confirm('/exit', token).status_code, 302)
        record = database.get_all_records()[0]
        self.assertEqual(record['fee'], 300000)
        self.assertEqual(record['exit_time'], '2026-10-19T16:13:49')
        self.assertEqual(database.get_statistics()['parking_revenue'], 300000)
        self.assertIn('300.000', self.client.get('/history').text)

    def test_exit_confirmation_recalculates_if_next_window_starts_after_preview(self):
        self.set_car_prices_and_entry('2026-10-19T11:37:47')

        class Clock(datetime):
            current = datetime(2026, 10, 19, 12, 59, 59)

            @classmethod
            def now(cls, tz=None):
                return cls.current

        with patch.object(self.module, 'datetime', Clock), patch.object(database, 'datetime', Clock):
            preview, token = self.recognize('/exit')
            self.assertIn('150.000 VNĐ', preview.text)
            Clock.current = datetime(2026, 10, 19, 13, 0, 0)
            self.assertEqual(self.confirm('/exit', token).status_code, 302)
        self.assertEqual(database.get_all_records()[0]['fee'], 300000)

    def test_month_ticket_exemption_and_expiry_still_apply_across_windows(self):
        self.set_car_prices_and_entry('2026-10-19T11:37:47')
        record = database.find_open_record('51F-12345')
        for expiry, expected in [('2026-10-19', 0), ('2026-10-18', 300000)]:
            with self.subTest(expiry=expiry), patch.object(database, 'get_registered_vehicle', return_value={
                    'ticket_type': 'month', 'expires_on': expiry, 'username': 'test-only'}):
                fee, _, _ = self.module.calc_fee(record, datetime(2026, 10, 19, 16, 13, 49))
            self.assertEqual(fee, expected)

    def test_menu_and_separate_pages(self):
        menu = self.client.get('/gate')
        self.assertEqual(menu.status_code, 200)
        self.assertIn('href="/entry"', menu.text)
        self.assertIn('href="/exit"', menu.text)
        for route, direction in (('/entry', 'entry'), ('/exit', 'exit')):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'action="{route}"', response.text)
            self.assertIn(f'data-direction="{direction}"', response.text)
            self.assertIn('id="camera-select"', response.text)
            self.assertIn('id="camera-start"', response.text)
            self.assertIn('id="camera-overlay"', response.text)
            self.assertIn('formnovalidate', response.text)
        with self.client.get('/static/js/gate.js') as script_response:
            self.assertEqual(script_response.status_code, 200)

    def test_cabin_is_separate_from_management_and_opens_a_new_tab(self):
        management = self.client.get('/parking').text
        cabin_link = re.search(r'<a\b[^>]*class="cabin-button"[^>]*>', management)
        self.assertIsNotNone(cabin_link)
        self.assertIn('target="_blank"', cabin_link.group())
        self.assertIn('rel="noopener"', cabin_link.group())
        self.assertNotIn('/css/cabin.css', management)
        cabin = self.client.get('/gate').text
        self.assertIn('/css/cabin.css', cabin)
        self.assertNotIn('class="app-header topbar"', cabin)
        self.assertIn('data-cabin-slot="A01"', cabin)

    def test_cabin_previews_occupied_slot_without_checking_out_vehicle(self):
        record_id = self.park()
        database._exec('UPDATE parking_records SET entry_time = ? WHERE id = ?',
                       ('2026-11-08T09:00:00', record_id))

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 8, 10)

        with patch.object(self.module, 'datetime', Clock):
            cabin = self.client.get('/gate')
        self.assertEqual(cabin.status_code, 200)
        self.assertIn('data-status="occupied" data-plate="51F-12345" data-fee="7000"', cabin.text)
        self.assertIn('/exit?plate=51F-12345', cabin.text)
        self.assertEqual(database.count_open(), 1)
        self.assertEqual(database.slot_counts()['occupied'], 1)

    def test_plate_from_cabin_does_not_bypass_image_recognition(self):
        self.park()
        response = self.client.get('/exit?plate=51F-12345')
        self.assertIn('value="51F-12345"', response.text)
        confirm = re.search(r'<button\b[^>]*id="confirm-button"[^>]*>', response.text)
        self.assertIn('disabled', confirm.group())
        self.assertEqual(database.count_open(), 1)

    def test_camera_recognition_does_not_record_until_confirmed(self):
        response, token = self.recognize()
        self.assertIn('name="source" id="source-select" value="camera"', response.text)
        self.assertIn('XE VÀO BÃI', response.text)
        self.assertTrue((Path(config.TMP_DIR) / (token + '.jpg')).exists())
        self.assertTrue((Path(config.TMP_DIR) / (token + '_ann.jpg')).exists())
        self.assertEqual(database.count_open(), 0)

    def test_camera_entry_and_exit_save_photos_fee_and_slot(self):
        _, token = self.recognize()
        response = self.confirm('/entry', token)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/entry?source=camera', response.location)
        record = database.find_open_record('51F-12345')
        self.assertEqual(record['slot_name'], 'A01')
        self.assertEqual(database.slot_counts()['occupied'], 1)
        self.assertEqual((Path(config.IN_DIR) / record['entry_image']).read_bytes(), self.jpg)
        preview, exit_token = self.recognize('/exit')
        self.assertIn('XE RA BÃI', preview.text)
        response = self.confirm('/exit', exit_token)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/exit?source=camera', response.location)
        record = database.get_all_records()[0]
        self.assertEqual(record['status'], 'OUT')
        self.assertEqual(record['fee'], 7000)
        self.assertEqual(database.slot_counts()['occupied'], 0)
        self.assertEqual((Path(config.OUT_DIR) / record['exit_image']).read_bytes(), self.jpg)
        self.assertIsNone(database.find_open_record('51F-12345'))

    def test_entry_cannot_exit_an_already_parked_vehicle(self):
        self.park()
        preview, token = self.recognize()
        self.assertIn('đang gửi trong bãi. Hãy chọn Xe ra', preview.text)
        response = self.confirm('/entry', token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(database.count_open(), 1)
        self.assertIsNotNone(database.find_open_record('51F-12345'))
        self.assertTrue((Path(config.TMP_DIR) / (token + '.jpg')).exists())

    def test_exit_cannot_create_an_entry(self):
        preview, token = self.recognize('/exit')
        self.assertIn('Không tìm thấy xe', preview.text)
        response = self.confirm('/exit', token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(database.get_all_records(), [])
        self.assertEqual(database.slot_counts()['occupied'], 0)

    def test_exit_checks_state_again_at_confirmation(self):
        record_id = self.park()
        _, token = self.recognize('/exit')
        database.close_record(record_id, 'other-exit.jpg', 7000)
        database.free_slot('A01')
        response = self.confirm('/exit', token)
        self.assertEqual(response.status_code, 200)
        self.assertIn('không thể xác nhận xe ra', response.text)
        self.assertEqual(len(database.get_all_records()), 1)

    def test_plate_match_ignores_separator_position(self):
        self.park('61-T32222')
        preview, token = self.recognize('/exit', plate='61T-32222')
        self.assertIn('XE RA BÃI', preview.text)
        response = self.confirm('/exit', token, plate='61T-32222')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(database.count_open(), 0)

    def test_upload_and_manual_correction_still_work(self):
        response, token = self.recognize(source='upload')
        self.assertIn('name="source" id="source-select" value="upload"', response.text)
        response = self.client.post('/entry', data={
            'action': 'recognize', 'source': 'upload', 'token': token, 'plate': '30A-54321',
        })
        self.assertIn('30A-54321', response.text)
        self.assertIn('XE VÀO BÃI', response.text)
        self.assertEqual(database.count_open(), 0)

    def test_staff_permissions(self):
        with self.client.session_transaction() as session:
            session['role'] = 'user'
        for route in ('/gate', '/entry', '/exit'):
            self.assertEqual(self.client.get(route).status_code, 302)
        self.assertEqual(self.client.post('/entry', data={'action': 'confirm'}).status_code, 302)
        with self.client.session_transaction() as session:
            session['role'] = 'manager'
        self.assertEqual(self.client.get('/entry').status_code, 200)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertIn('/login', self.client.get('/exit').location)

    def live_frame(self, direction='entry', **kwargs):
        return self.client.post(f'/gate/{direction}/camera', data={
            'source': 'camera', 'image': (BytesIO(self.jpg), 'camera.jpg'), **kwargs,
        })

    def test_live_returns_overlay_and_confirmation_without_recording(self):
        response = self.live_frame()
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertTrue(data['valid'])
        self.assertEqual(data['plate_key'], '51F12345')
        self.assertEqual(data['rect'], [10, 10, 100, 40])
        self.assertEqual((data['width'], data['height']), (200, 80))
        self.assertTrue(data['can_confirm'])
        self.assertIn('XE VÀO BÃI', data['html'])
        self.assertIn('name="vehicle_type_id"', data['html'])
        self.assertEqual(database.count_open(), 0)
        self.assertEqual(self.confirm('/entry', data['token']).status_code, 302)
        self.assertEqual(database.count_open(), 1)

    def test_live_exit_obeys_direction_and_can_confirm_existing_vehicle(self):
        data = self.live_frame('exit').json
        self.assertFalse(data['can_confirm'])
        self.assertIn('Không tìm thấy xe', data['html'])
        self.park()
        data = self.live_frame('exit').json
        self.assertTrue(data['can_confirm'])
        self.assertIn('XE RA BÃI', data['html'])
        self.assertEqual(self.confirm('/exit', data['token']).status_code, 302)
        self.assertEqual(database.count_open(), 0)

    def test_low_confidence_plate_keeps_scanning_and_returns_timing(self):
        values = ('51F-12345', self.frame, (10, 10, 100, 40), 200, 80,
                  dict(confidence=0.4, elapsed_ms=123, engine='easyocr'))
        with patch.object(self.module, 'recognize_plate_live', return_value=values):
            data = self.live_frame().json
        self.assertFalse(data['valid'])
        self.assertEqual(data['elapsed_ms'], 123)
        self.assertEqual(data['confidence'], 0.4)
        self.assertFalse(data['can_confirm'])
        self.assertEqual(data['checked_plate'], '')
        self.assertEqual(database.count_open(), 0)

    def test_capture_requests_accurate_camera_profile_without_creating_entry(self):
        with patch.object(self.module,'recognize_plate_live',return_value=('51F-12345',self.frame,(10,10,100,40),200,80,
                          dict(confidence=0.95,elapsed_ms=100,engine='easyocr-rows'))) as recognize:
            response=self.client.post('/gate/entry/camera',data={'profile':'capture','image':(BytesIO(self.jpg),'capture.jpg')})
        self.assertEqual(response.status_code,200)
        self.assertTrue(recognize.call_args.kwargs['accurate'])
        self.assertEqual(database.count_open(),0)
        self.assertEqual(self.client.post('/gate/entry/camera',data={'profile':'invalid'}).status_code,400)

    def test_live_discard_cleans_temporary_frames_only(self):
        first = self.live_frame().json
        second = self.live_frame().json
        self.assertNotEqual(first['token'], second['token'])
        response = self.client.post('/gate/entry/camera', data={'action': 'discard', 'token': first['token']})
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(self.module.find_tmp(first['token']))
        self.assertIsNotNone(self.module.find_tmp(second['token']))
        self.assertEqual(database.get_all_records(), [])

    def test_live_rejects_invalid_frame_and_releases_ocr_lock(self):
        before = set(Path(config.TMP_DIR).iterdir())
        with patch.object(self.module, 'recognize_plate_live', side_effect=ValueError('invalid image')):
            response = self.live_frame()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(Path(config.TMP_DIR).iterdir()), before)
        self.assertEqual(self.live_frame().status_code, 200)

    def test_live_ocr_busy_retries_without_creating_temporary_files(self):
        before = set(Path(config.TMP_DIR).iterdir())
        with self.module.CAMERA_OCR_LOCK:
            response = self.live_frame()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(set(Path(config.TMP_DIR).iterdir()), before)

    def test_entry_and_exit_lanes_scan_without_blocking_each_other(self):
        # Làn vào đang giữ khóa làn của nó -> làn ra vẫn quét được; chỉ chính làn vào bị từ chối.
        with self.module.LANE_OCR_LOCKS['entry']:
            self.assertEqual(self.live_frame('entry').status_code, 429)
            self.assertEqual(self.live_frame('exit').status_code, 200)
        self.assertEqual(self.live_frame('entry').status_code, 200)

    def test_capture_waits_for_shared_ocr_instead_of_failing(self):
        import threading
        self.module.CAMERA_OCR_LOCK.acquire()
        threading.Timer(0.3, self.module.CAMERA_OCR_LOCK.release).start()
        response = self.live_frame('exit', profile='capture')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.module.LANE_OCR_LOCKS['exit'].locked())

    def test_live_unclear_plate_can_be_corrected_manually(self):
        with patch.object(self.module, 'recognize_plate_live', return_value=('', self.frame, None, 200, 80,
                          dict(confidence=0, elapsed_ms=200, engine='easyocr'))):
            data = self.live_frame().json
        self.assertFalse(data['valid'])
        self.assertFalse(data['can_confirm'])
        self.assertIsNotNone(self.module.find_tmp(data['token']))
        response = self.client.post('/entry', data={
            'action': 'recognize', 'source': 'camera', 'token': data['token'], 'plate': '51F-12345',
        })
        self.assertIn('XE VÀO BÃI', response.text)

    def test_live_validates_upload_and_staff_access(self):
        self.assertEqual(self.client.post('/gate/entry/camera').status_code, 400)
        self.assertEqual(self.live_frame('invalid').status_code, 404)
        with self.client.session_transaction() as session:
            session['role'] = 'user'
        self.assertEqual(self.live_frame().status_code, 302)

    def test_camera_confirmation_controls_share_the_form_across_both_columns(self):
        class Controls(HTMLParser):
            def __init__(self):
                super().__init__()
                self.form = None
                self.sections = []
                self.found = []
                self.select = None
                self.slot_values = []

            def handle_starttag(self, tag, attributes):
                attrs = dict(attributes)
                if tag == 'form':
                    self.form = attrs.get('id')
                elif tag == 'section':
                    self.sections.append(attrs.get('class', '').split())
                if tag == 'select':
                    self.select = attrs.get('id')
                elif tag == 'option' and self.select == 'slot-name' and attrs.get('value'):
                    self.slot_values.append(attrs['value'])
                if tag in ('input', 'select', 'button'):
                    self.found.append((attrs, self.form, self.sections[-1] if self.sections else []))

            def handle_endtag(self, tag):
                if tag == 'form':
                    self.form = None
                elif tag == 'section':
                    self.sections.pop()
                if tag == 'select':
                    self.select = None

        database.set_user_setting(1, 'entry_mode', 'manual')
        data = self.live_frame().json
        response = self.client.post('/entry', data={
            'source': 'camera', 'action': 'recognize', 'token': data['token'], 'plate': data['plate'],
        })
        controls = Controls()
        controls.feed(response.text)
        by_id = {attrs.get('id'): (attrs, form, section) for attrs, form, section in controls.found}
        for key in ('image', 'image-recognize-button'):
            self.assertEqual(by_id[key][1], 'gate-form')
            self.assertIn('gate-media', by_id[key][2])
        for key in ('note', 'plate', 'vehicle_type_id', 'slot-name', 'confirm-button'):
            self.assertEqual(by_id[key][1], 'gate-form')
            self.assertIn('gate-details', by_id[key][2])
        self.assertEqual(by_id['source-select'][0]['type'], 'hidden')
        self.assertEqual(by_id['source-select'][0]['value'], 'camera')
        self.assertEqual(by_id['gate-token'][0]['value'], data['token'])
        self.assertEqual(by_id['confirm-button'][0]['name'], 'action')
        self.assertEqual(by_id['confirm-button'][0]['value'], 'confirm')
        self.assertIn('required', by_id['slot-name'][0])
        self.assertEqual(len(controls.slot_values), len(database.DEFAULT_AREAS) * database.SLOTS_PER_AREA)
        source_buttons = [attrs for attrs, _, _ in controls.found if 'data-source' in attrs]
        self.assertEqual(len(source_buttons), 2)
        self.assertTrue(all(attrs['type'] == 'button' for attrs in source_buttons))

    def test_system_settings_vietqr_configuration_and_gate_reflection(self):
        # 1. Access Settings -> section=payment
        page = self.client.get('/settings?section=payment')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Thanh toán &amp; VietQR', page.text)
        self.assertIn('name="vietqr_account_number"', page.text)

        # 2. Save custom bank account
        save_resp = self.client.post('/settings?section=payment', data={
            'setting_type': 'payment',
            'vietqr_bank_bin': '970436', # Vietcombank
            'vietqr_bank_name': 'Vietcombank',
            'vietqr_account_number': '0011002233445',
            'vietqr_account_name': 'BAI XE TRUNG TAM',
            'vietqr_template': 'compact2',
        })
        self.assertEqual(save_resp.status_code, 302)
        self.assertIn('/settings?section=payment', save_resp.location)

        # 3. Check values stored in database
        self.assertEqual(database.get_setting('vietqr_bank_bin'), '970436')
        self.assertEqual(database.get_setting('vietqr_account_number'), '0011002233445')
        self.assertEqual(database.get_setting('vietqr_account_name'), 'BAI XE TRUNG TAM')

        # 4. Check Exit Gate reflects custom VietQR settings
        self.park(plate='51K-99999')
        preview, token = self.recognize('/exit', plate='51K-99999')
        self.assertIn('data-vietqr-bin="970436"', preview.text)
        self.assertIn('data-vietqr-account="0011002233445"', preview.text)
        self.assertIn('data-vietqr-name="BAI XE TRUNG TAM"', preview.text)

    def test_exit_lane_has_confirm_and_pay_buttons_and_pay_redirects_to_invoice_print(self):
        self.park()
        preview, token = self.recognize('/exit')
        self.assertIn('id="confirm-button"', preview.text)
        self.assertIn('id="pay-button"', preview.text)
        self.assertIn('value="pay"', preview.text)
        self.assertIn('btn-exit-pay', preview.text)
        self.assertIn('btn-exit-confirm', preview.text)

        # Action: pay -> closes record and redirects back to exit gate with print_invoice to trigger print directly without leaving gate
        response = self.client.post('/exit', data={
            'action': 'pay', 'source': 'camera', 'token': token,
            'plate': '51F-12345', 'checked_plate': '51F-12345', 'payment_method': 'cash',
        })
        self.assertEqual(response.status_code, 302)
        record = database.find_open_record('51F-12345')
        self.assertIsNone(record)
        closed_records = self.module.parking_invoices.get_invoices('admin', 1)
        invoice = next(r for r in closed_records if r['plate_number'] == '51F-12345')
        self.assertIn(f"/exit?source=camera&print_invoice={invoice['id']}", response.location)

        # The exit gate page loads with hidden print frame for the invoice, staying right on the gate
        gate_page = self.client.get(response.location)
        self.assertEqual(gate_page.status_code, 200)
        self.assertIn(f'id="invoice-print-frame"', gate_page.text)
        self.assertIn(f"/invoices/{invoice['id']}/print?autoprint=1", gate_page.text)

        # And the printable invoice endpoint still has the print script
        print_page = self.client.get(f"/invoices/{invoice['id']}/print?autoprint=1")
        self.assertEqual(print_page.status_code, 200)
        self.assertIn('PHIẾU THU PHÍ GỬI XE', print_page.text)
        self.assertIn('window.print()', print_page.text)

    def test_gate_lanes_renders_kpi_lanes_and_active_vehicles(self):
        database.create_parking_entry('51F-88888', 'in_test.jpg', 'A01', 1, 'Ô tô')
        res = self.client.get('/gate/lanes')
        self.assertEqual(res.status_code, 200)
        self.assertIn('LÀN VÀO', res.text)
        self.assertIn('LÀN RA', res.text)
        self.assertIn('data-lane-form="entry"', res.text)
        self.assertIn('data-lane-form="exit"', res.text)
        self.assertIn('51F-88888', res.text)
        self.assertIn('lanes-kpi-bar', res.text)
        self.assertIn('lanes-activity', res.text)

        # Inline confirm without token returns JSON error without redirecting away
        inline_err = self.client.post('/entry', data={'inline': '1', 'action': 'confirm'})
        self.assertEqual(inline_err.status_code, 200)
        payload = inline_err.get_json()
        self.assertFalse(payload['ok'])
        self.assertIn('Chưa có ảnh', payload['message'])

    def test_settings_devices_section_saves_cameras(self):
        page = self.client.get('/settings?section=devices')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Camera, Barrier &amp; Máy in', page.text)
        self.assertIn('entry_barrier_port', page.text)
        self.assertIn('printer_port', page.text)

        res = self.client.post('/settings?section=devices', data={
            'setting_type': 'devices',
            'entry_plate_camera': 'cam-in-plate-01',
            'entry_overview_camera': 'cam-in-view-01',
            'exit_plate_camera': 'cam-out-plate-01',
            'exit_overview_camera': 'cam-out-view-01',
            'entry_barrier_port': 'COM8',
            'exit_barrier_port': 'COM9',
            'barrier_baudrate': '115200',
            'auto_open_barrier': '1',
            'printer_port': 'USB 80mm',
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('cam-in-plate-01', res.text)
        self.assertIn('cam-out-view-01', res.text)
        self.assertIn('COM8', res.text)
        self.assertIn('USB 80mm', res.text)

        lanes = self.client.get('/gate/lanes')
        self.assertIn('data-default-device="cam-in-plate-01"', lanes.text)
        self.assertIn('data-default-device="cam-out-view-01"', lanes.text)

    def test_settings_store_info_and_zones_management(self):
        store_page = self.client.get('/settings?section=store')
        self.assertEqual(store_page.status_code, 200)
        self.assertIn('Thông tin bãi xe', store_page.text)

        res_store = self.client.post('/settings?section=store', data={
            'setting_type': 'store',
            'store_name': 'Bãi Xe Số 1',
            'store_phone': '0988777666',
            'store_email': 'baixe1@example.com',
            'store_type': 'Bãi xe ô tô & xe máy',
            'store_address': '100 Lê Lợi',
            'store_province': 'TP. Hồ Chí Minh',
            'store_district': 'Quận 1',
            'store_ward': 'Phường Bến Thành',
        }, follow_redirects=True)
        self.assertEqual(res_store.status_code, 200)
        self.assertIn('Bãi Xe Số 1', res_store.text)
        self.assertIn('0988777666', res_store.text)

        zones_page = self.client.get('/settings?section=zones')
        self.assertEqual(zones_page.status_code, 200)
        self.assertNotIn('section=zones', zones_page.text)
        self.assertNotIn('id="kv-sec-zones"', zones_page.text)

        res_add = self.client.post('/settings/zones/save', data={
            'name': 'Cổng 3',
            'zone_type': 'gate_in',
            'location': 'Bãi xe trung tâm',
            'capacity': '60',
            'status': 'active',
            'note': 'Làn xe máy giờ cao điểm',
        }, follow_redirects=True)
        self.assertEqual(res_add.status_code, 200)
        zone = [z for z in database.get_parking_zones() if z['name'] == 'Cổng 3'][0]
        self.assertEqual(zone['location'], 'Bãi xe trung tâm')
        self.client.post(f"/settings/zones/{zone['id']}/toggle", follow_redirects=True)
        toggled = [z for z in database.get_parking_zones() if z['id'] == zone['id']][0]
        self.assertEqual(toggled['status'], 'inactive')

        self.client.post(f"/settings/zones/{zone['id']}/delete", follow_redirects=True)
        self.assertFalse(any(z['id'] == zone['id'] for z in database.get_parking_zones()))

    def test_settings_gates_section_crud_and_lane_types(self):
        gates_page = self.client.get('/settings?section=gates')
        self.assertEqual(gates_page.status_code, 200)
        self.assertIn('Cài đặt cổng', gates_page.text)
        self.assertIn('id="kv-sec-gates"', gates_page.text)

        for name, lane_type in (('Cổng Vào 1', 'gate_in'), ('Cổng Ra 1', 'gate_out'), ('Cổng Phụ', 'gate_inout')):
            res = self.client.post('/settings/zones/save', data={
                'name': name,
                'zone_type': lane_type,
                'location': 'Bãi xe trung tâm',
                'status': 'active',
            }, follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            self.assertIn(name, res.text)

        filtered = self.client.get('/settings?section=gates&lane_type=gate_inout')
        self.assertEqual(filtered.status_code, 200)
        self.assertIn('<strong>Cổng Phụ</strong>', filtered.text)
        self.assertNotIn('<strong>Cổng Vào 1</strong>', filtered.text)

        main_gate = [z for z in database.get_parking_zones() if z['name'] == 'Cổng Phụ'][0]
        self.client.post('/settings/zones/save', data={
            'zone_id': str(main_gate['id']),
            'name': 'Cổng Phụ A',
            'zone_type': 'gate_in',
            'location': 'Bãi xe trung tâm',
            'status': 'active',
        }, follow_redirects=True)
        updated = [z for z in database.get_parking_zones() if z['id'] == main_gate['id']][0]
        self.assertEqual(updated['name'], 'Cổng Phụ A')
        self.assertEqual(updated['zone_type'], 'gate_in')

        # Select this gate-in-only gate via topbar selector and verify /gate/lanes shows only entry lane
        sel_res = self.client.post('/gate/select', data={'gate_id': str(main_gate['id'])}, follow_redirects=True)
        self.assertEqual(sel_res.status_code, 200)
        lanes_in = self.client.get('/gate/lanes')
        self.assertEqual(lanes_in.status_code, 200)
        self.assertIn('data-lane-form="entry"', lanes_in.text)
        self.assertNotIn('data-lane-form="exit"', lanes_in.text)

        # Switch to gate-out-only gate and verify /gate/lanes shows only exit lane
        out_gate = [z for z in database.get_parking_zones() if z['name'] == 'Cổng Ra 1'][0]
        self.client.post('/gate/select', data={'gate_id': str(out_gate['id'])})
        lanes_out = self.client.get('/gate/lanes')
        self.assertEqual(lanes_out.status_code, 200)
        self.assertNotIn('data-lane-form="entry"', lanes_out.text)
        self.assertIn('data-lane-form="exit"', lanes_out.text)

        # Gate-specific statistics vs Cổng chính (all gates)
        vt = database.get_vehicle_types()[0]
        r1, _ = database.create_parking_entry('51A-11111', 'in1.jpg', None, vt['id'], vt['name'], entry_gate='Cổng Phụ A')
        database.close_record(r1, 'out1.jpg', 15000, exit_gate='Cổng Ra 1')
        r2, _ = database.create_parking_entry('51A-22222', 'in2.jpg', None, vt['id'], vt['name'], entry_gate='Cổng Vào 1')
        database.close_record(r2, 'out2.jpg', 25000, exit_gate='Cổng Vào 1')

        from datetime import date
        today_str = date.today().isoformat()
        all_stats = database.get_statistics(today_str, today_str)
        gate_a_stats = database.get_statistics(today_str, today_str, gate_name='Cổng Phụ A')
        gate_out_stats = database.get_statistics(today_str, today_str, gate_name='Cổng Ra 1')
        self.assertEqual(all_stats['period_entries'], 2)
        self.assertEqual(gate_a_stats['period_entries'], 1)
        self.assertEqual(gate_a_stats['period_exits'], 0)
        self.assertEqual(gate_out_stats['period_exits'], 1)
        self.assertEqual(gate_out_stats['period_parking_revenue'], 15000)

        # Reset back to Trung tâm (gate_id=0) and also allow selecting Cổng chính (gate_id=-1)
        main_res = self.client.post('/gate/select', data={'gate_id': '-1'}, follow_redirects=True)
        self.assertEqual(main_res.status_code, 200)
        self.assertIn('<span class="gate-pill-text">Cổng chính</span>', main_res.text)
        reset_res = self.client.post('/gate/select', data={'gate_id': '0'}, follow_redirects=True)
        self.assertEqual(reset_res.status_code, 200)
        self.assertIn('<span class="gate-pill-text">Tất cả các cổng</span>', reset_res.text)

    def test_settings_gates_central_branch_and_operating_hours(self):
        page = self.client.get('/settings?section=gates')
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-gate-row="central"', page.text)
        self.assertIn('<strong>Cổng chính</strong>', page.text)
        self.assertIn('data-detail-tab="info"', page.text)
        self.assertIn('data-detail-tab="staff"', page.text)
        self.assertIn('Gợi ý', page.text)

        # Update Cổng chính central gate settings directly (zone_id=0, is_central=1)
        central_res = self.client.post('/settings/zones/save', data={
            'zone_id': '0',
            'is_central': '1',
            'name': 'Cổng chính',
            'zone_type': 'gate_inout',
            'location': 'Khu trung tâm tầng 1',
            'operating_hours': '05:00 - 23:30',
            'note': 'Xử lý trung tâm chính',
        }, follow_redirects=True)
        self.assertEqual(central_res.status_code, 200)
        self.assertIn('Khu trung tâm tầng 1', central_res.text)
        self.assertIn('05:00 - 23:30', central_res.text)
        self.assertIn('Xử lý trung tâm chính', central_res.text)

        # Clearing Cổng chính note must persist as empty instead of reverting to default
        clear_note = self.client.post('/settings/zones/save', data={
            'zone_id': '0',
            'is_central': '1',
            'name': 'Cổng chính',
            'zone_type': 'gate_inout',
            'location': 'Khu trung tâm tầng 1',
            'operating_hours': '05:00 - 23:30',
            'note': '',
        }, follow_redirects=True)
        self.assertEqual(clear_note.status_code, 200)
        self.assertNotIn('Xử lý trung tâm chính', clear_note.text)
        self.assertNotIn('Cổng mặc định của bãi xe.', clear_note.text)

        # Reject creating duplicate custom gates named "Trung tâm" or "Cổng chính"
        dup_res = self.client.post('/settings/zones/save', data={
            'name': 'Cổng chính',
            'zone_type': 'gate_inout',
            'status': 'active',
        }, follow_redirects=True)
        self.assertEqual(dup_res.status_code, 200)
        self.assertFalse(any(z['name'].lower() == 'cổng chính' for z in database.get_parking_zones()))

        # Save custom gate with operating_hours and multiple vehicle_type_ids (2-wheelers)
        vts = database.get_vehicle_types()
        vt_ids = [str(vt['id']) for vt in vts[:2]]
        save_res = self.client.post('/settings/zones/save', data={
            'name': 'Cổng Đông',
            'zone_type': 'gate_in',
            'location': 'Mặt tiền đường A',
            'operating_hours': '06:00 - 22:00',
            'vehicle_type_ids': vt_ids,
            'status': 'active',
        }, follow_redirects=True)
        self.assertEqual(save_res.status_code, 200)
        self.assertIn('06:00 - 22:00', save_res.text)
        self.assertIn(vts[0]['name'], save_res.text)
        self.assertIn(vts[1]['name'], save_res.text)
        gate = [z for z in database.get_parking_zones() if z['name'] == 'Cổng Đông'][0]
        self.assertEqual(gate['operating_hours'], '06:00 - 22:00')
        self.assertEqual(gate['vehicle_type_ids'], ','.join(vt_ids))

    def test_dashboard_multi_gate_filter_and_api(self):
        database.save_parking_zone(None, 'Cổng Đông', 'gate_inout', 'Mặt tiền', None, 0, 'active', '')
        vt = database.get_vehicle_types()[0]
        r1, _ = database.create_parking_entry('51A-33333', 'in3.jpg', None, vt['id'], vt['name'], entry_gate='Cổng Đông')
        database.close_record(r1, 'out3.jpg', 20000, exit_gate='Cổng Đông')
        r2, _ = database.create_parking_entry('51A-44444', 'in4.jpg', None, vt['id'], vt['name'], entry_gate=None)
        database.close_record(r2, 'out4.jpg', 10000, exit_gate=None)

        dash_page = self.client.get('/')
        self.assertEqual(dash_page.status_code, 200)
        self.assertIn('id="kv-dash-gate-filter"', dash_page.text)
        self.assertIn('id="kv-dash-gate-reset"', dash_page.text)
        self.assertIn('Đặt lại', dash_page.text)
        self.assertIn('data-gate-option="Cổng chính"', dash_page.text)
        self.assertNotIn('data-gate-option="Tất cả các cổng"', dash_page.text)
        self.assertIn('data-gate-option="Cổng Đông"', dash_page.text)

        api_east = self.client.get('/api/dashboard?gates=Cổng Đông&range=today')
        self.assertEqual(api_east.status_code, 200)
        self.assertEqual(api_east.json['stats']['period_parking_revenue'], 20000)
        self.assertEqual(len(api_east.json['recent_records']), 1)

        api_central = self.client.get('/api/dashboard?gates=Cổng chính&range=today')
        self.assertEqual(api_central.status_code, 200)
        self.assertEqual(api_central.json['stats']['period_parking_revenue'], 10000)

        api_all = self.client.get('/api/dashboard?gates=all&range=today')
        self.assertEqual(api_all.status_code, 200)
        self.assertEqual(api_all.json['stats']['period_parking_revenue'], 30000)

        api_none = self.client.get('/api/dashboard?gates=none&range=today')
        self.assertEqual(api_none.status_code, 200)
        self.assertEqual(api_none.json['stats']['period_parking_revenue'], 0)
        self.assertEqual(api_none.json['recent_records'], [])
        self.assertEqual(api_none.json['counts']['total'], 0)
        self.assertEqual(api_none.json['area_stats'], {})

        # Gate with area_names='A' must filter dashboard counts & area_stats to only Khu A
        database.save_parking_zone(None, 'Cổng Khu A', 'gate_inout', 'Khu A', None, 0, 'active', '', area_names='A')
        api_a = self.client.get('/api/dashboard?gates=Cổng Khu A&range=today')
        self.assertEqual(api_a.status_code, 200)
        self.assertEqual(list(api_a.json['area_stats'].keys()), ['A'])
        self.assertEqual(api_a.json['counts']['total'], api_a.json['area_stats']['A']['total'])

    def test_parking_layout_and_gate_scoped_areas(self):
        database.save_parking_zone(None, 'Cổng Tây', 'gate_inout', 'Cổng phụ', None, 0, 'active', '', area_names='A')
        west = [z for z in database.get_parking_zones() if z['name'] == 'Cổng Tây'][0]

        # Trung tâm (gate_id=0) shows all areas A, B, C
        self.client.post('/gate/select', data={'gate_id': '0'})
        all_page = self.client.get('/parking')
        self.assertEqual(all_page.status_code, 200)
        self.assertIn('id="kv-parking-search"', all_page.text)
        self.assertIn('Khu A', all_page.text)
        self.assertIn('Khu B', all_page.text)

        # Select Cổng Tây from top-right -> /parking shows only Khu A
        self.client.post('/gate/select', data={'gate_id': str(west['id'])})
        west_page = self.client.get('/parking')
        self.assertEqual(west_page.status_code, 200)
        self.assertIn('Cổng Tây', west_page.text)
        west_norm = west_page.text.replace(' style="margin:0;font-size:17px;font-weight:650;"', '')
        self.assertIn('<h2>Khu A</h2>', west_norm)
        self.assertNotIn('<h2>Khu B</h2>', west_norm)

        # Update gate areas from /parking/gate-areas to B,C
        upd = self.client.post('/parking/gate-areas', data={'area_names': ['B', 'C']}, follow_redirects=True)
        self.assertEqual(upd.status_code, 200)
        upd_norm = upd.text.replace(' style="margin:0;font-size:17px;font-weight:650;"', '')
        self.assertIn('<h2>Khu B</h2>', upd_norm)
        self.assertIn('<h2>Khu C</h2>', upd_norm)
        self.assertNotIn('<h2>Khu A</h2>', upd_norm)

        # Export Excel (.xlsx)
        exp = self.client.get('/parking/export')
        self.assertEqual(exp.status_code, 200)
        self.assertIn('spreadsheetml', exp.content_type)

        # Creating a new area while Cổng Tây is active attaches it to Cổng Tây automatically
        self.client.post('/gate/select', data={'gate_id': str(west['id'])})
        new_area_res = self.client.post('/parking/areas/save', data={
            'name': 'VIP',
            'slot_count': '2',
            'vehicle_type_id': 'all',
            'note': 'Khu VIP cổng tây',
        }, follow_redirects=True)
        self.assertEqual(new_area_res.status_code, 200)
        self.assertIn('Khu VIP', new_area_res.text)
        self.assertIn('Khu VIP cổng tây', new_area_res.text)

        # Vehicle types setup inside /pricing (2w / 4w / other) and removed from /settings
        settings_page = self.client.get('/settings')
        self.assertNotIn('section=vehicles', settings_page.text)
        self.assertNotIn('Bảng giá &amp; Gói vé', settings_page.text)
        vpage = self.client.get('/pricing')
        self.assertEqual(vpage.status_code, 200)
        self.assertIn('Phân loại nhóm', vpage.text)
        vsave = self.client.post('/pricing/type/save', data={
            'name': 'Xe bán tải',
            'wheel_group': '4w',
            'free_minutes': '10',
            'monthly_price': '1200000',
        }, follow_redirects=True)
        self.assertEqual(vsave.status_code, 200)
        self.assertIn('Xe bán tải', vsave.text)
        self.assertIn('Xe 4 bánh', vsave.text)
        created_vt = [v for v in database.get_vehicle_types() if v['name'] == 'Xe bán tải'][0]
        self.assertEqual(created_vt['wheel_group'], '4w')

        # Gate with vehicle_type_id and no area_names must also render /parking cleanly
        vt = database.get_vehicle_types()[0]
        database.save_parking_zone(None, 'Cổng Xe Máy', 'gate_inout', 'Cổng phụ', vt['id'], 0, 'active', '')
        moto_gate = [z for z in database.get_parking_zones() if z['name'] == 'Cổng Xe Máy'][0]
        self.client.post('/gate/select', data={'gate_id': str(moto_gate['id'])})
        self.assertEqual(self.client.get('/parking').status_code, 200)


if __name__ == '__main__':
    unittest.main()
