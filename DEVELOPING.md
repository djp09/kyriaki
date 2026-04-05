# Developing Kyriaki

## Quick Start

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env  # add your ANTHROPIC_API_KEY
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev  # http://localhost:5173, proxies /api → :8000
```

## Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Database (defaults to SQLite for dev)
KYRIAKI_DATABASE_URL=sqlite+aiosqlite:///kyriaki_dev.db

# Optional overrides
KYRIAKI_CLAUDE_MODEL=claude-sonnet-4-20250514
KYRIAKI_DOSSIER_MODEL=claude-opus-4-20250514
KYRIAKI_LOG_LEVEL=INFO
KYRIAKI_LOG_FORMAT=text          # "text" for dev, "json" for prod
KYRIAKI_MONITOR_ENABLED=false
KYRIAKI_TRIAL_REFRESH_ENABLED=false
KYRIAKI_AUTO_CHAIN_MATCHING_TO_DOSSIER=false
```

## Local Gemma (ADR-002 hybrid pipeline)

Stages 1, 3, and 4 of the matching pipeline run on self-hosted Gemma to keep
PHI local. In dev, Gemma runs via Ollama on your machine.

### Setup

```bash
# Install Ollama (official macOS app — NOT the Homebrew formula, which has
# Metal shader issues on M5/Tahoe as of v0.20.2)
brew install --cask ollama-app

# Launch Ollama (lives in menu bar, serves on localhost:11434)
open -a Ollama

# Pull models
ollama pull gemma3:12b        # ~8GB — generation (intake normalization, criterion extraction)
ollama pull nomic-embed-text  # ~274MB — embeddings (semantic recall)

# Verify
curl -s http://localhost:11434/api/tags | python3 -m json.tool
```

### Config

```bash
# Add to .env (defaults shown — only override if needed)
KYRIAKI_GEMMA_BACKEND=ollama              # "ollama" for dev, "vertex" for prod
KYRIAKI_OLLAMA_HOST=http://localhost:11434
KYRIAKI_GEMMA_GENERATE_MODEL=gemma3:12b
KYRIAKI_GEMMA_EMBED_MODEL=nomic-embed-text
```

### Running the prototypes

```bash
# Stage 1 — intake normalization (5 test patients)
python3 -m backend.scripts.prototype_intake

# Stage 4 — criterion extraction (3 trial eligibility blocks)
python3 -m backend.scripts.prototype_criterion
```

### Known issues

- **Homebrew `ollama` formula (NOT cask)** fails on Apple M5 / macOS 26 Tahoe
  with `ggml_metal_library_init: error: failed to create library`. The official
  `ollama-app` cask bundles a precompiled Metal library and works correctly.
- **Latency**: ~7–13s per call on M5 Pro for gemma3:12b. Acceptable for dev;
  Vertex AI endpoints will be faster in prod.
- **OLLAMA_NUM_GPU=0** does NOT bypass the Metal issue — the runner initializes
  Metal regardless.

## Testing

```bash
cd backend

# Run all tests
python3 -m pytest --tb=short -q

# Run with coverage
python3 -m pytest --cov=. --cov-report=term-missing

# Run a specific test file
python3 -m pytest test_orchestration.py -v

# Run a specific test class
python3 -m pytest test_matching.py::TestProgrammaticScoring -v
```

## Linting & Formatting

```bash
cd backend

# Check lint
python3 -m ruff check backend/

# Auto-fix lint
python3 -m ruff check backend/ --fix

# Check formatting
python3 -m ruff format --check backend/

# Auto-format
python3 -m ruff format backend/

# Full pre-push check (lint + format + test)
python3 -m ruff check backend/ && python3 -m ruff format --check backend/ && python3 -m pytest --tb=short -q
```

## Evaluation Harness

Measures matching quality against 10 synthetic patients with known clinical profiles. Searches real ClinicalTrials.gov, evaluates with Claude, scores programmatically.

```bash
cd backend

# Quick eval — first 3 patients (~2 min, uses Claude API)
python3 -m eval.run_eval --quick

# Full eval — all 10 patients (~10 min)
python3 -m eval.run_eval

# Single patient
python3 -m eval.run_eval eval_nsclc_egfr
python3 -m eval.run_eval eval_tnbc_heavy
python3 -m eval.run_eval eval_peds_neuro

# Available patient IDs:
# eval_nsclc_egfr    — NSCLC EGFR+ Stage IV
# eval_tnbc_heavy    — TNBC Stage IV, 3 prior lines
# eval_peds_neuro    — Neuroblastoma, age 8
# eval_crc_msih      — Colorectal MSI-H Stage IV
# eval_melanoma_braf — Melanoma BRAF V600E
# eval_pancreatic    — Pancreatic Stage IV
# eval_prostate_brca — Prostate mCRPC, BRCA2+
# eval_ewing         — Ewing sarcoma, age 19
# eval_sclc          — SCLC limited stage
# eval_gbm           — Glioblastoma recurrent
```

