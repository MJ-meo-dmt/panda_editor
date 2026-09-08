@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [Panda Editor] Creating virtual environment...
    py -3 -m venv venv
    if errorlevel 1 goto :fail
)

call "venv\Scripts\activate.bat"
echo [Panda Editor] Installing/updating requirements...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [Panda Editor] Starting...
python run_editor.py
goto :eof

:fail
echo.
echo [Panda Editor] Setup failed. Review the error above.
pause
exit /b 1
