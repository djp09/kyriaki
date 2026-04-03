"""Tool: Programmatic match scoring from criterion-level evaluations.

Aggregates individual criterion evaluations into a final match score
and tier. This is pure Python — no LLM in the scoring loop.

The score formula produces differentiated results because it reflects
how many criteria are confirmed vs. unknown vs. failed, which varies
naturally across trials for a given patient.
"""

from __future__ import annotations

from logging_config import get_logger
from tools import ToolResult, ToolSpec, register_tool

logger = get_logger("kyriaki.tools.scoring")


def calculate_match_score(evaluations: list[dict], flags: list[str] | None = None) -> dict:
    """Calculate match score from criterion-level evaluations.

    Args:
        evaluations: List of criterion evaluation dicts with keys:
            criterion_id, type (inclusion/exclusion), status, confidence
        flags: Optional flags_for_oncologist from the LLM

    Returns:
        Dict with score, tier, criteria counts, explanation, details.
    """
    inclusion = [e for e in evaluations if e.get("type") == "inclusion"]
    exclusion = [e for e in evaluations if e.get("type") == "exclusion"]

    # --- Hard disqualifiers: any exclusion criterion triggered = score 0 ---
    hard_exclusions = [e for e in exclusion if e.get("status") == "TRIGGERED"]
    if hard_exclusions:
        triggered = hard_exclusions[0]
        return {
            "score": 0.0,
            "tier": "EXCLUDED",
            "match_explanation": (
                f"This trial is not a match because an exclusion criterion applies: "
                f"{triggered.get('criterion_text', 'Unknown criterion')}. "
                f"{triggered.get('reasoning', '')}"
            ),
            "criteria_met": 0,
            "criteria_not_met": 0,
            "criteria_unknown": 0,
            "criteria_total": len(inclusion),
            "exclusions_clear": len([e for e in exclusion if e.get("status") == "NOT_TRIGGERED"]),
            "exclusions_triggered": len(hard_exclusions),
            "exclusions_unknown": len([e for e in exclusion if e.get("status") == "INSUFFICIENT_INFO"]),
            "flags_for_oncologist": flags or [],
        }

    # --- Hard NOT_MET on critical inclusion criteria ---
    not_met_critical = [
        e
        for e in inclusion
        if e.get("status") == "NOT_MET"
        and e.get("confidence") == "HIGH"
        and e.get("category", "") in ("diagnosis", "biomarker", "stage", "demographic")
    ]
    if not_met_critical:
        failed = not_met_critical[0]
        return {
            "score": 5.0,
            "tier": "EXCLUDED",
            "match_explanation": (
                f"This trial requires a criterion you do not meet: "
                f"{failed.get('criterion_text', 'Unknown criterion')}. "
                f"{failed.get('reasoning', '')}"
            ),
            "criteria_met": len([e for e in inclusion if e.get("status") == "MET"]),
            "criteria_not_met": len([e for e in inclusion if e.get("status") == "NOT_MET"]),
            "criteria_unknown": len([e for e in inclusion if e.get("status") == "INSUFFICIENT_INFO"]),
            "criteria_total": len(inclusion),
            "exclusions_clear": len([e for e in exclusion if e.get("status") == "NOT_TRIGGERED"]),
            "exclusions_triggered": 0,
            "exclusions_unknown": len([e for e in exclusion if e.get("status") == "INSUFFICIENT_INFO"]),
            "flags_for_oncologist": flags or [],
        }

    # --- Score inclusion criteria ---
    met = len([e for e in inclusion if e.get("status") == "MET"])
    not_met = len([e for e in inclusion if e.get("status") == "NOT_MET"])
    unknown = len([e for e in inclusion if e.get("status") == "INSUFFICIENT_INFO"])
    total = len(inclusion)

    # Met criteria count fully, unknown count partially (0.3 weight)
    base_score = 50.0 if total == 0 else ((met * 1.0 + unknown * 0.3) / total) * 100

    # --- Confidence adjustment ---
    # High-confidence MET criteria are worth more
    high_confidence_met = len([e for e in inclusion if e.get("status") == "MET" and e.get("confidence") == "HIGH"])
    confidence_bonus = (high_confidence_met / max(total, 1)) * 10

    # --- NOT_MET penalty ---
    # Each NOT_MET drags the score down
    not_met_penalty = not_met * 8

    # --- Exclusion safety margin ---
    # Unknown exclusions are risky — penalize
    unknown_exclusions = len([e for e in exclusion if e.get("status") == "INSUFFICIENT_INFO"])
    exclusion_penalty = unknown_exclusions * 3

    final_score = min(100.0, max(0.0, base_score + confidence_bonus - not_met_penalty - exclusion_penalty))

    # --- Tier assignment ---
    if final_score >= 75 and not_met == 0:
        tier = "STRONG_MATCH"
    elif final_score >= 50:
        tier = "POTENTIAL_MATCH"
    elif final_score >= 25:
        tier = "PARTIAL_MATCH"
    else:
        tier = "UNLIKELY_MATCH"

    # --- Generate explanation ---
    explanation = _generate_explanation(tier, met, not_met, unknown, total, exclusion, final_score)

    return {
        "score": round(final_score, 1),
        "tier": tier,
        "match_explanation": explanation,
        "criteria_met": met,
        "criteria_not_met": not_met,
        "criteria_unknown": unknown,
        "criteria_total": total,
        "exclusions_clear": len([e for e in exclusion if e.get("status") == "NOT_TRIGGERED"]),
        "exclusions_triggered": 0,
        "exclusions_unknown": unknown_exclusions,
        "flags_for_oncologist": flags or [],
    }