Results are saved to `eval/last_run.json` and printed to stdout with:
- Per-trial scores with tier indicators (`+` strong, `~` potential, `?` partial, `-` unlikely, `X` excluded)
- Score distribution buckets
- Criterion-level accuracy against expected outcomes
- Phase 1 gate check (>85% criterion accuracy)
- Differentiation check (per-patient score spread >= 30)

## E2E Integration Test

Runs the full agent pipeline (matching → dossier → gate resolution) against real APIs with an in-memory SQLite database.

```bash
cd backend
python3 run_integration_e2e.py
```

## Database

### Development (SQLite)
Tables are auto-created on startup. No migration needed.

### Production (PostgreSQL)
```bash
cd backend
alembic upgrade head
```

### Migrations
```bash
# After modifying db_models.py:
alembic revision --autogenerate -m "Description"
alembic upgrade head
```

## CI

CI runs on every push to `main`: lint → format check → test → Docker build.

```bash
# Monitor CI after pushing
gh run list --limit 1
gh run watch <run-id> --exit-status

# Check failed logs
gh run view <run-id> --log-failed
```

## Admin Endpoints

```bash
# Trigger trial cache refresh manually
curl -X POST http://localhost:8000/api/admin/refresh-trials

# Check trial cache health
curl http://localhost:8000/api/admin/trial-cache/stats

# Retry a failed task
curl -X POST http://localhost:8000/api/agents/tasks/<task-id>/retry

# Check patient pipeline status
curl http://localhost:8000/api/patients/<patient-id>/pipeline

# Download dossier PDF
curl http://localhost:8000/api/agents/tasks/<task-id>/dossier.pdf -o dossier.pdf

# View patient profile version history
curl http://localhost:8000/api/patients/<patient-id>/versions
```

## Project Structure

```
backend/
├── agents.py              # 5 ReAct agents (matching, dossier, enrollment, outreach, monitor)
├── agent_loop.py          # Generic ReAct execution engine with tool_use
├── dispatcher.py          # Task lifecycle, duplicate guard, pipeline state, retry
├── routing.py             # Patient complexity classification (simple/moderate/complex)
├── prompts.py             # All prompt templates
├── gemma_client.py        # Local Gemma LLM client (Ollama dev / Vertex prod)
├── intake.py              # Stage 1: intake normalization (Gemma, local)
├── semantic_recall.py     # Stage 3: embedding + cosine-rank (Gemma, local)
├── criterion_extraction.py # Stage 4: eligibility text → structured criteria (Gemma, local)
├── matching_engine.py     # Legacy sync matching (uses new criterion pipeline)
├── trials_client.py       # ClinicalTrials.gov + NCI API client
├── civic_client.py        # CIViC biomarker evidence API
├── rxnorm_client.py       # RxNorm drug normalization API
├── trial_refresh.py       # Nightly cache refresh service
├── tools/
│   ├── __init__.py        # ToolResult, TokenUsage, tool registry
│   ├── claude_api.py      # All Claude API calls + adaptive rate limiter
│   ├── criteria_parser.py # Rule-based eligibility criteria splitter
│   ├── scoring.py         # Programmatic match scoring (no LLM)
│   ├── data_formatter.py  # Pure data transforms
│   ├── prompt_renderer.py # Validated prompt rendering
│   ├── trial_search.py    # Trial search tool wrappers
│   ├── document_extractor.py  # Medical document AI extraction
│   ├── pdf_renderer.py    # Dossier PDF generation
│   ├── ground_truth.py    # Outcome tracking
│   ├── biomarker_lookup.py    # CIViC tool wrapper
│   └── drug_normalization.py  # RxNorm tool wrapper
├── eval/
│   ├── synthetic_patients.py  # 10 test patients
│   └── run_eval.py            # Batch evaluation runner
├── db_models.py           # SQLAlchemy ORM models
├── db_service.py          # DB CRUD + profile versioning
├── config.py              # Pydantic settings
├── main.py                # FastAPI app + endpoints
├── scripts/
│   ├── prototype_intake.py    # Stage 1 Gemma prototype harness
│   └── prototype_criterion.py # Stage 4 Gemma prototype harness
└── alembic/versions/      # DB migrations (001-010)

frontend/
├── src/
│   ├── App.jsx            # Main app with pipeline state management
│   ├── api.js             # Backend API client
│   ├── components/
│   │   ├── DocumentUpload.jsx   # Drag-and-drop medical record upload
│   │   ├── IntakeForm.jsx       # Multi-step patient intake (pre-fillable)
│   │   ├── TrialResults.jsx     # Match results with per-trial actions
│   │   ├── TrialDetail.jsx      # Expanded trial view
│   │   └── DossierView.jsx      # Eligibility dossier display
│   └── hooks/
│       └── useTaskPoller.js     # Poll background task status
└── vite.config.js         # Dev proxy /api → localhost:8000
```
