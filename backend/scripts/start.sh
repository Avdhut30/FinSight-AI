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
