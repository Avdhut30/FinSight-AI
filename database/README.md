# Database Notes

- Local development defaults to PostgreSQL through `docker-compose.yml`.
- The backend also supports SQLite for quick local boot if `DATABASE_URL` is not set.
- Schema changes are managed through Alembic migrations in `backend/alembic/`.
- Apply the current schema with `alembic upgrade head` from the `backend/` directory.
- A vector store is not wired in this starter yet; add Chroma or pgvector once you want retrieval over filings, transcripts, or internal research notes.
