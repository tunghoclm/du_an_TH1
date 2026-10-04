@echo off
REM setup.bat — Chạy MỘT LẦN DUY NHẤT để cài đặt toàn bộ môi trường.
REM Sau khi chạy xong, mọi lần sau chỉ cần chạy: run.bat

echo ====================================================
echo  CAI DAT SMART PARKING DEMO (chi can chay 1 lan)
echo ====================================================

IF NOT EXIST venv (
    echo Dang tao virtual environment...
    python -m venv venv
) ELSE (
    echo Da co virtual environment, bo qua buoc tao.
)

call venv\Scripts\activate.bat

echo Dang cai thu vien tu requirements.txt...
python -m pip install --upgrade pip
pip install -r requirements.txt
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo ====================================================
    echo  LOI: Cai thu vien that bai. Xem thong bao loi mau do
    echo  o phia tren de biet nguyen nhan cu the.
    echo  KHONG tiep tuc cac buoc sau cho den khi loi nay het.
    echo ====================================================
    pause
    exit /b 1
)

echo Dang tai san model EasyOCR (chi tai 1 lan, can Internet)...
python -c "import easyocr; easyocr.Reader(['en'], gpu=False); print('Da tai xong model EasyOCR.')"

echo Dang khoi tao database...
python -c "import database; database.init_db(); print('Da khoi tao database (parking.db).')"

echo.
echo ====================================================
echo  CAI DAT HOAN TAT!
echo  Tu gio moi lan muon chay ung dung, chi can chay:
echo.
echo      run.bat
echo ====================================================
pause
