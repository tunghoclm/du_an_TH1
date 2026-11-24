"""
config.py
Tập trung toàn bộ đường dẫn của dự án để các file khác dùng chung.
"""
import os

PY_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PY_DIR)                      # smart_parking/

CACHE_DIR = os.path.join(BASE_DIR, "cache")             # file sinh ra sau khi chạy setup
DB_PATH = os.path.join(CACHE_DIR, "parking.db")
EASYOCR_DIR = os.path.join(CACHE_DIR, "easyocr_models")  # model EasyOCR tải sẵn
TMP_DIR = os.path.join(CACHE_DIR, "tmp")                # ảnh tạm giữa bước Nhận diện và Xác nhận

# Model YOLOv8 phát hiện VÙNG BIỂN SỐ (tùy chọn). Nếu có file .pt trong YOLO_DIR,
# hệ thống dùng YOLO để dò biển số; không có thì tự quay về cách dò contour (Canny).
YOLO_DIR = os.path.join(CACHE_DIR, "yolo")
PLATE_YOLO_MODEL = os.path.join(YOLO_DIR, "plate_yolov8n.pt")

SQL_DIR = os.path.join(BASE_DIR, "SQL")                 # chứa các file .sql (đọc tất cả, theo thứ tự tên)

# Font tiếng Việt đi kèm dự án (dùng khi xuất báo cáo PDF — chạy được trên mọi máy)
FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")

TEMPLATES_HTML_DIR = os.path.join(BASE_DIR, "templates", "html")
TEMPLATES_CSS_DIR = os.path.join(BASE_DIR, "templates", "css")

STATIC_DIR = os.path.join(BASE_DIR, "static")
IN_DIR = os.path.join(STATIC_DIR, "in")                 # ảnh xe đi vào
OUT_DIR = os.path.join(STATIC_DIR, "out")               # ảnh xe đi ra

for _d in (CACHE_DIR, EASYOCR_DIR, TMP_DIR, YOLO_DIR, IN_DIR, OUT_DIR):
    os.makedirs(_d, exist_ok=True)
