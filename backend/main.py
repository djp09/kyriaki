from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import asyncio
import json
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import agents as _agents  # noqa: F401 — triggers agent registration
from config import get_settings
from database import async_session, get_db
from db_models import AgentEventDB, AgentTaskDB, HumanGateDB, TaskStatus
from db_service import (
    get_patient_activity,
    get_task_with_gates,
    list_events_for_task,
    list_gates,
    list_tasks_for_patient,
    save_patient_profile,
)
from dispatcher import dispatch_background, recover_stale_tasks
from logging_config import get_logger, setup_logging
from matching_engine import match_trials
from middleware import RequestLoggingMiddleware
from models import (
    ActivityItem,
    DossierRequest,
    EnrollmentRequest,
    EventResponse,
    GateResolution,
    GateResponse,
    MatchRequest,
    MatchResponse,
    MonitorRequest,
    OutcomeResponse,
    OutcomeStats,
    OutcomeUpdate,
    OutreachRequest,
    PatientProfile,
    TaskDetailResponse,
    TaskResponse,
)
from tools.ground_truth import compute_outcome_stats, get_outcomes_for_patient, upsert_outcome
from trials_client import close_http_client, get_trial

settings = get_settings()
setup_logging(log_level=settings.log_level, log_format=settings.log_format)
logger = get_logger("kyriaki.main")


