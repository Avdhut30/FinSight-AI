#!/bin/sh
# Robust startup for local, Docker, and Render.
set -eu

# Always run from backend root so imports and alembic paths resolve.
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
import os
import time
import psycopg

url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
max_attempts = int(os.getenv("DB_WAIT_ATTEMPTS", "30"))
interval = float(os.getenv("DB_WAIT_INTERVAL", "3"))

for attempt in range(max_attempts):
    try:
        with psycopg.connect(url, connect_timeout=5):
            print("Database ready.")
            break
    except Exception as exc:
        print(f"Waiting for database... ({attempt + 1}/{max_attempts}) {exc}")
        time.sleep(interval)
else:
    raise SystemExit(f"Database did not become ready in time after {max_attempts} attempts.")
PY

alembic upgrade head

PORT="${PORT:-8000}"
exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
