#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python -m pip install -r requirements.txt
exec python run.py
