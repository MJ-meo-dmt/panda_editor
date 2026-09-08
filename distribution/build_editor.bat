@echo off
setlocal
cd /d "%~dp0.."
if not exist "venv\Scripts\python.exe" (
  echo ERROR: venv\Scripts\python.exe was not found.
  echo Run setup_and_run.bat first.
  pause
  exit /b 1
)
call "venv\Scripts\activate.bat"
python distribution\setup_editor.py build_apps
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (
  echo Panda3D build_apps completed. Check the build folder.
) else (
  echo Build failed with exit code %RC%.
)
pause
exit /b %RC%
