"""Agent task dispatcher — creates, executes, and tracks agent tasks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db_models import AgentEventDB, AgentTaskDB, HumanGateDB, TaskStatus
from logging_config import get_logger

logger = get_logger("kyriaki.dispatcher")

# Agent registry — populated by @register_agent decorator
_registry: dict[str, type] = {}


def register_agent(cls: type) -> type:
    """Decorator: register an agent class by its agent_type."""
    _registry[cls.agent_type] = cls
    return cls


def get_registry() -> dict[str, type]:
    return _registry


async def dispatch(
    session: AsyncSession,
    agent_type: str,
    patient_id: uuid.UUID,
    input_data: dict[str, Any] | None = None,
    parent_task_id: uuid.UUID | None = None,
) -> AgentTaskDB:
    """Create a task record, execute the agent, return the task.

    The caller owns the session (commit/rollback).
    """
    from agents import AgentContext  # deferred to avoid circular import

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
    await session.flush()

    async def emit(event_type: str, data: dict[str, Any] | None = None) -> None:
        session.add(AgentEventDB(task_id=task.id, event_type=event_type, data=data or {}))
        await session.flush()

    task.status = TaskStatus.running.value
    task.started_at = datetime.now(timezone.utc)
    await emit("started")

    try:
        agent = _registry[agent_type]()
        ctx = AgentContext(task_id=task.id, patient_id=patient_id, input_data=task.input_data, emit=emit)
        result = await agent.execute(ctx)
    except Exception as e:
        task.status = TaskStatus.failed.value
        task.error = f"{type(e).__name__}: {e}"
        task.completed_at = datetime.now(timezone.utc)
        await emit("failed", {"error": task.error})
        logger.error("task.failed", task_id=str(task.id), agent_type=agent_type, error=task.error)
        return task

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

    return task
