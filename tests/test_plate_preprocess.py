"""Geometry regressions for clipped edges and two-row plate segmentation."""
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py'))
import plate_preprocess as prep
from plate_utils import assemble_plate, is_valid_plate_format


class PlatePreprocessTests(unittest.TestCase):
    def test_two_rows_keep_leading_zero_in_recognition_box(self):
        frame = np.full((260, 420, 3), 240, np.uint8)
        cv2.putText(frame, '15-P1', (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (10, 10, 10), 4)
        cv2.putText(frame, '037.37', (25, 220), cv2.FONT_HERSHEY_SIMPLEX, 2, (10, 10, 10), 4)
        boxes = prep.text_rows(frame)
        self.assertIsNotNone(boxes)
        self.assertEqual(len(boxes), 2)
        self.assertLess(boxes[1][0], 30)
        rightmost_ink = np.where(frame[150:, :, 0] < 128)[1].max()
        self.assertGreater(boxes[1][1], rightmost_ink)

    def test_rotation_expands_canvas_and_preserves_edge_characters(self):
        frame = np.full((100, 400, 3), 240, np.uint8)
        cv2.putText(frame, '03737', (1, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
        rotated = prep._rotate(frame, 25)
        self.assertGreater(rotated.shape[0], frame.shape[0])
        self.assertGreater(np.count_nonzero(rotated[:, :, 0] < 128),
                           np.count_nonzero(frame[:, :, 0] < 128) * 0.9)

    def test_incomplete_border_is_not_used_as_a_perspective_crop(self):
        frame = np.full((200, 400, 3), 50, np.uint8)
        cv2.rectangle(frame, (40, 30), (360, 230), (240, 240, 240), -1)
        self.assertIsNone(prep._plate_quad(frame, strict=True))

    def test_rectification_recovers_bottom_outside_tight_detector_box(self):
        frame = np.full((600, 800, 3), 60, np.uint8)
        corners = np.array([[200, 160], [580, 100], [600, 390], [170, 420]], np.int32)
        cv2.fillConvexPoly(frame, corners, (240, 240, 240))
        cv2.putText(frame, '03737', (205, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (10, 10, 10), 3)
        found = prep.rectify_detected(frame, (180, 120, 400, 240))
        self.assertIsNotNone(found)
        crop, (x, y, w, h) = found
        self.assertGreater(y + h, 410)
        self.assertGreater(w, 400)
        self.assertGreater(crop.size, 0)

    def test_two_line_car_and_two_letter_series_are_accepted(self):
        for rows in (['51F', '123.45'], ['29AB', '12345'], ['15-P1', '037.37']):
            self.assertTrue(is_valid_plate_format(assemble_plate(rows), rows=2))