async def _monitor_loop() -> None:
    """Background loop: periodically dispatches MonitorAgent for all tracked patients."""
    while True:
        await asyncio.sleep(settings.monitor_interval_seconds)
        try:
            async with async_session() as session:
                # Find all patients with completed matching tasks
                stmt = (
                    select(AgentTaskDB.patient_id)
                    .where(AgentTaskDB.agent_type == "matching", AgentTaskDB.status == "completed")
                    .distinct()
                )
                result = await session.execute(stmt)
                patient_ids = [row[0] for row in result.all()]

                for pid in patient_ids:
                    # Gather watched trials from completed matching tasks
                    task_stmt = (
                        select(AgentTaskDB)
                        .where(
                            AgentTaskDB.patient_id == pid,
                            AgentTaskDB.agent_type == "matching",
                            AgentTaskDB.status == "completed",
                        )
                        .order_by(AgentTaskDB.created_at.desc())
                        .limit(1)
                    )
                    task_result = await session.execute(task_stmt)
                    task = task_result.scalars().first()
                    if not task or not task.output_data:
                        continue

                    watches = [
                        {"nct_id": m["nct_id"], "last_status": m.get("overall_status", ""), "last_site_count": 0}
                        for m in task.output_data.get("matches", [])
                    ]
                    if watches:
                        await dispatch_background(session, "monitor", pid, input_data={"watches": watches})
                await session.commit()
            logger.info("monitor.loop_complete", patients_checked=len(patient_ids))
        except Exception as e:
            logger.error("monitor.loop_error", error=f"{type(e).__name__}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Auto-create tables in dev mode (SQLite). Production uses alembic."""
    if settings.database_url.startswith("sqlite"):
        from database import engine
        from db_models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("db.auto_created_tables", backend="sqlite")

    # Recover any tasks orphaned by a prior process restart
    async with async_session() as session:
        recovered = await recover_stale_tasks(session)
        await session.commit()
        if recovered:
            logger.info("startup.recovered_stale_tasks", count=recovered)

    monitor_task = None
    if settings.monitor_enabled:
        monitor_task = asyncio.create_task(_monitor_loop())
        logger.info("monitor.started", interval=settings.monitor_interval_seconds)

    yield

    if monitor_task:
        monitor_task.cancel()
    await close_http_client()


app = FastAPI(title="Kyriaki", description="Clinical trial matching engine for cancer patients", lifespan=lifespan)

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
    return _error_response(422, f"Invalid input. Please check these fields: {', '.join(str(f) for f in fields)}")


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", exc_type=type(exc).__name__, error=str(exc), exc_info=True)
    return _error_response(500, "Something went wrong on our end. Please try again in a moment.")


# --- Core endpoints ---


@app.get("/api/health")
async def health():
    from database import check_db_health

    db_ok = await check_db_health()
    return {"status": "ok" if db_ok else "degraded", "database": "connected" if db_ok else "unavailable"}


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
        return _error_response(504, "The matching process took too long. Please try again.")
    except Exception as e:
        logger.error("match.pipeline_error", exc_type=type(e).__name__, error=str(e), exc_info=True)
        return _error_response(500, "We encountered an error while matching trials. Please try again.")


_NCT_RE = re.compile(r"^NCT\d{2,11}$")


@app.get("/api/trials/{nct_id}")
async def trial_detail(nct_id: str):
    if not _NCT_RE.match(nct_id):
        raise HTTPException(400, "Invalid trial ID format")
    trial = await get_trial(nct_id)
    if trial is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    return trial


# --- Helpers ---


def _parse_uuid(value: str) -> uuid.UUID:
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


def _task_to_detail_response(task: AgentTaskDB) -> TaskDetailResponse:
    gates = [_gate_to_response(g) for g in task.gates] if hasattr(task, "gates") and task.gates else []
    return TaskDetailResponse(
        task_id=str(task.id),
        agent_type=task.agent_type,
        status=task.status,
        output_data=task.output_data,
        error=task.error,
        created_at=task.created_at.isoformat() if task.created_at else "",
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        parent_task_id=str(task.parent_task_id) if task.parent_task_id else None,
        gates=gates,
    )


def _gate_to_response(gate: HumanGateDB) -> GateResponse:
    return GateResponse(
        gate_id=str(gate.id),
        task_id=str(gate.task_id),
        gate_type=gate.gate_type,
        status=gate.status,
        requested_data=gate.requested_data,
        resolution_data=gate.resolution_data,
        created_at=gate.created_at.isoformat() if gate.created_at else "",
        resolved_at=gate.resolved_at.isoformat() if gate.resolved_at else None,
        resolved_by=gate.resolved_by,
    )


def _event_to_response(event: AgentEventDB) -> EventResponse:
    return EventResponse(
        event_id=str(event.id),
        task_id=str(event.task_id),
        event_type=event.event_type,
        data=event.data,
        created_at=event.created_at.isoformat() if event.created_at else "",
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# --- Agent orchestration endpoints ---
# NOTE: List routes MUST be registered before parameterized routes.


@app.post("/api/agents/match", response_model=TaskResponse)
async def agent_match(request: MatchRequest, db: AsyncSession = Depends(get_db)):
    patient_data = request.patient.model_dump()
    patient = await save_patient_profile(db, patient_data)

    task = await dispatch_background(
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

    task = await dispatch_background(
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


@app.get("/api/agents/tasks", response_model=list[TaskDetailResponse])
async def list_agent_tasks(
    patient_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if patient_id:
        tasks = await list_tasks_for_patient(db, _parse_uuid(patient_id))
    else:
        from sqlalchemy.orm import joinedload

        stmt = (
            select(AgentTaskDB)
            .options(joinedload(AgentTaskDB.gates))
            .order_by(AgentTaskDB.created_at.desc())
            .limit(100)
        )
        result = await db.execute(stmt)
        tasks = list(result.unique().scalars().all())
    return [_task_to_detail_response(t) for t in tasks]


@app.get("/api/agents/gates", response_model=list[GateResponse])
async def list_agent_gates(
    status: str = Query(default="pending", pattern="^(pending|approved|rejected)$"),
    db: AsyncSession = Depends(get_db),
):
    gates = await list_gates(db, status=status)
    return [_gate_to_response(g) for g in gates]


@app.get("/api/agents/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await get_task_with_gates(db, _parse_uuid(task_id))
    if not task:
        raise HTTPException(404, "Task not found")
    return _task_to_detail_response(task)


@app.get("/api/agents/tasks/{task_id}/events", response_model=list[EventResponse])
async def get_task_events(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(AgentTaskDB, _parse_uuid(task_id))
    if not task:
        raise HTTPException(404, "Task not found")
    events = await list_events_for_task(db, task.id)
    return [_event_to_response(e) for e in events]


@app.get("/api/agents/tasks/{task_id}/stream")
async def stream_task_events(task_id: str):
    """SSE endpoint — streams task events in real-time until terminal state."""
    task_uuid = _parse_uuid(task_id)
    terminal = {TaskStatus.completed.value, TaskStatus.failed.value, TaskStatus.blocked.value}

    async def event_generator():
        last_count = 0
        try:
            while True:
                async with async_session() as session:
                    task = await session.get(AgentTaskDB, task_uuid)
                    if not task:
                        yield _sse("error", {"message": "Task not found"})
                        return
                    events = await list_events_for_task(session, task_uuid)
                    task_status = task.status

                for ev in events[last_count:]:
                    yield _sse(
                        ev.event_type,
                        {
                            "event_id": str(ev.id),
                            "data": ev.data,
                            "created_at": ev.created_at.isoformat() if ev.created_at else "",
                        },
                    )
                last_count = len(events)

                # Also send task status updates
                yield _sse("task_update", {"status": task_status})

                if task_status in terminal:
                    yield _sse("done", {"final_status": task_status})
                    return
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/agents/enrollment", response_model=TaskResponse)
async def agent_enrollment(request: EnrollmentRequest, db: AsyncSession = Depends(get_db)):
    dossier_task = await db.get(AgentTaskDB, _parse_uuid(request.dossier_task_id))
    if not dossier_task or dossier_task.status != "completed":
        raise HTTPException(404, "Dossier task not found or not completed")

    task = await dispatch_background(
        db,
        "enrollment",
        dossier_task.patient_id,
        input_data={
            "patient": dossier_task.input_data.get("patient", {}),
            "dossier": dossier_task.output_data.get("dossier", {}),
            "trial_nct_id": request.trial_nct_id,
        },
        parent_task_id=dossier_task.id,
    )
    return _task_to_response(task)


@app.post("/api/agents/outreach", response_model=TaskResponse)
async def agent_outreach(request: OutreachRequest, db: AsyncSession = Depends(get_db)):
    enrollment_task = await db.get(AgentTaskDB, _parse_uuid(request.enrollment_task_id))
    if not enrollment_task or enrollment_task.status != "completed":
        raise HTTPException(404, "Enrollment task not found or not completed")

    task = await dispatch_background(
        db,
        "outreach",
        enrollment_task.patient_id,
        input_data={
            **enrollment_task.output_data,
            "patient": enrollment_task.input_data.get("patient", {}),
        },
        parent_task_id=enrollment_task.id,
    )
    return _task_to_response(task)


@app.post("/api/agents/monitor", response_model=TaskResponse)
async def agent_monitor(request: MonitorRequest, db: AsyncSession = Depends(get_db)):
    patient_id = _parse_uuid(request.patient_id)

    # Build watch list from latest matching task
    stmt = (
        select(AgentTaskDB)
        .where(
            AgentTaskDB.patient_id == patient_id,
            AgentTaskDB.agent_type == "matching",
            AgentTaskDB.status == "completed",
        )
        .order_by(AgentTaskDB.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    match_task = result.scalars().first()
    if not match_task or not match_task.output_data:
        raise HTTPException(404, "No completed matching task found for this patient")

    watches = [
        {"nct_id": m["nct_id"], "last_status": m.get("overall_status", ""), "last_site_count": 0}
        for m in match_task.output_data.get("matches", [])
    ]

    task = await dispatch_background(db, "monitor", patient_id, input_data={"watches": watches})
    return _task_to_response(task)


@app.get("/api/agents/monitor/status")
async def monitor_status():
    return {
        "enabled": settings.monitor_enabled,
        "interval_seconds": settings.monitor_interval_seconds,
    }


@app.post("/api/agents/gates/{gate_id}/resolve")
async def resolve_gate(gate_id: str, resolution: GateResolution, db: AsyncSession = Depends(get_db)):
    gate = await db.get(HumanGateDB, _parse_uuid(gate_id))
    if not gate or gate.status != "pending":
        raise HTTPException(404, "Gate not found or already resolved")

    gate.status = resolution.status
    gate.resolved_by = resolution.resolved_by
    gate.resolution_data = {"notes": resolution.notes, "chain_to_trial": resolution.chain_to_trial}
    gate.resolved_at = datetime.now(timezone.utc)

    task = await db.get(AgentTaskDB, gate.task_id)
    if resolution.status == "approved":
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)

        # Auto-chain: dossier approved → enrollment
        if gate.gate_type == "dossier_review" and resolution.chain_to_trial:
            # Ground truth: record navigator approved this trial
            dossier = task.output_data.get("dossier", {})
            section = next(
                (s for s in dossier.get("sections", []) if s.get("nct_id") == resolution.chain_to_trial),
                {},
            )
            await upsert_outcome(
                db,
                patient_id=task.patient_id,
                nct_id=resolution.chain_to_trial,
                match_score=section.get("match_score") or section.get("revised_score"),
                revised_score=section.get("revised_score"),
                navigator_decision="approved",
            )

            await dispatch_background(
                db,
                "enrollment",
                task.patient_id,
                input_data={
                    "patient": task.input_data.get("patient", {}),
                    "dossier": task.output_data.get("dossier", {}),
                    "trial_nct_id": resolution.chain_to_trial,
                },
                parent_task_id=task.id,
            )

        # Auto-chain: enrollment approved → outreach
        elif gate.gate_type == "enrollment_review":
            await dispatch_background(
                db,
                "outreach",
                task.patient_id,
                input_data={**task.output_data, "patient": task.input_data.get("patient", {})},
                parent_task_id=task.id,
            )

        # Ground truth: outreach approved → record site response
        elif gate.gate_type == "outreach_review":
            trial_nct_id = task.output_data.get("trial_nct_id") or task.input_data.get("trial_nct_id", "")
            if trial_nct_id:
                await upsert_outcome(
                    db,
                    patient_id=task.patient_id,
                    nct_id=trial_nct_id,
                    site_response="accepted",
                    outcome_notes=resolution.notes,
                )

    else:
        task.status = "failed"
        task.error = f"Gate rejected by {resolution.resolved_by}"
        task.completed_at = datetime.now(timezone.utc)

        # Ground truth: record rejection
        if gate.gate_type == "dossier_review" and resolution.chain_to_trial:
            await upsert_outcome(
                db,
                patient_id=task.patient_id,
                nct_id=resolution.chain_to_trial,
                navigator_decision="rejected",
                outcome_notes=resolution.notes,
            )

    return {"status": "resolved", "gate_status": resolution.status}


@app.get("/api/patients/{patient_id}/activity")
async def patient_activity(patient_id: str, db: AsyncSession = Depends(get_db)):
    pid = _parse_uuid(patient_id)
    items = await get_patient_activity(db, pid)
    return {"patient_id": patient_id, "items": [ActivityItem(**i) for i in items]}


# --- Ground truth feedback endpoints ---
# NOTE: /stats must be registered before /{patient_id} to avoid route collision.


@app.get("/api/outcomes/stats", response_model=OutcomeStats)
async def outcome_stats(db: AsyncSession = Depends(get_db)):
    """Aggregated accuracy statistics across all outcomes."""
    result = await compute_outcome_stats(db)
    return OutcomeStats(**result.data)


@app.get("/api/outcomes/{patient_id}", response_model=list[OutcomeResponse])
async def list_outcomes(patient_id: str, db: AsyncSession = Depends(get_db)):
    """Get all outcomes for a patient."""
    pid = _parse_uuid(patient_id)
    result = await get_outcomes_for_patient(db, pid)
    return [OutcomeResponse(**o) for o in result.data]


@app.post("/api/outcomes/{patient_id}/{nct_id}", response_model=OutcomeResponse)
async def record_outcome(patient_id: str, nct_id: str, update: OutcomeUpdate, db: AsyncSession = Depends(get_db)):
    """Manually record or update a screening outcome for a patient-trial pairing."""
    pid = _parse_uuid(patient_id)
    if not _NCT_RE.match(nct_id):
        raise HTTPException(400, "Invalid trial ID format")

    await upsert_outcome(
        db,
        patient_id=pid,
        nct_id=nct_id,
        site_response=update.site_response,
        screening_result=update.screening_result,
        outcome_notes=update.notes,
    )

    # Fetch and return the updated outcome
    result = await get_outcomes_for_patient(db, pid)
    outcome = next((o for o in result.data if o["nct_id"] == nct_id), None)
    if not outcome:
        raise HTTPException(500, "Failed to retrieve recorded outcome")
    return OutcomeResponse(**outcome)
