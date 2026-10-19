"""Kiểm tra tọa độ khung camera và ảnh xem trước, không nạp model OCR."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py'))


class PlateLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        easyocr = types.ModuleType('easyocr')
        easyocr.Reader = lambda *args, **kwargs: None
        spec = importlib.util.spec_from_file_location('live_recognition_test_module', ROOT / 'py/plate_recognition.py')
        cls.recognition = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'easyocr': easyocr}):
            spec.loader.exec_module(cls.recognition)

    def test_live_coordinates_remain_in_original_frame_space(self):
        frame = np.zeros((1200, 1600, 3), dtype=np.uint8)
        rect = (100, 200, 600, 250)
        candidate = self.recognition._Cand('51F-12345', 0.95, frame, rect, ['51F-12345'])
        with patch.object(self.recognition, '_run', return_value=(candidate, frame, 200)) as ocr:
            plate, annotated, box, width, height = self.recognition.recognize_plate_live('frame.jpg')
        ocr.assert_called_once_with('frame.jpg', fast=True)
        self.assertEqual((plate, box, width, height), ('51F-12345', rect, 1600, 1200))
        self.assertEqual(annotated.shape[:2], (675, 900))
        self.assertFalse(np.any(frame))  # vẽ khung không sửa ảnh gốc

    def test_uploaded_image_interface_still_returns_two_values(self):
        frame = np.zeros((80, 200, 3), dtype=np.uint8)
        with patch.object(self.recognition, '_recognize', return_value=('', frame, None, frame)):
            plate, annotated = self.recognition.recognize_plate_annotated('frame.jpg')
        self.assertEqual(plate, '')
        np.testing.assert_array_equal(annotated, frame)

    def test_live_details_include_confidence_engine_and_elapsed_time(self):
        p = self.recognition
        frame = np.zeros((80, 200, 3), np.uint8)
        cand = p._Cand('51F-12345', 0.9534, frame, (10, 20, 100, 40), ['51F12345'], 'easyocr-rows')
        with patch.object(p, '_run', return_value=(cand, frame, 175)):
            result = p.recognize_plate_live('frame.jpg', details=True)
        self.assertEqual(result[-1], dict(confidence=0.953, engine='easyocr-rows', elapsed_ms=175))

    def test_clear_rows_bypass_craft_detection(self):
        p = self.recognition
        frame = np.full((100, 400, 3), 240, np.uint8)
        reader = MagicMock()
        reader.recognize.return_value = [([[0, 0], [390, 0], [390, 90], [0, 90]], '51F12345', 0.95)]
        with patch.object(p, '_reader', reader), patch.object(p.plate_preprocess, 'text_rows', return_value=[[0, 390, 0, 90]]):
            result = p._read_crop(frame, (0, 0, 400, 100), fast=True)
        self.assertEqual(result.text, '51F-12345')
        self.assertEqual(result.engine, 'easyocr-rows')
        reader.readtext.assert_not_called()

    def test_live_uses_one_recovery_attempt_instead_of_full_frame_retries(self):
        p = self.recognition
        frame = np.zeros((720, 1280, 3), np.uint8)
        rect = (100, 100, 200, 80)
        uncertain = p._Cand('?', 0.2, frame, rect, ['?'])
        with patch.object(p, '_use_yolo', return_value=True), \
                patch.object(p.plate_yolo, 'detect_best', return_value=rect), \
                patch.object(p.plate_preprocess, 'rectify_detected', return_value=None), \
                patch.object(p.plate_preprocess, 'recovery_variants', return_value=iter([('a', frame), ('b', frame), ('c', frame)])), \
                patch.object(p, '_read_crop', return_value=uncertain) as crop_read, \
                patch.object(p, 'ocr_read') as full_read:
            p._local(frame, fast=True)
        self.assertEqual(crop_read.call_count, 2)
        full_read.assert_not_called()

    def test_recovery_can_replace_incomplete_detection_and_keep_original_coordinates(self):
        p = self.recognition
        frame = np.zeros((2160, 3840, 3), np.uint8)
        rect = (200, 300, 200, 100)
        recovered_rect = (590, 890, 650, 420)
        uncertain = p._Cand('15P', 0.3, frame, None, ['15P'])
        correct = p._Cand('15-P103737', 0.96, frame, recovered_rect, ['15P1', '03737'])
        with patch.object(p, '_use_yolo', return_value=True), \
                patch.object(p.plate_yolo, 'detect_best', return_value=rect), \
                patch.object(p.plate_preprocess, 'rectify_detected', return_value=(frame, recovered_rect)), \
                patch.object(p, '_read_crop', side_effect=[uncertain, correct]):
            result = p._local(frame, fast=True)
        self.assertEqual(result.rect, recovered_rect)
        self.assertEqual(result.text, '15-P103737')

    def test_api_off_never_invokes_network_even_for_uncertain_plate(self):
        p = self.recognition
        frame = np.zeros((80, 200, 3), np.uint8)
        uncertain = p._Cand('', 0, frame, None, [])
        with patch.dict('os.environ', {'PLATE_API_MODE': 'off', 'PLATE_API_TOKEN': 'test-only'}), \
                patch.object(p.cv2, 'imread', return_value=frame), \
                patch.object(p, '_local', return_value=uncertain), patch.object(p.plate_api, 'recognize') as api:
            p._run('frame.jpg')
        api.assert_not_called()

    def test_cloud_only_replaces_local_result_when_valid_and_confident(self):
        p = self.recognition
        frame = np.zeros((80, 200, 3), np.uint8)
        with patch.dict('os.environ', {'PLATE_API_TOKEN': 'test-only', 'PLATE_API_MODE': 'fallback'}), \
                patch.object(p.plate_api, 'recognize', return_value=('51f12345', (10, 10, 100, 40), 0.3)):
            self.assertIsNone(p._recognize_api(frame, 'frame.jpg'))
        with patch.dict('os.environ', {'PLATE_API_TOKEN': 'test-only', 'PLATE_API_MODE': 'fallback'}), \
                patch.object(p.plate_api, 'recognize', return_value=('51f12345', (10, 10, 100, 40), 0.95)):
            result = p._recognize_api(frame, 'frame.jpg')
        self.assertEqual((result.text, result.engine), ('51F-12345', 'plate-recognizer'))

    def test_camera_cloud_requires_explicit_enable(self):
        p = self.recognition
        with patch.dict('os.environ', {'PLATE_API_TOKEN': 'test-only', 'PLATE_API_CAMERA': '0'}), \
                patch.object(p.plate_api, 'recognize') as api:
            self.assertIsNone(p._recognize_api(np.zeros((80, 200, 3), np.uint8), 'frame.jpg', fast=True))
        api.assert_not_called()

    def test_partial_row_detection_falls_back_to_complete_border(self):
        p = self.recognition
        frame = np.zeros((720, 1280, 3), np.uint8)
        row_rect, plate_rect = (400, 400, 220, 50), (400, 220, 420, 280)
        partial = p._Cand('03737', 0.99, frame, row_rect, ['03737'])
        complete = p._Cand('15-P103737', 0.98, frame, plate_rect, ['15P1', '03737'])
        with patch.object(p, '_use_yolo', return_value=True), \
                patch.object(p.plate_yolo, 'detect_best', return_value=row_rect), \
                patch.object(p, '_contour_rect', return_value=plate_rect), \
                patch.object(p, '_read_crop', side_effect=[partial, complete]):
            result = p._local(frame, fast=True)
        self.assertEqual(result.text, '15-P103737')
        self.assertEqual(result.rect, plate_rect)

    def test_api_first_attempts_cloud_only_once_when_no_plate_returned(self):
        p = self.recognition
        frame = np.zeros((80, 200, 3), np.uint8)
        uncertain = p._Cand('', 0, frame, None, [])
        with patch.dict('os.environ', {'PLATE_API_MODE': 'first'}), \
                patch.object(p.cv2, 'imread', return_value=frame), \
                patch.object(p, '_local', return_value=uncertain), \
                patch.object(p, '_recognize_api', return_value=None) as api:
            p._run('frame.jpg')
        api.assert_called_once()


if __name__ == '__main__':
    unittest.main()
