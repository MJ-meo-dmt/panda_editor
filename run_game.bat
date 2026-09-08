@echo off
setlocal
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" run_game.py %*
) else (
  python run_game.py %*
)
endlocal
