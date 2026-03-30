# FinSight AI

FinSight AI is a stock analysis starter project with a production-minded structure: a FastAPI backend, a React frontend, live market and news ingestion, sentiment scoring, and an agent layer that turns those tool outputs into an analyst-style answer.

## What is included

- `backend/`: FastAPI application with modular services for stock data, news, sentiment, rate limiting, persistence, and the stock analysis agent.
- `frontend/`: React + Vite workspace with a chat-style interface, watchlist cards, and analysis panels.
- `docker-compose.yml`: One-command local stack for PostgreSQL, backend, and frontend.
- `database/`: Notes for persistence and future vector-store expansion.

## Backend flow

1. Resolve the company ticker from the user query.
2. Pull market data from Twelve Data.
3. Pull recent headlines from Google News RSS.
4. Score sentiment with a lexicon model by default or FinBERT when enabled.
5. Build a recommendation and optionally refine the answer with an OpenAI model.
6. Persist each analysis record in the configured SQL database.

## Key endpoints

- `GET /api/v1/health`
- `GET /api/v1/watchlist`
- `POST /api/v1/analyze`
- `POST /api/v1/analyze/stream`
- `GET /api/v1/analyses/{analysis_id}`

## Local setup

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn main:app --reload
```

If you want FinBERT sentiment, also install:

```bash
pip install -r requirements-ml.txt
```

Run the backend test suite with:

```bash
python -m pytest
```

### Frontend

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

If PowerShell blocks `npm` script execution on Windows, use `npm.cmd run dev` instead.

The frontend expects the backend at `http://localhost:8000` by default.
The chat UI uses the streaming analysis endpoint by default and renders progress plus answer text incrementally.

## Docker setup

```bash
copy backend\.env.example backend\.env
docker compose up --build
```

Local development defaults to SQLite via `backend/.env`.
`docker-compose.yml` overrides `DATABASE_URL` so the backend connects to the `db` container instead of SQLite.

Frontend: `http://localhost:4173`  
Backend docs: `http://localhost:8000/docs`

The backend container runs `alembic upgrade head` before starting the API, so the database schema is applied from the migration history instead of being created implicitly at app startup.

## Environment variables

### Backend

- `DATABASE_URL`: PostgreSQL or SQLite connection string. Local development defaults to SQLite.
- `OPENAI_API_KEY`: Optional. Enables the LLM answer layer.
- `OPENAI_MODEL`: Optional model name for the answer layer.
- `OPENAI_TEMPERATURE` and `OPENAI_MAX_TOKENS`: LLM generation controls.
- `TWELVE_DATA_API_KEY`: Required for market data.
- `ENABLE_TRANSFORMERS_SENTIMENT`: Set to `true` to use FinBERT.
- `FINBERT_MODEL_NAME`: Hugging Face model id.
- `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS`: API throttling controls.
- `DEFAULT_WATCHLIST`: Comma-separated symbols for the dashboard rail.

LLM prompt templates live in `backend/app/prompts/` so prompt changes are versioned separately from service logic.

### Frontend

- `VITE_API_BASE_URL`: Base URL for the FastAPI service.

## Suggested next upgrades

- Add portfolio upload and risk analytics.
- Add alerts and scheduled jobs for daily summaries.
- Replace heuristic recommendation scoring with a trained ranking model.
- Store filings, earnings call notes, and research memos in a vector store for retrieval-augmented answers.
