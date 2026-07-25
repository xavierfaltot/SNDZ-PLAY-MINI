#!/bin/zsh
set -e

APP_DIR="${0:A:h}"
cd "$APP_DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:/usr/bin:/bin:$PATH"

if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

if ! ".venv/bin/python" -c "import PySide6.QtWidgets" >/dev/null 2>&1; then
  ".venv/bin/python" -m pip install -r requirements.txt
fi

exec ".venv/bin/python" run_sndz_mini.py
