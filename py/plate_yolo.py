"""
plate_yolo.py
Phát hiện VÙNG BIỂN SỐ bằng model YOLOv8 (thư viện ultralytics).

Vì sao cần YOLO?
 - Cách dò contour (Canny + tìm hình chữ nhật) trong plate_recognition.py hoạt động
   tốt với ảnh đơn giản nhưng dễ sai khi ảnh có nhiều cạnh/chi tiết (nhiều xe, cửa sổ,
   biển báo...). YOLOv8 được huấn luyện trên ảnh biển số thực tế nên dò vùng biển số
   chính xác hơn nhiều.
 - Module này CHỈ lo việc TÌM VÙNG biển số (bounding box). Việc ĐỌC ký tự vẫn do
   EasyOCR đảm nhiệm (xem plate_recognition.py).

Model được nạp LƯỜI (lazy) ở lần dùng đầu tiên để lúc mở app không bị chậm.
Nếu chưa cài ultralytics hoặc chưa có file model -> is_available() trả False và
toàn bộ hệ thống tự quay về cách dò contour cũ, không hề báo lỗi.

Cấu hình bằng biến môi trường (tùy chọn):
    PLATE_YOLO_MODEL   đường dẫn file .pt (mặc định: cache/yolo/plate_yolov8n.pt)
    PLATE_YOLO_CONF    ngưỡng tin cậy tối thiểu 0-1 (mặc định 0.25)
"""

import os

from config import PLATE_YOLO_MODEL

_model = None
_load_failed = False   # đánh dấu đã thử nạp mà thất bại -> không thử lại mỗi lần gọi


def model_path() -> str:
    return os.environ.get('PLATE_YOLO_MODEL', '').strip() or PLATE_YOLO_MODEL


def confidence_threshold() -> float:
    try:
        return float(os.environ.get('PLATE_YOLO_CONF', '0.25'))
    except ValueError:
        return 0.25


def is_available() -> bool:
    """Có sẵn sàng dùng YOLO không: có file model + import được ultralytics."""
    if _load_failed:
        return False
    if not os.path.exists(model_path()):
        return False
    try:
        _get_model()
        return _model is not None
    except Exception:
        return False


def _get_model():
    """Nạp model 1 lần duy nhất (lazy)."""
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model
    try:
        from ultralytics import YOLO
        path = model_path()
        if not os.path.exists(path):
            return None
        _model = YOLO(path)
    except Exception as e:                       # thiếu ultralytics/torch, model hỏng...
        print(f'[plate_yolo] YOLO unavailable, fallback to contour: {e}')
        _load_failed = True
        _model = None
    return _model


def detect_best(image):
    """Chạy YOLO trên ảnh (numpy BGR). Trả về (x, y, w, h) của biển số tin cậy nhất
    trên ẢNH GỐC, hoặc None nếu không thấy / lỗi."""
    model = _get_model()
    if model is None:
        return None
    try:
        results = model.predict(image, conf=confidence_threshold(), verbose=False)
    except Exception as e:
        print(f'[plate_yolo] YOLO predict error: {e}')
        return None
    if not results:
        return None

    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return None

    best = max(boxes, key=lambda b: float(b.conf[0]))
    x1, y1, x2, y2 = (int(v) for v in best.xyxy[0].tolist())
    h, w = image.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 10 or y2 - y1 < 5:
        return None
    return x1, y1, x2 - x1, y2 - y1
