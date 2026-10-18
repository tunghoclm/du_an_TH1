"""
plate_preprocess.py
Tiền xử lý VÙNG BIỂN SỐ đã được cắt ra (bởi YOLOv8 hoặc contour) trước khi đưa vào OCR:
  1. Tăng độ tương phản (CLAHE) — chỉ khi ảnh thiếu tương phản.  (enhance)
  2. Xoay thẳng (deskew) — TÙY CHỌN.                          (straighten / prepare)

Lưu ý: thử nghiệm thực tế cho thấy EasyOCR vốn đọc tốt biển bị nghiêng, còn việc xoay/warp
phối cảnh lại dễ làm biến dạng biển xe máy 2 dòng và khiến đọc SAI. Vì vậy pipeline mặc định
CHỈ gọi enhance(); deskew chỉ bật khi đặt biến môi trường PLATE_DESKEW=1 (xem plate_recognition.py).

Xoay thẳng có 2 mức, tự chọn:
  a. Biến đổi phối cảnh 4 điểm (perspective warp): tìm hình tứ giác của biển rồi
     "kéo" thẳng thành hình chữ nhật — xử lý tốt cả ảnh chụp nghiêng gần (close-up).
  b. Chỉ xoay (rotation) theo góc nghiêng ước lượng từ Hough lines: dùng khi không
     tìm được tứ giác biển rõ ràng.

Mọi hàm đều là "best effort": ảnh đã thẳng thì gần như giữ nguyên, không xử lý được
thì bỏ qua (không ném lỗi).
"""

import math

import cv2
import numpy as np

LOW_CONTRAST_STD = 45.0   # độ lệch chuẩn mức xám dưới ngưỡng này mới cần kéo tương phản (CLAHE)
MIN_QUAD_RECT = 0.6       # độ "vuông vắn" tối thiểu để coi một contour là hình biển số


def _order_points(pts):
    """Sắp 4 điểm theo thứ tự trên-trái, trên-phải, dưới-phải, dưới-trái."""
    pts = np.asarray(pts, dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
                    dtype=np.float32)


def _plate_quad(crop):
    """Tìm hình tứ giác bao quanh vùng biển số trong crop (ngưỡng Otsu + contour), bỏ qua
    contour chính là nền/viền ảnh. Trả về (4 điểm, góc nghiêng, tỉ lệ diện tích) hoặc None."""
    h, w = crop.shape[:2]
    img_area = float(h * w)
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, normal = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    best, best_score = None, 0.0
    for binary in (normal, cv2.bitwise_not(normal)):
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area <= 1:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            touches = x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2
            if touches and area > 0.9 * img_area:      # contour chính là nền/viền ảnh -> bỏ
                continue
            center, size, angle = cv2.minAreaRect(c)
            rw, rh = size
            if rw < 5 or rh < 5:
                continue
            rectangularity = area / float(rw * rh)
            if rectangularity < MIN_QUAD_RECT:          # không giống hình chữ nhật -> bỏ
                continue
            score = area * rectangularity
            if score > best_score:
                norm_angle = angle + (90.0 if rw < rh else 0.0)   # góc cạnh dài so với phương ngang
                norm_angle = ((norm_angle + 45.0) % 90.0) - 45.0
                best_score = score
                best = (cv2.boxPoints((center, size, angle)).astype(np.float32),
                        norm_angle, area / img_area)
    return best


def _warp_quad(crop, quad):
    """Biến đổi phối cảnh: "kéo" tứ giác `quad` thành hình chữ nhật thẳng, cắt sát biển."""
    tl, tr, br, bl = _order_points(quad)
    width = int(round(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))))
    height = int(round(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))))
    if width < 10 or height < 5:
        return None
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl], np.float32), dst)
    return cv2.warpPerspective(crop, matrix, (width, height))


def _hough_angle(gray):
    """Góc nghiêng (độ) từ Hough lines — hướng các đường gần nằm ngang. None nếu không có."""
    edges = cv2.Canny(gray, 60, 180)
    min_len = max(20, int(gray.shape[1] * 0.25))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180.0,
                            threshold=max(25, int(gray.shape[1] * 0.2)),
                            minLineLength=min_len, maxLineGap=10)
    if lines is None:
        return None
    angles = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        a = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if abs(a) <= 45.0:
            angles.append(a)
        elif abs(a) >= 135.0:
            angles.append(a - 180.0 if a > 0 else a + 180.0)
    return None if not angles else float(np.median(angles))


def _rotate(crop, angle):
    h, w = crop.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    return cv2.warpAffine(crop, matrix, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def straighten(crop, min_angle=1.0):
    """Đưa vùng biển số về nằm ngang.
    - Nếu tìm được tứ giác biển RÕ RÀNG (nghiêng, hoặc chỉ chiếm một phần ảnh) -> warp phối cảnh.
    - Ngược lại (biển đã thẳng và lấp kín crop) -> chỉ xoay nhẹ theo góc Hough nếu cần."""
    quad = _plate_quad(crop)
    if quad is not None:
        box, angle, area_frac = quad
        if abs(angle) >= min_angle or area_frac < 0.5:    # biển nghiêng, hoặc chỉ chiếm phần nhỏ crop
            warped = _warp_quad(crop, box)
            if warped is not None:
                return warped

    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    angle = _hough_angle(gray)
    if angle is None or abs(angle) < min_angle or abs(angle) > 30.0:
        return crop
    return _rotate(crop, angle)


def enhance(crop):
    """Khử nhiễu nhẹ, và tăng tương phản (CLAHE) CHỈ khi ảnh thiếu tương phản.
    Với ảnh đã đủ nét, kéo tương phản mạnh có thể làm EasyOCR đọc nhầm 1 ký tự.
    Trả về ảnh BGR."""
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 5, 40, 40)     # khử nhiễu nhẹ, giữ cạnh chữ
    if gray.std() < LOW_CONTRAST_STD:               # ảnh mờ/nhạt -> kéo tương phản cục bộ
        gray = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def prepare(crop):
    """Toàn bộ tiền xử lý: xoay thẳng -> tăng tương phản. Trả về ảnh đã xử lý (BGR)."""
    if crop is None or crop.size == 0:
        return crop
    return enhance(straighten(crop))
