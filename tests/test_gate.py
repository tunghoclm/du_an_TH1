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
        self.assertEqual(database.count_open(), 0)

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
        self.assertEqual(len(controls.slot_values), 60)
        source_buttons = [attrs for attrs, _, _ in controls.found if 'data-source' in attrs]
        self.assertEqual(len(source_buttons), 2)
        self.assertTrue(all(attrs['type'] == 'button' for attrs in source_buttons))


if __name__ == '__main__':
    unittest.main()
