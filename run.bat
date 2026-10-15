@echo off
rem Start Arti Gala on Windows: creates a virtual environment on first run,
rem installs dependencies, then serves the dashboard at http://127.0.0.1:8000
cd /d "%~dp0"

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv || goto :nopython
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || goto :error
)

echo Arti Gala running at http://127.0.0.1:8000  (API docs: /docs, stop with Ctrl+C)
start "" http://127.0.0.1:8000
.venv\Scripts\python -m app.cli serve %*
goto :eof

:nopython
echo Python 3.11 or newer is required: https://www.python.org/downloads/
echo Tick "Add python.exe to PATH" during installation, then run this file again.
pause
goto :eof

:error
echo Installing dependencies failed. See the messages above.
pause
