from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import asyncio
import re
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import agents as _agents  # noqa: F401 — triggers agent registration
from config import get_settings
from database import get_db
from db_models import AgentTaskDB, HumanGateDB
from db_service import save_patient_profile
from dispatcher import dispatch
from logging_config import get_logger, setup_logging
from matching_engine import match_trials
from middleware import RequestLoggingMiddleware
from models import DossierRequest, GateResolution, MatchRequest, MatchResponse, PatientProfile, TaskResponse
from trials_client import get_trial

settings = get_settings()
setup_logging(log_level=settings.log_level, log_format=settings.log_format)
logger = get_logger("kyriaki.main")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Auto-create tables in dev mode (SQLite). Production uses alembic."""
    if settings.database_url.startswith("sqlite"):
        from database import engine
        from db_models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("db.auto_created_tables", backend="sqlite")
    yield


app = FastAPI(title="Kyriaki", description="Clinical trial matching engine for cancer patients", lifespan=lifespan)

# Request logging middleware (added first so it wraps everything)
app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(status_code: int, message: str, detail: str | None = None) -> JSONResponse:
    body: dict = {"error": True, "message": message}
    if detail:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    errors = exc.errors()
    fields = [e.get("loc", ["unknown"])[-1] for e in errors[:3]]
    logger.warning("validation_error", fields=fields, error_count=len(errors))
    return _error_response(
        422,
        f"Invalid input. Please check these fields: {', '.join(str(f) for f in fields)}",
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", exc_type=type(exc).__name__, error=str(exc), exc_info=True)
    return _error_response(
        500,
        "Something went wrong on our end. Please try again in a moment.",
    )


@app.get("/api/health")
async def health():
    from database import check_db_health

    db_ok = await check_db_health()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unavailable",
    }


@app.post("/api/intake")
async def intake(patient: PatientProfile):
    return {"status": "accepted", "patient": patient}


@app.post("/api/match", response_model=MatchResponse)
async def match(request: MatchRequest):
    try:
        result = await asyncio.wait_for(
            match_trials(request.patient, max_results=request.max_results),
            timeout=settings.match_timeout,
        )
        return MatchResponse(**result)
    except TimeoutError:
        return _error_response(
            504,
            "The matching process took too long. Please try again with fewer results or a more specific cancer type.",
        )
    except Exception as e:
        logger.error("match.pipeline_error", exc_type=type(e).__name__, error=str(e), exc_info=True)
        return _error_response(
            500,
            "We encountered an error while matching trials. Please try again.",
        )


@app.get("/api/trials/{nct_id}")
async def trial_detail(nct_id: str):
    if not _NCT_RE.match(nct_id):
        raise HTTPException(400, "Invalid trial ID format")
    trial = await get_trial(nct_id)
    if trial is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    return trial


# --- Agent orchestration endpoints ---

_NCT_RE = re.compile(r"^NCT\d{2,11}$")


def _parse_uuid(value: str) -> uuid.UUID:
    """Parse a UUID string, raising 400 on invalid input."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(400, "Invalid ID format") from exc


def _task_to_response(task: AgentTaskDB) -> TaskResponse:
    return TaskResponse(
        task_id=str(task.id),
        agent_type=task.agent_type,
        status=task.status,
        output_data=task.output_data,
        error=task.error,
        created_at=task.created_at.isoformat() if task.created_at else "",
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


@app.post("/api/agents/match", response_model=TaskResponse)
async def agent_match(request: MatchRequest, db: AsyncSession = Depends(get_db)):
    patient_data = request.patient.model_dump()
    patient = await save_patient_profile(db, patient_data)

    task = await dispatch(
        db,
        "matching",
        patient.id,
        input_data={"patient": patient_data, "max_results": request.max_results},
    )
    return _task_to_response(task)


@app.post("/api/agents/dossier", response_model=TaskResponse)
async def agent_dossier(request: DossierRequest, db: AsyncSession = Depends(get_db)):
    matching_task = await db.get(AgentTaskDB, _parse_uuid(request.matching_task_id))
    if not matching_task or matching_task.status != "completed":
        raise HTTPException(404, "Matching task not found or not completed")

    task = await dispatch(
        db,
        "dossier",
        matching_task.patient_id,
        input_data={
            "patient": matching_task.input_data["patient"],
            "matches": matching_task.output_data["matches"],
            "patient_summary": matching_task.output_data.get("patient_summary", ""),
            "top_n": request.top_n,
        },
        parent_task_id=matching_task.id,
    )
    return _task_to_response(task)


@app.get("/api/agents/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(AgentTaskDB, _parse_uuid(task_id))
    if not task:
        raise HTTPException(404, "Task not found")
    return _task_to_response(task)


@app.post("/api/agents/gates/{gate_id}/resolve")
async def resolve_gate(gate_id: str, resolution: GateResolution, db: AsyncSession = Depends(get_db)):
    gate = await db.get(HumanGateDB, _parse_uuid(gate_id))
    if not gate or gate.status != "pending":
        raise HTTPException(404, "Gate not found or already resolved")

    gate.status = resolution.status
    gate.resolved_by = resolution.resolved_by
    gate.resolution_data = {"notes": resolution.notes} if resolution.notes else {}
    gate.resolved_at = datetime.now(timezone.utc)

    task = await db.get(AgentTaskDB, gate.task_id)
    if resolution.status == "approved":
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
    else:
        task.status = "failed"
        task.error = f"Gate rejected by {resolution.resolved_by}"
        task.completed_at = datetime.now(timezone.utc)

    return {"status": "resolved", "gate_status": resolution.status}
