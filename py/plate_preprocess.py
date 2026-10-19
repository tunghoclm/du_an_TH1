"""
plate_preprocess.py
Tiền xử lý VÙNG BIỂN SỐ đã được cắt ra (bởi YOLOv8 hoặc contour) trước khi đưa vào OCR:
  1. Tăng độ tương phản (CLAHE) — chỉ khi ảnh thiếu tương phản.  (enhance)
  2. Xoay thẳng (deskew) — TÙY CHỌN.                          (straighten / prepare)

Ảnh gốc luôn được giữ làm ứng viên. Chỉ thử chỉnh hình học/ánh sáng khi lần đọc
ban đầu chưa đủ tốt; không dùng một phép warp duy nhất thay thế ảnh gốc.

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


def _plate_quad(crop, min_area=0.35, strict=False):
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
            if area < min_area * img_area:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            touches = x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2
            if touches:      # an incomplete border cannot define a safe perspective crop
                continue
            center, size, angle = cv2.minAreaRect(c)
            rw, rh = size
            if rw < 5 or rh < 5:
                continue
            rectangularity = area / float(rw * rh)
            if rectangularity < MIN_QUAD_RECT:          # không giống hình chữ nhật -> bỏ
                continue
            approx = cv2.approxPolyDP(c, 0.025 * cv2.arcLength(c, True), True)
            if strict and (len(approx) != 4 or not cv2.isContourConvex(approx)):
                continue
            score = area * rectangularity
            if score > best_score:
                norm_angle = angle + (90.0 if rw < rh else 0.0)   # góc cạnh dài so với phương ngang
                norm_angle = ((norm_angle + 45.0) % 90.0) - 45.0
                best_score = score
                # Use the actual four corners to correct perspective, not just a
                # rotated rectangle (which only corrects roll).
                points = approx.reshape(4, 2) if len(approx) == 4 and cv2.isContourConvex(approx) else cv2.boxPoints((center, size, angle))
                best = (points.astype(np.float32),
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
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = int(h * sine + w * cosine), int(h * cosine + w * sine)
    matrix[0, 2] += (new_w - w) / 2
    matrix[1, 2] += (new_h - h) / 2
    return cv2.warpAffine(crop, matrix, (new_w, new_h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(220, 220, 220))


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


def rectify_detected(image, rect):
    """Recover complete corners near a tight/incomplete detector box.

    Work on a bounded larger context so a tilted bottom row is not clipped.
    Only a closed, convex four-corner border enclosing the detector center is
    accepted. Return rectified crop and its box in the ORIGINAL image.
    """
    x, y, w, h = rect
    height, width = image.shape[:2]
    # A detector may enclose just one row of a motorcycle plate. Base vertical
    # context on width too, so the other row is still available for recovery.
    vertical = max(h * 0.6, w * 0.5)
    x0, y0 = max(0, int(x - w * 0.45)), max(0, int(y - vertical))
    x1, y1 = min(width, int(x + w * 1.45)), min(height, int(y + h + vertical))
    context = image[y0:y1, x0:x1]
    ratio = min(1.0, 1200 / max(context.shape[:2]))
    small = cv2.resize(context, None, fx=ratio, fy=ratio) if ratio < 1 else context
    found = _plate_quad(small, min_area=0.12, strict=True)
    if found is None:
        return None
    quad = found[0] / ratio
    if cv2.pointPolygonTest(quad, (x + w / 2 - x0, y + h / 2 - y0), False) < 0:
        return None
    warped = _warp_quad(context, quad)
    if warped is None:
        return None
    rx, ry, rw, rh = cv2.boundingRect(quad)
    return warped, (rx + x0, ry + y0, rw, rh)


def text_rows(crop):
    """Find one/two rows of character components inside a detected plate.

    Conservative boxes let the recognizer skip the expensive CRAFT detector.
    Return None when reflections, tilt or background make segmentation uncertain.
    """
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    if h < 25 or w < 70:
        return None
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary)
    chars = []
    for x, y, cw, ch, area in stats[1:count]:
        if (0.10 * h <= ch <= 0.88 * h and 0.005 * w <= cw <= 0.22 * w
                and 0.08 <= cw / ch <= 1.05 and area >= 10
                and area / (cw * ch) >= 0.1):
            chars.append((int(x), int(y), int(cw), int(ch)))
    if not 6 <= len(chars) <= 12:
        return None
    groups = []
    for char in sorted(chars, key=lambda c: c[1] + c[3] / 2):
        cy = char[1] + char[3] / 2
        if groups and abs(cy - np.mean([c[1] + c[3] / 2 for c in groups[-1]])) < char[3] * 0.45:
            groups[-1].append(char)
        else:
            groups.append([char])
    if len(groups) not in (1, 2) or any(len(row) < 3 for row in groups):
        return None
    boxes = []
    for row in groups:
        heights = [c[3] for c in row]
        if max(heights) > min(heights) * 1.7:
            return None
        x0, y0 = min(c[0] for c in row), min(c[1] for c in row)
        x1, y1 = max(c[0] + c[2] for c in row), max(c[1] + c[3] for c in row)
        if x1 - x0 < w * 0.35:
            return None
        margin = max(2, round(np.median(heights) * 0.1))
        boxes.append([max(0, x0 - margin), min(w, x1 + margin),
                      max(0, y0 - margin), min(h, y1 + margin)])
    return boxes


def recovery_variants(crop):
    """Yield bounded alternatives; retain the original as an OCR candidate.

    Illumination normalization reduces smooth glare/shadows. Sharpening helps
    mild blur, but cannot restore characters lost to clipping or motion blur.
    """
    if crop is None or crop.size == 0:
        return
    corrected = straighten(crop)
    if corrected.shape != crop.shape or not np.array_equal(corrected, crop):
        yield 'deskew', enhance(corrected)
    gray = cv2.cvtColor(corrected, cv2.COLOR_BGR2GRAY) if corrected.ndim == 3 else corrected
    background = cv2.GaussianBlur(gray, (0, 0), max(5, min(gray.shape) / 6))
    normalized = cv2.divide(gray, np.maximum(background, 1), scale=210)
    normalized = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(normalized)
    smooth = cv2.GaussianBlur(normalized, (0, 0), 1.1)
    sharpened = cv2.addWeighted(normalized, 1.7, smooth, -0.7, 0)
    yield 'lighting', cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)
    block = max(15, min(51, (min(gray.shape) // 3) | 1))
    binary = cv2.adaptiveThreshold(normalized, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, block, 9)
    yield 'threshold', cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
