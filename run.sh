#!/usr/bin/env sh
# Start Arti Gala on macOS / Linux: creates a virtual environment on first run,
# installs dependencies, then serves the dashboard at http://127.0.0.1:8000
set -e
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  "$PYTHON" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

echo "Arti Gala running at http://127.0.0.1:8000  (API docs: /docs, stop with Ctrl+C)"
exec .venv/bin/python -m app.cli serve "$@"
