# Kyriaki

AI-powered clinical trial matching engine for cancer patients. Takes a patient profile and returns ranked, eligible clinical trials with plain-language explanations — powered by a multi-agent orchestration layer.

## How It Works

1. Patient fills out an intake form (cancer type, stage, biomarkers, treatments, labs, location)
2. **MatchingAgent** searches ClinicalTrials.gov and runs Claude Sonnet against each trial's eligibility criteria (5 parallel)
3. Returns ranked matches with scores, criterion evaluations, and oncologist flags
4. **DossierAgent** (optional) runs Claude Opus for deep line-by-line eligibility analysis on top matches
5. Dossier blocks on a **human gate** — a navigator or oncologist must approve before the patient acts

All agent tasks, events, and approvals are tracked in the database.

## Tech Stack

- **Backend:** Python 3.9+ / FastAPI
- **AI:** Claude API — Sonnet for matching, Opus for dossier deep analysis
- **Database:** PostgreSQL (production) / SQLite (local dev)
- **Frontend:** React 19 / Vite
- **Trial Data:** ClinicalTrials.gov API v2
- **Infrastructure:** Docker, GitHub Actions CI, structured logging

## Quick Start

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env  # add your ANTHROPIC_API_KEY
python3 -m uvicorn main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

The backend auto-creates SQLite tables on startup for local dev — no database setup needed.

## Docker

```bash
docker compose up
```

Starts PostgreSQL, backend, and frontend. Requires `ANTHROPIC_API_KEY` in environment or `.env`.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `KYRIAKI_DATABASE_URL` | No | PostgreSQL localhost | Database connection string |
| `KYRIAKI_MAX_CONCURRENT_ANALYSES` | No | `5` | Parallel Claude calls |
| `KYRIAKI_DOSSIER_MODEL` | No | `claude-opus-4-20250514` | Model for deep analysis |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agents/match` | POST | Run matching (tracked agent task) |
| `/api/agents/dossier` | POST | Generate deep eligibility dossier |
| `/api/agents/tasks/{id}` | GET | Poll task status |
| `/api/agents/gates/{id}/resolve` | POST | Approve/reject a human gate |
| `/api/match` | POST | Direct matching (no DB tracking) |
| `/api/trials/{nct_id}` | GET | Trial details |
| `/api/health` | GET | Health check |

Interactive API docs at http://localhost:8000/docs

## Tests

```bash
cd backend
pytest -q          # 111 tests
ruff check .       # lint
ruff format --check .  # format
```

## Security

- API keys loaded from environment variables, never committed
- All GitHub Actions pinned to exact commit SHAs
- CI includes pip-audit and npm audit
- Input validation on all endpoints (UUID, NCT ID format, field lengths)
- No internal error details exposed to clients
- Docker containers run as non-root users

**Do not commit `.env` files or API keys to this repository.**

## License

All rights reserved.
