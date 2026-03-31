#!/bin/sh
set -eu

python - <<'PY'
import os
import time
import psycopg

url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
for attempt in range(10):
    try:
        with psycopg.connect(url, connect_timeout=3):
            print("Database ready.")
            break
    except Exception as exc:
        print(f"Waiting for database... ({attempt + 1}/10) {exc}")
        time.sleep(2)
else:
    raise SystemExit("Database did not become ready in time.")
PY

alembic upgrade head

PORT="${PORT:-8000}"
exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
