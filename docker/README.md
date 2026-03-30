# Docker Notes

- `docker-compose.yml` starts PostgreSQL, the FastAPI backend, and the built React frontend.
- The PostgreSQL service exposes a health check so the backend waits for the database before applying migrations.
- The backend container runs `alembic upgrade head` before launching Uvicorn.
- Copy `backend/.env.example` to `backend/.env` before running the compose stack.
