#!/bin/bash
# run.sh — Dùng để CHẠY ứng dụng hàng ngày sau khi đã chạy setup.sh.
# Tự động kích hoạt venv (cache/venv) rồi chạy app.py.

cd "$(dirname "$0")"
if [ ! -d "cache/venv" ]; then
    echo "Chưa cài đặt. Hãy chạy ./setup.sh trước."
    exit 1
fi
source cache/venv/bin/activate
python app.py
