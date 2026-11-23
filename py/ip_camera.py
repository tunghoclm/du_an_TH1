"""
Hỗ trợ kết nối camera IP / điện thoại (IP Webcam Android, RTSP, MJPEG HTTP).

Cung cấp các hàm chuẩn hóa URL, kiểm tra kết nối, chụp khung hình và stream MJPEG
qua OpenCV để trình duyệt hiển thị cùng origin (tránh lỗi CORS/RTSP).
"""

import time
import re
from urllib.parse import urlsplit, urlunsplit

import cv2

CAMERA_SLOT_SETTING_KEYS = {
    'entry_plate': 'entry_plate_camera',
    'entry_overview': 'entry_overview_camera',
    'exit_plate': 'exit_plate_camera',
    'exit_overview': 'exit_overview_camera',
}

_SCHEME_RE = re.compile(r'^(https?|rtsps?)://', re.IGNORECASE)
_HOST_PORT_RE = re.compile(r'^[a-zA-Z0-9._-]+:\d{2,5}(/.*)?$')


def is_ip_camera_url(value: str) -> bool:
    """Trả về True nếu chuỗi là URL camera IP (http/https/rtsp hoặc host:port)."""
    text = (value or '').strip()
    if not text:
        return False
    return bool(_SCHEME_RE.match(text) or _HOST_PORT_RE.match(text))


def normalize_ip_camera_url(value: str) -> str:
    """Chuẩn hóa URL camera IP; tự thêm http:// và /video cho IP Webcam nếu thiếu."""
    text = (value or '').strip()
    if not is_ip_camera_url(text):
        return ''
    if not _SCHEME_RE.match(text):
        text = 'http://' + text
    parts = urlsplit(text)
    if not parts.netloc:
        return ''
    scheme = parts.scheme.lower()
    path = parts.path
    if scheme in ('http', 'https') and path in ('', '/'):
        path = '/video'
    return urlunsplit((scheme, parts.netloc, path, parts.query, ''))


def open_ip_capture(raw_url: str):
    """Mở cv2.VideoCapture cho URL camera IP và kiểm tra đọc được khung hình đầu."""
    url = normalize_ip_camera_url(raw_url)
    if not url:
        raise ValueError('Đường dẫn camera không hợp lệ (VD: http://192.168.1.15:8080/video).')
    cap = cv2.VideoCapture(url)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    if not cap.isOpened():
        cap.release()
        raise OSError('Không mở được luồng camera.')
    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        raise OSError('Đã kết nối nhưng không nhận được hình ảnh từ camera.')
    return cap, frame, url


def probe_ip_camera(raw_url: str) -> dict:
    """Kiểm tra kết nối tới camera IP, trả về dict {ok, message, normalized_url}."""
    normalized = normalize_ip_camera_url(raw_url)
    if not normalized:
        return {
            'ok': False,
            'message': 'Đường dẫn chưa đúng định dạng (VD: http://192.168.1.15:8080/video).',
            'normalized_url': '',
        }
    cap = None
    try:
        cap, frame, normalized = open_ip_capture(normalized)
        height, width = frame.shape[:2]
        return {
            'ok': True,
            'message': f'Kết nối thành công ({width}×{height}).',
            'normalized_url': normalized,
        }
    except Exception:
        return {
            'ok': False,
            'message': 'Không kết nối được tới camera. Kiểm tra IP, cổng (mặc định 8080), đã bấm Start server trên IP Webcam và cùng mạng Wi-Fi.',
            'normalized_url': normalized,
        }
    finally:
        if cap is not None:
            cap.release()


def _encode_jpeg(frame, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise OSError('Không nén được khung hình JPEG.')
    return buf.tobytes()


def capture_ip_camera_jpeg(raw_url: str) -> bytes:
    """Chụp 1 khung hình JPEG từ camera IP."""
    cap = None
    try:
        cap, frame, _ = open_ip_capture(raw_url)
        return _encode_jpeg(frame, quality=90)
    finally:
        if cap is not None:
            cap.release()


def stream_mjpeg_frames(cap, first_frame, fps_limit: float = 25.0):
    """Generator phát luồng multipart MJPEG từ VideoCapture đã mở sẵn."""
    min_interval = 1.0 / max(1.0, fps_limit)
    consecutive_failures = 0
    try:
        if first_frame is not None:
            payload = _encode_jpeg(first_frame)
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + payload + b'\r\n'
            )
        while True:
            started = time.monotonic()
            ok, frame = cap.read()
            if not ok or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= 15:
                    break
                time.sleep(0.05)
                continue
            consecutive_failures = 0
            payload = _encode_jpeg(frame)
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + payload + b'\r\n'
            )
            elapsed = time.monotonic() - started
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
    finally:
        cap.release()
