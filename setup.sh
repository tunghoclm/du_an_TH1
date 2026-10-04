#!/bin/bash
# setup.sh — Chạy MỘT LẦN DUY NHẤT để cài đặt toàn bộ môi trường.
# Sau khi chạy xong, mọi lần sau chỉ cần: 
#   source venv/bin/activate && python app.py

set -e  # dừng ngay nếu có lỗi

echo "===================================================="
echo " CÀI ĐẶT SMART PARKING DEMO (chỉ cần chạy 1 lần)"
echo "===================================================="

# 1. Tạo virtual environment
if [ ! -d "venv" ]; then
    echo ">> Đang tạo virtual environment..."
    python3 -m venv venv
else
    echo ">> Đã có virtual environment, bỏ qua bước tạo."
fi

# 2. Kích hoạt venv
source venv/bin/activate

# 3. Cài thư viện
echo ">> Đang cài thư viện từ requirements.txt (có thể mất vài phút)..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Tải sẵn model EasyOCR ngay trong bước cài đặt,
#    để lần chạy app.py đầu tiên không phải chờ tải model.
echo ">> Đang tải sẵn model EasyOCR (chỉ tải 1 lần, cần Internet)..."
python -c "import easyocr; easyocr.Reader(['en'], gpu=False); print('Đã tải xong model EasyOCR.')"

# 5. Khởi tạo database (nếu chưa có)
echo ">> Đang khởi tạo database..."
python -c "import database; database.init_db(); print('Đã khởi tạo database (parking.db).')"

echo ""
echo "===================================================="
echo " CÀI ĐẶT HOÀN TẤT!"
echo " Từ giờ mỗi lần muốn chạy ứng dụng, chỉ cần:"
echo ""
echo "     source venv/bin/activate"
echo "     python app.py"
echo ""
echo " (hoặc chạy: ./run.sh)"
echo "===================================================="
