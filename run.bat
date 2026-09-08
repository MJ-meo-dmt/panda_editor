@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup_and_run.bat first.
    pause
    exit /b 1
)
call "venv\Scripts\activate.bat"
python run_editor.py
