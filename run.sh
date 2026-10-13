#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv 2>/dev/null
fi
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi
pip install -q -r requirements.txt
python app.py
