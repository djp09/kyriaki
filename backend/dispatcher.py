"""Agent task dispatcher — creates, executes, and tracks agent tasks.

Handles duplicate dispatch prevention, pipeline state tracking,
task retry, and stale task recovery.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db_models import (
    AgentEventDB,
    AgentTaskDB,
    HumanGateDB,
    PatientPipelineDB,
    TaskStatus,
    TrialWatchDB,
)
from logging_config import get_logger

logger = get_logger("kyriaki.dispatcher")

# Agent registry — populated by @register_agent decorator
_registry: dict[str, type] = {}

# Track background tasks to prevent garbage collection
_background_tasks: set[asyncio.Task] = set()


def register_agent(cls: type) -> type:
    """Decorator: register an agent class by its agent_type."""
    _registry[cls.agent_type] = cls
    return cls


def get_registry() -> dict[str, type]:
    return _registry


# --- Pipeline state helpers ---

# Maps agent_type to pipeline stage name
_AGENT_TO_STAGE = {
    "matching": "matching",
    "dossier": "dossier",
    "enrollment": "enrollment",
    "outreach": "outreach",
    "monitor": "monitoring",
}


async def get_or_create_pipeline(session: AsyncSession, patient_id: uuid.UUID) -> PatientPipelineDB:
    """Get or create the pipeline state row for a patient."""
    stmt = select(PatientPipelineDB).where(PatientPipelineDB.patient_id == patient_id)
    result = await session.execute(stmt)
    pipeline = result.scalars().first()
    if not pipeline:
        pipeline = PatientPipelineDB(patient_id=patient_id, current_stage="matching")
        session.add(pipeline)
        await session.flush()
    return pipeline


async def _update_pipeline_state(
    session: AsyncSession,
    patient_id: uuid.UUID,
    *,
    stage: str | None = None,
    task_id: uuid.UUID | None = None,
    gate_id: uuid.UUID | None = None,
    completed_stage: str | None = None,
) -> None:
    """Update the pipeline state for a patient."""
    pipeline = await get_or_create_pipeline(session, patient_id)
    if stage is not None:
        pipeline.current_stage = stage
    if task_id is not None:
        pipeline.current_task_id = task_id
    if gate_id is not None:
        pipeline.blocked_at_gate_id = gate_id
    elif stage is not None:
        # Moving to a new stage clears the gate block
        pipeline.blocked_at_gate_id = None
    if completed_stage is not None:
        pipeline.last_completed_stage = completed_stage
        pipeline.last_completed_at = datetime.now(timezone.utc)


# --- Duplicate dispatch guard ---


async def has_active_task(
    session: AsyncSession,
    agent_type: str,
    patient_id: uuid.UUID,
) -> AgentTaskDB | None:
    """Check if there's already a pending/running task of this type for this patient.

    Returns the existing task if found, None otherwise.
    """
    active_statuses = [TaskStatus.pending.value, TaskStatus.running.value]
    stmt = (
        select(AgentTaskDB)
        .where(
            AgentTaskDB.patient_id == patient_id,
            AgentTaskDB.agent_type == agent_type,
            AgentTaskDB.status.in_(active_statuses),
        )
        .order_by(AgentTaskDB.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


# --- Trial watch persistence ---


async def upsert_trial_watches(
    session: AsyncSession,
    patient_id: uuid.UUID,
    watches: list[dict],
) -> int:
    """Create or update trial watch records from matching results.

    Returns count of watches upserted.
    """
    count = 0
    for w in watches:
        nct_id = w.get("nct_id", "")
        if not nct_id:
            continue

        stmt = select(TrialWatchDB).where(
            TrialWatchDB.patient_id == patient_id,
            TrialWatchDB.nct_id == nct_id,
        )
        result = await session.execute(stmt)
        existing = result.scalars().first()

        if existing:
            existing.last_status = w.get("last_status", existing.last_status)
            existing.last_site_count = w.get("last_site_count", existing.last_site_count)
        else:
            session.add(
                TrialWatchDB(
                    patient_id=patient_id,
                    nct_id=nct_id,
                    last_status=w.get("last_status", ""),
                    last_site_count=w.get("last_site_count", 0),
                )
            )
        count += 1
    await session.flush()
    return count


async def get_trial_watches(session: AsyncSession, patient_id: uuid.UUID) -> list[dict]:
    """Get all trial watches for a patient, for the monitor agent."""
    stmt = select(TrialWatchDB).where(TrialWatchDB.patient_id == patient_id)
    result = await session.execute(stmt)
    watches = result.scalars().all()
    return [
        {
            "nct_id": w.nct_id,
            "last_status": w.last_status or "",
            "last_site_count": w.last_site_count,
        }
        for w in watches
    ]


async def update_watch_after_check(
    session: AsyncSession,
    patient_id: uuid.UUID,
    nct_id: str,
    new_status: str | None = None,
    new_site_count: int | None = None,
) -> None:
    """Update a trial watch record after the monitor agent checks it."""
    stmt = select(TrialWatchDB).where(
        TrialWatchDB.patient_id == patient_id,
        TrialWatchDB.nct_id == nct_id,
    )
    result = await session.execute(stmt)
    watch = result.scalars().first()
    if watch:
        if new_status is not None:
            watch.last_status = new_status
        if new_site_count is not None:
            watch.last_site_count = new_site_count
        watch.last_checked_at = datetime.now(timezone.utc)


# --- Core dispatch ---


async def _execute_task(
    session: AsyncSession,
    task: AgentTaskDB,
    agent_type: str,
    patient_id: uuid.UUID,
    input_data: dict[str, Any],
) -> None:
    """Run an agent, update task status, emit events. Inner logic shared by sync/background dispatch."""
    from agents import AgentContext  # deferred to avoid circular import

    pending_events: list[AgentEventDB] = []

    async def emit(event_type: str, data: dict[str, Any] | None = None) -> None:
        pending_events.append(AgentEventDB(task_id=task.id, event_type=event_type, data=data or {}))

    async def flush_events() -> None:
        if pending_events:
            session.add_all(pending_events)
            pending_events.clear()
            await session.flush()

    task.status = TaskStatus.running.value
    task.started_at = datetime.now(timezone.utc)
    stage = _AGENT_TO_STAGE.get(agent_type, agent_type)
    await _update_pipeline_state(session, patient_id, stage=stage, task_id=task.id)
    await emit("started")
    await flush_events()

    try:
        agent = _registry[agent_type]()
        ctx = AgentContext(task_id=task.id, patient_id=patient_id, input_data=input_data, emit=emit, db_session=session)
        result = await agent.execute(ctx)
    except Exception as e:
        task.status = TaskStatus.failed.value
        task.error = f"{type(e).__name__}: {e}"
        task.completed_at = datetime.now(timezone.utc)
        await emit("failed", {"error": task.error})
        await flush_events()
        logger.error("task.failed", task_id=str(task.id), agent_type=agent_type, error=task.error)
        return

    if result.gate_request:
        task.status = TaskStatus.blocked.value
        task.output_data = result.output_data
        gate = HumanGateDB(
            task_id=task.id,
            gate_type=result.gate_request.gate_type,
            status="pending",
            requested_data=result.gate_request.requested_data,
        )
        session.add(gate)
        await session.flush()  # flush to get gate.id
        await _update_pipeline_state(session, patient_id, gate_id=gate.id)
        await emit("blocked", {"gate_type": result.gate_request.gate_type})
        logger.info("task.blocked", task_id=str(task.id), gate_type=result.gate_request.gate_type)
    elif result.success:
        task.status = TaskStatus.completed.value
        task.output_data = result.output_data
        task.completed_at = datetime.now(timezone.utc)
        await _update_pipeline_state(session, patient_id, completed_stage=stage)

        # Persist trial watches when matching completes
        if agent_type == "matching" and result.output_data:
            matches = result.output_data.get("matches", [])
            watch_data = [
                {"nct_id": m["nct_id"], "last_status": m.get("overall_status", "")} for m in matches if m.get("nct_id")
            ]
            if watch_data:
                await upsert_trial_watches(session, patient_id, watch_data)

        await emit("completed")
        logger.info("task.completed", task_id=str(task.id), agent_type=agent_type)

        # Auto-chain: matching → dossier (if configured)
        if agent_type == "matching" and result.output_data:
            from config import get_settings as _get_settings

            if _get_settings().auto_chain_matching_to_dossier:
                matches = result.output_data.get("matches", [])
                if matches:
                    logger.info("dispatcher.auto_chain", from_agent="matching", to_agent="dossier")
                    # Note: this is a synchronous dispatch within the same session,
                    # not background, since we're already in a background task
                    dossier_task = _create_task(
                        session,
                        "dossier",
                        patient_id,
                        {
                            "matches": matches,
                            "patient_summary": result.output_data.get("patient_summary", ""),
                        },
                        task.id,
                    )
                    await session.flush()
                    await _execute_task(session, dossier_task, "dossier", patient_id, dossier_task.input_data)
    else:
        task.status = TaskStatus.failed.value
        task.error = result.error
        task.completed_at = datetime.now(timezone.utc)
        await emit("failed", {"error": result.error})
        logger.error("task.failed", task_id=str(task.id), agent_type=agent_type, error=result.error)

    await flush_events()


def _create_task(
    session: AsyncSession,
    agent_type: str,
    patient_id: uuid.UUID,
    input_data: dict[str, Any] | None,
    parent_task_id: uuid.UUID | None,
) -> AgentTaskDB:
    """Create a pending task record (does not flush)."""
    if agent_type not in _registry:
        raise ValueError(f"Unknown agent type: {agent_type}")
    task = AgentTaskDB(
        agent_type=agent_type,
        status=TaskStatus.pending.value,
        patient_id=patient_id,
        input_data=input_data or {},
        parent_task_id=parent_task_id,
    )
    session.add(task)
    return task


async def recover_stale_tasks(session: AsyncSession) -> int:
    """Mark any 'running' or 'pending' tasks as failed on startup.

    These tasks were orphaned by a process restart. Returns the count of
    recovered tasks.
    """
    stale_statuses = [TaskStatus.running.value, TaskStatus.pending.value]
    stmt = (
        update(AgentTaskDB)
        .where(AgentTaskDB.status.in_(stale_statuses))
        .values(
            status=TaskStatus.failed.value,
            error="Process restarted — task was orphaned",
            completed_at=datetime.now(timezone.utc),
        )
    )
    result = await session.execute(stmt)
    count = result.rowcount
    if count:
        logger.warning("dispatcher.recovered_stale_tasks", count=count)
    return count


async def dispatch(
    session: AsyncSession,
    agent_type: str,
    patient_id: uuid.UUID,
    input_data: dict[str, Any] | None = None,
    parent_task_id: uuid.UUID | None = None,
) -> AgentTaskDB:
    """Synchronous dispatch — blocks until the agent completes. Returns the finished task."""
    task = _create_task(session, agent_type, patient_id, input_data, parent_task_id)
    await session.flush()
    await _execute_task(session, task, agent_type, patient_id, task.input_data)
    return task


async def _run_in_background(
    task_id: uuid.UUID,
    agent_type: str,
    patient_id: uuid.UUID,
    input_data: dict[str, Any],
) -> None:
    """Background coroutine: opens its own DB session and runs the agent."""
    from database import async_session

    # Yield control so the HTTP response commits its session first.
    # Critical for SQLite which uses file-level locking.
    logger.info("background.starting", task_id=str(task_id), agent_type=agent_type)
    await asyncio.sleep(0.5)

    try:
        async with async_session() as session:
            task = await session.get(AgentTaskDB, task_id)
            if not task:
                logger.error("background.task_not_found", task_id=str(task_id))
                return
            logger.info("background.task_loaded", task_id=str(task_id), status=task.status)
            await _execute_task(session, task, agent_type, patient_id, input_data)
            await session.commit()
            logger.info("background.committed", task_id=str(task_id))
    except Exception as e:
        logger.error("background.unhandled", task_id=str(task_id), error=f"{type(e).__name__}: {e}")


async def dispatch_background(
    session: AsyncSession,
    agent_type: str,
    patient_id: uuid.UUID,
    input_data: dict[str, Any] | None = None,
    parent_task_id: uuid.UUID | None = None,
    *,
    allow_duplicate: bool = False,
) -> AgentTaskDB:
    """Background dispatch — creates task, returns immediately, agent runs in background.

    The caller's session must commit (via get_db dependency) before the background
    task modifies the record. This is safe because asyncio is cooperative: the
    background coroutine won't execute until the current coroutine yields.

    If allow_duplicate is False (default), returns the existing active task instead
    of creating a new one.
    """
    if not allow_duplicate:
        existing = await has_active_task(session, agent_type, patient_id)
        if existing:
            logger.info(
                "dispatcher.duplicate_prevented",
                agent_type=agent_type,
                patient_id=str(patient_id),
                existing_task_id=str(existing.id),
            )
            return existing

    task = _create_task(session, agent_type, patient_id, input_data, parent_task_id)
    await session.flush()

    # Capture primitives — don't pass ORM objects across session boundaries
    t_id, t_input = task.id, task.input_data

    bg = asyncio.create_task(_run_in_background(t_id, agent_type, patient_id, t_input))
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)

    return task


async def retry_task(
    session: AsyncSession,
    failed_task_id: uuid.UUID,
) -> AgentTaskDB | None:
    """Retry a failed task by creating a new task with the same input.

    Returns the new task, or None if the original wasn't failed.
    """
    original = await session.get(AgentTaskDB, failed_task_id)
    if not original or original.status != TaskStatus.failed.value:
        return None

    return await dispatch_background(
        session,
        original.agent_type,
        original.patient_id,
        input_data=original.input_data,
        parent_task_id=original.parent_task_id,
    )
