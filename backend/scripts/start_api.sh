#!/bin/sh
set -eu

cd /app
python -m scripts.migrate_all
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
