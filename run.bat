@echo off
REM run.bat - Dung de CHAY ung dung hang ngay sau khi da chay setup.bat.
REM Tu dong kich hoat venv (cache\venv) roi chay app.py.
cd /d "%~dp0"

IF NOT EXIST cache\venv (
    echo Chua cai dat. Hay chay setup.bat truoc.
    pause
    exit /b 1
)
call cache\venv\Scripts\activate.bat
python app.py
pause
