"""
plate_api.py
Nhận diện biển số bằng API đám mây (mặc định: Plate Recognizer Snapshot API).
Tùy chọn: không cấu hình thì hệ thống vẫn dùng EasyOCR như cũ; API lỗi cũng tự quay về EasyOCR.

Cấu hình bằng biến môi trường (đặt trước khi chạy app.py):
    PLATE_API_TOKEN    (bắt buộc để bật API)  token lấy từ https://platerecognizer.com
    PLATE_API_URL      (tùy chọn)  mặc định https://api.platerecognizer.com/v1/plate-reader/
                       (đổi sang địa chỉ máy chủ on-premise nếu bạn tự cài Snapshot SDK)
    PLATE_API_REGIONS  (tùy chọn)  mã quốc gia, cách nhau bằng dấu phẩy, mặc định 'vn'
    PLATE_API_TIMEOUT  (tùy chọn)  số giây chờ tối đa, mặc định 5
    PLATE_API_MODE     fallback (mặc định) / first / off
    PLATE_API_CAMERA   1 để cho phép gửi khung camera khi OCR cục bộ chưa tốt
    PLATE_API_MIN_SCORE ngưỡng chấp nhận kết quả, mặc định 0.8

    Windows (cmd):   set PLATE_API_TOKEN=xxxxxxxx
    macOS / Linux:   export PLATE_API_TOKEN=xxxxxxxx

Kết quả trả về được đưa qua plate_utils để đặt dấu '-' đúng dạng (vd 29-L131332, 51F-12345).
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid

import cv2

DEFAULT_URL = 'https://api.platerecognizer.com/v1/plate-reader/'
MAX_SIDE = 1600          # thu nhỏ ảnh quá lớn trước khi gửi (nhanh hơn, tránh lỗi 413)
_state_lock = threading.Lock()
_retry_after = 0.0
_last_attempt = float('-inf')


class ApiUnavailable(RuntimeError):
    """A failed/rate-limited API is cooling down; local OCR remains available."""


def _number(name, default, low, high):
    try:
        return max(low, min(high, float(os.environ.get(name, default))))
    except (ValueError, TypeError):
        return default


def min_score():
    return _number('PLATE_API_MIN_SCORE', 0.8, 0.0, 1.0)


def is_enabled() -> bool:
    return (os.environ.get('PLATE_API_MODE', 'fallback').lower() != 'off'
            and bool(os.environ.get('PLATE_API_TOKEN', '').strip()))


def _encode_image(image_path: str):
    """Trả về (bytes JPEG, hệ số thu nhỏ)."""
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f'Không đọc được ảnh: {image_path}')
    h, w = img.shape[:2]
    scale = MAX_SIDE / float(max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        scale = 1.0
    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError('Không mã hóa được ảnh để gửi API')
    return buf.tobytes(), scale


def recognize(image_path: str, *, min_interval=0):
    """Gửi ảnh lên API. Trả về (biển số thô viết hoa, (x, y, w, h) trên ẢNH GỐC hoặc None, độ tin cậy 0-1).
    Biển số thô chưa có dấu '-' chuẩn: nơi gọi phải đưa qua plate_utils.normalize_plate.
    Ném exception nếu lỗi mạng / token sai / hết hạn mức (nơi gọi sẽ chuyển sang EasyOCR)."""
    token = os.environ['PLATE_API_TOKEN'].strip()
    url = os.environ.get('PLATE_API_URL', DEFAULT_URL).strip() or DEFAULT_URL
    regions = [r.strip() for r in os.environ.get('PLATE_API_REGIONS', 'vn').split(',') if r.strip()]
    timeout = _number('PLATE_API_TIMEOUT', 5, 0.5, 30)

    # Skip encoding/upload preparation too while the service is cooling down.
    global _retry_after, _last_attempt
    with _state_lock:
        now = time.monotonic()
        if now < _retry_after or now - _last_attempt < min_interval:
            raise ApiUnavailable('API cooldown')
        _last_attempt = now
    jpg, scale = _encode_image(image_path)

    # Tự dựng form multipart/form-data bằng thư viện chuẩn (không cần cài thêm 'requests')
    boundary = uuid.uuid4().hex
    parts = []
    for r in regions:
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="regions"\r\n\r\n{r}\r\n').encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="upload"; filename="plate.jpg"\r\n'
                  f'Content-Type: image/jpeg\r\n\r\n').encode())
    parts.append(jpg)
    parts.append(f'\r\n--{boundary}--\r\n'.encode())
    body = b''.join(parts)

    req = urllib.request.Request(url, data=body, method='POST', headers={
        'Authorization': f'Token {token}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        with _state_lock:
            _retry_after = time.monotonic() + (300 if e.code in (401, 403) else 60)
        raise RuntimeError(f'API trả về lỗi HTTP {e.code}') from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        with _state_lock:
            _retry_after = time.monotonic() + 60
        raise
    results = payload.get('results') or []
    if not results:
        return '', None, 0.0

    best = max(results, key=lambda r: r.get('score') or 0)
    text = (best.get('plate') or '').upper()
    box = best.get('box') or {}
    rect = None
    if all(k in box for k in ('xmin', 'ymin', 'xmax', 'ymax')):
        x1, y1 = int(box['xmin'] / scale), int(box['ymin'] / scale)
        x2, y2 = int(box['xmax'] / scale), int(box['ymax'] / scale)
        rect = (x1, y1, max(0, x2 - x1), max(0, y2 - y1))
    return text, rect, float(best.get('score') or 0.0)
