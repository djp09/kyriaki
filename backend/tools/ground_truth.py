"""Tool: Ground truth feedback — outcome recording and accuracy stats.

Records real-world outcomes for patient-trial pairings and computes
accuracy statistics to identify systematic scoring biases.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db_models import TrialOutcomeDB
from logging_config import get_logger
from tools import ToolResult, register_tool

logger = get_logger("kyriaki.tools.ground_truth")


async def upsert_outcome(
    session: AsyncSession,
    *,
    patient_id: uuid.UUID,
    nct_id: str,
    match_score: int | None = None,
    revised_score: int | None = None,
    navigator_decision: str | None = None,
    site_response: str | None = None,
    screening_result: str | None = None,
    outcome_notes: str | None = None,
) -> ToolResult:
    """Create or update an outcome record for a patient-trial pairing."""
    # Check for existing outcome
    stmt = select(TrialOutcomeDB).where(
        TrialOutcomeDB.patient_id == patient_id,
        TrialOutcomeDB.nct_id == nct_id,
    )
    result = await session.execute(stmt)
    outcome = result.scalars().first()

    if outcome:
        # Update only non-None fields
        if match_score is not None:
            outcome.match_score = match_score
        if revised_score is not None:
            outcome.revised_score = revised_score
        if navigator_decision is not None:
            outcome.navigator_decision = navigator_decision
        if site_response is not None:
            outcome.site_response = site_response
        if screening_result is not None:
            outcome.screening_result = screening_result
        if outcome_notes is not None:
            outcome.outcome_notes = outcome_notes
        logger.info("outcome.updated", patient_id=str(patient_id), nct_id=nct_id)
    else:
        outcome = TrialOutcomeDB(
            patient_id=patient_id,
            nct_id=nct_id,
            match_score=match_score,
            revised_score=revised_score,
            navigator_decision=navigator_decision,
            site_response=site_response,
            screening_result=screening_result,
            outcome_notes=outcome_notes,
        )
        session.add(outcome)
        logger.info("outcome.created", patient_id=str(patient_id), nct_id=nct_id)

    await session.flush()
    return ToolResult(success=True, data={"outcome_id": str(outcome.id)})


async def get_outcomes_for_patient(session: AsyncSession, patient_id: uuid.UUID) -> ToolResult:
    """Get all outcomes for a patient."""
    stmt = (
        select(TrialOutcomeDB).where(TrialOutcomeDB.patient_id == patient_id).order_by(TrialOutcomeDB.created_at.desc())
    )
    result = await session.execute(stmt)
    outcomes = result.scalars().all()

    return ToolResult(
        success=True,
        data=[
            {
                "patient_id": str(o.patient_id),
                "nct_id": o.nct_id,
                "match_score": o.match_score,
                "revised_score": o.revised_score,
                "navigator_decision": o.navigator_decision,
                "site_response": o.site_response,
                "screening_result": o.screening_result,
                "outcome_notes": o.outcome_notes,
                "created_at": o.created_at.isoformat() if o.created_at else "",
                "updated_at": o.updated_at.isoformat() if o.updated_at else "",
            }
            for o in outcomes
        ],
    )


async def compute_outcome_stats(session: AsyncSession) -> ToolResult:
    """Compute accuracy statistics across all outcomes.

    Returns score distributions by navigator decision and screening result
    to identify systematic scoring biases.
    """
    stmt = select(TrialOutcomeDB)
    result = await session.execute(stmt)
    outcomes = list(result.scalars().all())

    if not outcomes:
        return ToolResult(
            success=True,
            data={
                "total_outcomes": 0,
                "by_navigator_decision": {},
                "by_screening_result": {},
                "avg_score_by_decision": {},
                "avg_score_by_screening": {},
                "score_accuracy": {},
            },
        )

    # Count by decision/result
    by_decision: dict[str, int] = defaultdict(int)
    by_screening: dict[str, int] = defaultdict(int)
    scores_by_decision: dict[str, list[int]] = defaultdict(list)
    scores_by_screening: dict[str, list[int]] = defaultdict(list)

    for o in outcomes:
        # Use revised_score if available, else match_score
        score = o.revised_score if o.revised_score is not None else o.match_score

        if o.navigator_decision:
            by_decision[o.navigator_decision] += 1
            if score is not None:
                scores_by_decision[o.navigator_decision].append(score)

        if o.screening_result:
            by_screening[o.screening_result] += 1
            if score is not None:
                scores_by_screening[o.screening_result].append(score)

    def _avg(scores: list[int]) -> float:
        return round(sum(scores) / len(scores), 1) if scores else 0.0

    avg_by_decision = {k: _avg(v) for k, v in scores_by_decision.items()}
    avg_by_screening = {k: _avg(v) for k, v in scores_by_screening.items()}

    # Score accuracy: what % of high-score (>=65) matches were actually eligible?
    high_score_outcomes = [
        o for o in outcomes if (o.revised_score or o.match_score or 0) >= 65 and o.screening_result is not None
    ]
    low_score_outcomes = [
        o for o in outcomes if (o.revised_score or o.match_score or 0) < 40 and o.screening_result is not None
    ]

    score_accuracy = {}
    if high_score_outcomes:
        eligible_count = sum(1 for o in high_score_outcomes if o.screening_result == "eligible")
        score_accuracy["high_score_eligible_pct"] = round(eligible_count / len(high_score_outcomes), 3)
        score_accuracy["high_score_total"] = len(high_score_outcomes)

    if low_score_outcomes:
        ineligible_count = sum(1 for o in low_score_outcomes if o.screening_result == "ineligible")
        score_accuracy["low_score_ineligible_pct"] = round(ineligible_count / len(low_score_outcomes), 3)
        score_accuracy["low_score_total"] = len(low_score_outcomes)

    return ToolResult(
        success=True,
        data={
            "total_outcomes": len(outcomes),
            "by_navigator_decision": dict(by_decision),
            "by_screening_result": dict(by_screening),
            "avg_score_by_decision": avg_by_decision,
            "avg_score_by_screening": avg_by_screening,
            "score_accuracy": score_accuracy,
        },
    )


# --- Register tools ---

register_tool("upsert_outcome", upsert_outcome)
register_tool("get_outcomes_for_patient", get_outcomes_for_patient)
register_tool("compute_outcome_stats", compute_outcome_stats)
