@echo off
REM run.bat — Dùng để CHẠY ứng dụng hàng ngày sau khi đã setup.bat xong.
REM Tự động kích hoạt venv rồi chạy app.py.

call venv\Scripts\activate.bat
python app.py
pause
