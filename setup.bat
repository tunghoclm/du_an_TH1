@echo off
REM setup.bat - Chay MOT LAN DUY NHAT de cai dat toan bo moi truong.
REM Moi file sinh ra (venv, model EasyOCR, database, anh tam) deu nam trong thu muc cache\.
REM Sau khi chay xong, moi lan sau chi can chay: run.bat
cd /d "%~dp0"

echo ====================================================
echo  CAI DAT SMART PARKING DEMO (chi can chay 1 lan)
echo ====================================================

IF NOT EXIST cache mkdir cache
IF NOT EXIST static\in mkdir static\in
IF NOT EXIST static\out mkdir static\out

IF NOT EXIST cache\venv (
    echo Dang tao virtual environment trong cache\venv ...
    python -m venv cache\venv
) ELSE (
    echo Da co virtual environment, bo qua buoc tao.
)

call cache\venv\Scripts\activate.bat

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
python -c "import sys; sys.path.insert(0, 'py'); import easyocr; from config import EASYOCR_DIR; easyocr.Reader(['en'], gpu=False, model_storage_directory=EASYOCR_DIR, user_network_directory=EASYOCR_DIR); print('Da tai xong model EasyOCR.')"

echo Dang khoi tao database...
python -c "import sys; sys.path.insert(0, 'py'); import database; database.init_db(); print('Da khoi tao database (cache/parking.db).')"

echo.
echo ====================================================
echo  CAI DAT HOAN TAT!
echo  Tu gio moi lan muon chay ung dung, chi can chay:
echo.
echo      run.bat
echo ====================================================
pause
