"""
download_yolo_model.py
Tải model YOLOv8 phát hiện biển số về cache/yolo/plate_yolov8n.pt (chỉ tải 1 lần).

Model dùng bản công khai của cộng đồng (1 lớp 'license_plate'):
    https://huggingface.co/Koushim/yolov8-license-plate-detection

Chạy:  python py/download_yolo_model.py
Nếu máy không có Internet hoặc tải lỗi, script chỉ in cảnh báo — ứng dụng vẫn
chạy bình thường bằng cách dò contour (xem plate_recognition.py).
"""

import os
import sys
import urllib.request

# Console Windows mặc định dùng cp1252 -> in tiếng Việt sẽ lỗi; chuyển sang UTF-8.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PLATE_YOLO_MODEL, YOLO_DIR   # noqa: E402

MODEL_URL = 'https://huggingface.co/Koushim/yolov8-license-plate-detection/resolve/main/best.pt'


def _fetch(url: str, out_path: str, timeout: int = 180):
    """Tải 1 URL (tự theo redirect) xuống out_path."""
    req = urllib.request.Request(url, headers={'User-Agent': 'smart-parking-setup/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(out_path, 'wb') as out:
        total = int(resp.headers.get('Content-Length') or 0)
        done = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f'\r  {done * 100 // total}% ({done // 1024} KB)', end='', flush=True)
    print()


def download(target: str = PLATE_YOLO_MODEL, url: str = MODEL_URL, attempts: int = 3) -> bool:
    """Tải model về `target`. Trả về True nếu có sẵn file sau cùng (đã có sẵn hoặc tải xong)."""
    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f'Đã có model YOLO: {target} (bỏ qua tải).')
        return True

    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + '.part'
    last_err = None
    for attempt in range(1, attempts + 1):
        print(f'Đang tải model YOLO ({url}) — lần {attempt}/{attempts} ...')
        try:
            _fetch(url, tmp)
            os.replace(tmp, target)
            print(f'Đã tải xong: {target}')
            return True
        except Exception as e:
            last_err = e
            print(f'  Lỗi: {e}')
            try:
                os.remove(tmp)
            except OSError:
                pass

    print(f'\nCẢNH BÁO: không tải được model YOLO ({last_err}).')
    print('Ứng dụng vẫn chạy được bằng cách dò contour (độ chính xác thấp hơn với ảnh thực tế).')
    return False


if __name__ == '__main__':
    ok = download()
    sys.exit(0 if ok else 0)   # luôn thoát 0: model là tùy chọn, không chặn cài đặt
