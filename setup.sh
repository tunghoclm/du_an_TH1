#!/bin/bash
# setup.sh — Chạy MỘT LẦN DUY NHẤT để cài đặt toàn bộ môi trường.
# Mọi file sinh ra (venv, model EasyOCR, database, ảnh tạm) đều nằm trong thư mục cache/.
# Sau khi chạy xong, mọi lần sau chỉ cần: ./run.sh

set -e  # dừng ngay nếu có lỗi
cd "$(dirname "$0")"

echo "===================================================="
echo " CÀI ĐẶT SMART PARKING DEMO (chỉ cần chạy 1 lần)"
echo "===================================================="

mkdir -p cache static/in static/out

# 1. Tạo virtual environment trong cache/venv
if [ ! -d "cache/venv" ]; then
    echo ">> Đang tạo virtual environment (cache/venv)..."
    python3 -m venv cache/venv
else
    echo ">> Đã có virtual environment, bỏ qua bước tạo."
fi

# 2. Kích hoạt venv
source cache/venv/bin/activate

# 3. Cài thư viện
echo ">> Đang cài thư viện từ requirements.txt (có thể mất vài phút)..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Tải sẵn model EasyOCR vào cache/easyocr_models
echo ">> Đang tải sẵn model EasyOCR (chỉ tải 1 lần, cần Internet)..."
python -c "
import sys; sys.path.insert(0, 'py')
import easyocr
from config import EASYOCR_DIR
easyocr.Reader(['en'], gpu=False, model_storage_directory=EASYOCR_DIR, user_network_directory=EASYOCR_DIR)
print('Đã tải xong model EasyOCR.')
"

# 5. Khởi tạo database (cache/parking.db) từ SQL/schema.sql
echo ">> Đang khởi tạo database..."
python -c "
import sys; sys.path.insert(0, 'py')
import database
database.init_db()
print('Đã khởi tạo database (cache/parking.db).')
"

echo ""
echo "===================================================="
echo " CÀI ĐẶT HOÀN TẤT!"
echo " Từ giờ mỗi lần muốn chạy ứng dụng, chỉ cần:"
echo ""
echo "     ./run.sh"
echo "===================================================="
