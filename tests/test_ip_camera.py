"""Kiểm tra module ip_camera và các endpoint proxy camera IP trong app.py."""
import importlib.util
from pathlib import Path
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
import ip_camera


class _FakeCapture:
    def __init__(self, frame=None, opened=True, reads=3):
        self.frame = frame
        self.opened = opened
        self.reads = reads
        self.released = False

    def set(self, prop, value):
        return True

    def isOpened(self):
        return self.opened

    def read(self):
        if not self.opened or self.frame is None or self.reads <= 0:
            return False, None
        self.reads -= 1
        return True, self.frame

    def release(self):
        self.released = True


class IpCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='parking-ipcam-tests-')
        cls.root = Path(cls.temp.name)
        cls.original_paths = {key: getattr(config, key) for key in ('DB_PATH', 'TMP_DIR', 'IN_DIR', 'OUT_DIR')}
        config.DB_PATH = str(cls.root / 'initial.db')
        database.DB_PATH = config.DB_PATH
        for key in ('TMP_DIR', 'IN_DIR', 'OUT_DIR'):
            path = cls.root / key
            path.mkdir()
            setattr(config, key, str(path))
        cls.frame = np.full((60, 120, 3), 180, dtype=np.uint8)
        recognition = types.ModuleType('plate_recognition')
        recognition.recognize_plate_annotated = lambda path: ('51F-12345', cls.frame)
        recognition.recognize_plate = lambda path: ('51F-12345', cls.frame)
        recognition.recognize_plate_live = lambda path, **kw: (
            '51F-12345', cls.frame, (10, 10, 80, 30), 120, 60,
            dict(confidence=0.95, elapsed_ms=100, engine='easyocr-rows')
        )
        spec = importlib.util.spec_from_file_location('parking_ipcam_test_app', ROOT / 'app.py')
        cls.app_module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'plate_recognition': recognition}):
            spec.loader.exec_module(cls.app_module)
        cls.app = cls.app_module.app
        cls.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        for key, value in cls.original_paths.items():
            setattr(config, key, value)
        database.DB_PATH = config.DB_PATH
        cls.temp.cleanup()

    def setUp(self):
        db_file = self.root / f'{self._testMethodName}.db'
        config.DB_PATH = str(db_file)
        database.DB_PATH = str(db_file)
        database.init_db()
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin'
            sess['full_name'] = 'Quản trị viên'

    def test_url_detection_and_normalization(self):
        self.assertTrue(ip_camera.is_ip_camera_url('http://192.168.1.15:8080/video'))
        self.assertTrue(ip_camera.is_ip_camera_url('rtsp://192.168.1.15:8080/h264_ulaw.sdp'))
        self.assertTrue(ip_camera.is_ip_camera_url('192.168.1.15:8080'))
        self.assertFalse(ip_camera.is_ip_camera_url(''))
        self.assertFalse(ip_camera.is_ip_camera_url('cam-in-plate-01'))
        self.assertFalse(ip_camera.is_ip_camera_url('a9f3b1c2d4e5f6'))

        self.assertEqual(
            ip_camera.normalize_ip_camera_url('192.168.1.15:8080'),
            'http://192.168.1.15:8080/video',
        )
        self.assertEqual(
            ip_camera.normalize_ip_camera_url('http://192.168.1.15:8080/'),
            'http://192.168.1.15:8080/video',
        )
        self.assertEqual(
            ip_camera.normalize_ip_camera_url('http://192.168.1.15:8080/shot.jpg'),
            'http://192.168.1.15:8080/shot.jpg',
        )
        self.assertEqual(
            ip_camera.normalize_ip_camera_url('rtsp://192.168.1.15:8080/h264_ulaw.sdp'),
            'rtsp://192.168.1.15:8080/h264_ulaw.sdp',
        )

    def test_probe_endpoint_and_stream_snapshot(self):
        fake_cap = _FakeCapture(frame=self.frame, opened=True, reads=4)
        with patch.object(ip_camera.cv2, 'VideoCapture', return_value=fake_cap):
            res = self.client.post('/api/camera/test', json={'url': '192.168.1.15:8080'})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data['ok'])
            self.assertEqual(data['normalized_url'], 'http://192.168.1.15:8080/video')
            self.assertTrue(fake_cap.released)

        database.set_setting('exit_plate_camera', 'http://192.168.1.15:8080/video')
        snap_cap = _FakeCapture(frame=self.frame, opened=True, reads=2)
        with patch.object(ip_camera.cv2, 'VideoCapture', return_value=snap_cap):
            snap = self.client.get('/gate/camera-snapshot/exit_plate')
            self.assertEqual(snap.status_code, 200)
            self.assertEqual(snap.mimetype, 'image/jpeg')
            self.assertGreater(len(snap.data), 100)
            self.assertTrue(snap_cap.released)

        stream_cap = _FakeCapture(frame=self.frame, opened=True, reads=2)
        with patch.object(ip_camera.cv2, 'VideoCapture', return_value=stream_cap):
            stream = self.client.get('/gate/camera-stream/exit_plate')
            self.assertEqual(stream.status_code, 200)
            self.assertIn('multipart/x-mixed-replace', stream.mimetype)
            self.assertIn(b'--frame', stream.data)

    def test_settings_normalizes_ip_camera_url_only(self):
        res = self.client.post('/settings?section=devices', data={
            'setting_type': 'devices',
            'entry_plate_camera': 'cam-in-plate-01',
            'exit_plate_camera': '192.168.1.20:8080',
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(database.get_setting('entry_plate_camera'), 'cam-in-plate-01')
        self.assertEqual(database.get_setting('exit_plate_camera'), 'http://192.168.1.20:8080/video')


if __name__ == '__main__':
    unittest.main()
