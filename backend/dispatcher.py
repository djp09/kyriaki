"""Agent task dispatcher — creates, executes, and tracks agent tasks."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db_models import AgentEventDB, AgentTaskDB, HumanGateDB, TaskStatus
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


async def _execute_task(
    session: AsyncSession,
    task: AgentTaskDB,
    agent_type: str,
    patient_id: uuid.UUID,
    input_data: dict[str, Any],
) -> None:
    """Run an agent, update task status, emit events. Inner logic shared by sync/background dispatch."""
    from agents import AgentContext  # deferred to avoid circular import

    async def emit(event_type: str, data: dict[str, Any] | None = None) -> None:
        session.add(AgentEventDB(task_id=task.id, event_type=event_type, data=data or {}))
        await session.flush()

    task.status = TaskStatus.running.value
    task.started_at = datetime.now(timezone.utc)
    await emit("started")

    try:
        agent = _registry[agent_type]()
        ctx = AgentContext(task_id=task.id, patient_id=patient_id, input_data=input_data, emit=emit)
        result = await agent.execute(ctx)
    except Exception as e:
        task.status = TaskStatus.failed.value
        task.error = f"{type(e).__name__}: {e}"
        task.completed_at = datetime.now(timezone.utc)
        await emit("failed", {"error": task.error})
        logger.error("task.failed", task_id=str(task.id), agent_type=agent_type, error=task.error)
        return

    if result.gate_request:
        task.status = TaskStatus.blocked.value
        task.output_data = result.output_data
        session.add(
            HumanGateDB(
                task_id=task.id,
                gate_type=result.gate_request.gate_type,
                status="pending",
                requested_data=result.gate_request.requested_data,
            )
        )
        await emit("blocked", {"gate_type": result.gate_request.gate_type})
        logger.info("task.blocked", task_id=str(task.id), gate_type=result.gate_request.gate_type)
    elif result.success:
        task.status = TaskStatus.completed.value
        task.output_data = result.output_data
        task.completed_at = datetime.now(timezone.utc)
        await emit("completed")
        logger.info("task.completed", task_id=str(task.id), agent_type=agent_type)
    else:
        task.status = TaskStatus.failed.value
        task.error = result.error
        task.completed_at = datetime.now(timezone.utc)
        await emit("failed", {"error": result.error})
        logger.error("task.failed", task_id=str(task.id), agent_type=agent_type, error=result.error)


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
    await asyncio.sleep(0.1)

    try:
        async with async_session() as session:
            task = await session.get(AgentTaskDB, task_id)
            if not task:
                logger.error("background.task_not_found", task_id=str(task_id))
                return
            await _execute_task(session, task, agent_type, patient_id, input_data)
            await session.commit()
    except Exception as e:
        logger.error("background.unhandled", task_id=str(task_id), error=f"{type(e).__name__}: {e}")


async def dispatch_background(
    session: AsyncSession,
    agent_type: str,
    patient_id: uuid.UUID,
    input_data: dict[str, Any] | None = None,
    parent_task_id: uuid.UUID | None = None,
) -> AgentTaskDB:
    """Background dispatch — creates task, returns immediately, agent runs in background.

    The caller's session must commit (via get_db dependency) before the background
    task modifies the record. This is safe because asyncio is cooperative: the
    background coroutine won't execute until the current coroutine yields.
    """
    task = _create_task(session, agent_type, patient_id, input_data, parent_task_id)
    await session.flush()

    # Capture primitives — don't pass ORM objects across session boundaries
    t_id, t_input = task.id, task.input_data

    bg = asyncio.create_task(_run_in_background(t_id, agent_type, patient_id, t_input))
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)

    return task