def _generate_explanation(
    tier: str,
    met: int,
    not_met: int,
    unknown: int,
    total: int,
    exclusion: list[dict],
    score: float,
) -> str:
    """Generate a patient-friendly explanation of the match score."""
    if tier == "STRONG_MATCH":
        msg = (
            f"This trial appears to be a strong fit for you. "
            f"You meet {met} of {total} inclusion criteria we could evaluate"
        )
        if unknown > 0:
            msg += f", with {unknown} item(s) your oncologist can help confirm"
        msg += "."
    elif tier == "POTENTIAL_MATCH":
        msg = (
            f"This trial could be a good option. You meet {met} of {total} criteria, "
            f"but {unknown} item(s) need more information from your medical team."
        )
    elif tier == "PARTIAL_MATCH":
        msg = f"This trial is a partial match. You meet {met} of {total} criteria"
        if not_met > 0:
            msg += f", but {not_met} criteria may not be met"
        if unknown > 0:
            msg += f" and {unknown} need verification"
        msg += ". Discuss with your oncologist to see if it could still work."
    else:
        msg = (
            f"This trial is unlikely to be a match based on available information. "
            f"Only {met} of {total} criteria are met"
        )
        if not_met > 0:
            msg += f", with {not_met} not met"
        msg += "."

    unknown_exc = len([e for e in exclusion if e.get("status") == "INSUFFICIENT_INFO"])
    if unknown_exc > 0:
        msg += f" Note: {unknown_exc} exclusion criteria could not be fully evaluated — your oncologist should review these."

    return msg


def score_trial(evaluations: list[dict], flags: list[str] | None = None) -> ToolResult:
    """Score a trial match from criterion evaluations. Returns ToolResult."""
    try:
        result = calculate_match_score(evaluations, flags)
        return ToolResult(success=True, data=result)
    except Exception as e:
        return ToolResult(success=False, error=f"Scoring failed: {e}")


# --- Register tool ---

register_tool(
    "score_trial",
    score_trial,
    ToolSpec(
        name="score_trial",
        description="Calculate match score from criterion-level evaluations. Pure Python, no LLM.",
        parameters={
            "evaluations": "List of criterion evaluation dicts with type, status, confidence",
            "flags": "Optional flags_for_oncologist from the LLM",
        },
        returns="Dict with score (0-100), tier, criteria counts, explanation",
        edge_cases=[
            "Any exclusion TRIGGERED = score 0, tier EXCLUDED",
            "Critical inclusion NOT_MET with HIGH confidence = score 5, tier EXCLUDED",
            "Unknown criteria count at 0.3 weight (not penalized like NOT_MET)",
        ],
    ),
)
