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
    def test_plate_region_prefers_character_rows_over_larger_vehicle_rectangles(self):
        image = np.full((720,1280,3),75,np.uint8)
        cv2.rectangle(image,(170,70),(1110,280),(220,220,220),-1)
        for y in range(90,260,25):
            cv2.line(image,(190,y),(1090,y),(90,90,90),5)
        cv2.rectangle(image,(420,400),(860,540),(235,235,235),-1)
        cv2.rectangle(image,(425,405),(855,535),(30,30,30),2)
        cv2.putText(image,'18A-12345',(437,497),cv2.FONT_HERSHEY_SIMPLEX,1.9,(15,15,15),4,cv2.LINE_AA)
        regions = prep.plate_regions(image)
        self.assertTrue(regions)
        self.assertGreater(prep._region_overlap(regions[0],(420,400,440,140)),0.60)

    def test_plain_windows_and_bright_backgrounds_are_not_plate_regions(self):
        image = np.full((720,1280,3),80,np.uint8)
        cv2.rectangle(image,(200,200),(1050,500),(230,230,230),-1)
        self.assertEqual(prep.plate_regions(image),[])

    def test_tilted_character_rows_are_checked_after_geometric_rectification(self):
        image=np.full((720,1280,3),80,np.uint8)
        cv2.rectangle(image,(380,280),(900,450),(240,240,240),-1)
        cv2.putText(image,'51F-12345',(405,395),cv2.FONT_HERSHEY_SIMPLEX,2.5,(15,15,15),5)
        for angle in (12,-18):
            tilted=cv2.warpAffine(image,cv2.getRotationMatrix2D((640,360),angle,1),(1280,720),borderValue=(80,80,80))
            self.assertTrue(prep.plate_regions(tilted),angle)

    def test_plate_regions_accept_two_rows_and_keep_bounds_inside_image(self):
        image = np.full((480,640,3),80,np.uint8)
        cv2.rectangle(image,(180,100),(460,330),(240,240,240),-1)
        cv2.putText(image,'29-L1',(210,185),cv2.FONT_HERSHEY_SIMPLEX,1.4,(15,15,15),3)
        cv2.putText(image,'123.45',(190,290),cv2.FONT_HERSHEY_SIMPLEX,1.4,(15,15,15),3)
        regions = prep.plate_regions(image)
        self.assertTrue(regions)
        for x,y,w,h in regions:
            self.assertGreaterEqual(min(x,y),0)
            self.assertLessEqual(x+w,640)
            self.assertLessEqual(y+h,480)

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
