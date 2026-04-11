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


def calculate_match_score(
    evaluations: list[dict],
    flags: list[str] | None = None,
    *,
    biomarker_aligned: bool = True,
    intervention_types: set[str] | None = None,
    has_actionable_genes: bool = False,
) -> dict:
    """Calculate match score from criterion-level evaluations.

    Args:
        evaluations: List of criterion evaluation dicts with keys:
            criterion_id, type (inclusion/exclusion), status, confidence
        flags: Optional flags_for_oncologist from the LLM
        biomarker_aligned: True if trial targets the patient's actionable
            biomarkers (or patient has none). Drives the −30 penalty.
        intervention_types: Set of category strings from trial_classifier.
            Used to detect radiation-only mismatches and combo trials.
        has_actionable_genes: True if patient has ≥1 actionable biomarker.
            Required to trigger biomarker penalties.

    Returns:
        Dict with score, tier, criteria counts, explanation, details.
    """
    from tools.trial_classifier import is_radiation_or_observational_only

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
    # Only hard-exclude if a critical category has NOT_MET but NO MET criteria.
    # Multi-cohort trials (common in oncology) have criteria for different cohorts —
    # a patient may fail one cohort's criterion while meeting another's.
    CRITICAL_CATEGORIES = {"diagnosis", "biomarker", "stage", "demographic"}
    not_met_critical = [
        e
        for e in inclusion
        if e.get("status") == "NOT_MET"
        and e.get("confidence") == "HIGH"
        and e.get("category", "") in CRITICAL_CATEGORIES
    ]
    if not_met_critical:
        # Check if any critical category criterion is also MET — if so, the patient
        # may qualify under a different cohort, so don't hard-exclude
        met_critical_categories = {
            e.get("category")
            for e in inclusion
            if e.get("status") == "MET" and e.get("category", "") in CRITICAL_CATEGORIES
        }
        not_met_categories = {e.get("category") for e in not_met_critical}
        # Only hard-exclude if a NOT_MET category has zero MET criteria
        unmet_categories = not_met_categories - met_critical_categories
        if unmet_categories:
            failed_criteria = [e for e in not_met_critical if e.get("category") in unmet_categories]
            failed = failed_criteria[0]
            met_count = len([e for e in inclusion if e.get("status") == "MET"])
            total_inc = len(inclusion)
            explanation = (
                f"This trial is unlikely to be a match. You meet {met_count} of "
                f"{total_inc} inclusion criteria, but a key requirement is not met: "
                f"{failed.get('criterion_text', 'Unknown criterion')}. "
                f"{failed.get('reasoning', '')}"
            )
            if len(failed_criteria) > 1:
                others = [e.get("criterion_text", "?") for e in failed_criteria[1:]]
                explanation += f" Additionally not met: {'; '.join(others)}."
            return {
                "score": 5.0,
                "tier": "EXCLUDED",
                "match_explanation": explanation,
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

    # Score based on DEFINITIVE answers only (Session 4 fix). Previously used
    # `(met + unknown * 0.15) / total`, but that drags the score down whenever
    # Claude evaluates more criteria — even if the patient is unchanged. The
    # old prompt was being output-truncated at 2500 tokens, so it only ever
    # returned the first 8-10 criteria. After compacting the output schema we
    # get full evaluations, including labs/washout criteria that default to
    # INSUFFICIENT_INFO; under the old formula those new unknowns inflated
    # the denominator and tanked the score.
    #
    # New formula: score = met / (met + not_met), then linearly dampened by
    # how confidently we know the answers (definitive / total). A 5-met trial
    # with 0 unknowns scores higher than a 5-met trial with 20 unknowns —
    # both have the same met ratio but different evidence depth. Unknown
    # criteria don't drag the raw score; they only reduce confidence. If
    # everything is unknown, fall back to a neutral 30.
    definitive = met + not_met
    if definitive == 0:
        base_score = 30.0
    else:
        raw = (met / definitive) * 100
        confidence_factor = definitive / max(total, 1)
        base_score = raw * confidence_factor + 30.0 * (1 - confidence_factor)

    # --- Confidence adjustment ---
    # High-confidence MET criteria are worth more
    high_confidence_met = len([e for e in inclusion if e.get("status") == "MET" and e.get("confidence") == "HIGH"])
    confidence_bonus = (high_confidence_met / max(total, 1)) * 10

    # --- NOT_MET penalty ---
    # Each NOT_MET drags the score down. Cap raised from 24 → 40 so trials
    # with multiple failed criteria can no longer hide in the 60s.
    not_met_penalty = min(not_met * 10, 40)

    # --- Exclusion safety margin ---
    # Unknown exclusions are risky — penalize, but cap at 15 to avoid
    # crushing scores when patient data is incomplete (common for intake forms)
    unknown_exclusions = len([e for e in exclusion if e.get("status") == "INSUFFICIENT_INFO"])
    exclusion_penalty = min(unknown_exclusions * 3, 15)

    # --- Biomarker–therapy alignment penalties ---
    # Layer 2 of defense-in-depth: even after the pre-filter, apply scoring
    # penalties so any trial that slipped through gets demoted.
    biomarker_mismatch_penalty = 30 if (has_actionable_genes and not biomarker_aligned) else 0

    # Combination trials (e.g., osimertinib + radiation) are technically aligned
    # but carry slight risk for biomarker-driven patients — soft −15 penalty.
    combo_radiation_penalty = 0
    if (
        has_actionable_genes
        and intervention_types
        and "radiation" in intervention_types
        and (intervention_types & {"targeted", "chemo", "immunotherapy"})
    ):
        combo_radiation_penalty = 15

    final_score = min(
        100.0,
        max(
            0.0,
            base_score
            + confidence_bonus
            - not_met_penalty
            - exclusion_penalty
            - biomarker_mismatch_penalty
            - combo_radiation_penalty,
        ),
    )

    # --- Layer 3: hard cap for radiation-only mismatches ---
    # Even if the LLM scores a radiation trial well for an EGFR+ patient,
    # cap it at 40 so it never appears in STRONG/POTENTIAL match tiers.
    if (
        has_actionable_genes
        and intervention_types
        and is_radiation_or_observational_only(intervention_types)
        and not biomarker_aligned
    ):
        final_score = min(final_score, 40.0)

    # --- Tier assignment ---
    # STRONG_MATCH now requires biomarker alignment.
    if final_score >= 75 and not_met == 0 and biomarker_aligned:
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
    unknown_exc = len([e for e in exclusion if e.get("status") == "INSUFFICIENT_INFO"])

    if tier == "STRONG_MATCH":
        msg = (
            f"This trial appears to be a strong fit for you. "
            f"You meet {met} of {total} inclusion criteria we could evaluate"
        )
        if unknown > 0:
            msg += f", with {unknown} that your oncologist can help confirm"
        msg += "."
    elif tier == "POTENTIAL_MATCH":
        msg = (
            f"This trial could be a good option. You meet {met} of {total} inclusion criteria, "
            f"but {unknown} need more information from your medical team."
        )
    elif tier == "PARTIAL_MATCH":
        msg = f"This trial is a partial match. You meet {met} of {total} inclusion criteria"
        if not_met > 0:
            msg += f", {not_met} may not be met"
        if unknown > 0:
            msg += f", and {unknown} need verification"
        msg += ". Discuss with your oncologist to see if it could still work."
    else:
        msg = (
            f"This trial is unlikely to be a match based on available information. "
            f"You meet {met} of {total} inclusion criteria"
        )
        if not_met > 0:
            msg += f", with {not_met} not met"
        msg += "."

    if unknown_exc > 0:
        msg += f" Additionally, {unknown_exc} exclusion criteria could not be fully evaluated — your oncologist should review these."

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
