"""Matching engine — backward-compatibility shim.

All core logic has moved to tools/:
  - Claude API: tools/claude_api.py
  - Data formatting: tools/data_formatter.py
  - Prompt rendering: tools/prompt_renderer.py

This module re-exports under the original names so existing imports
(from agents.py, main.py, tests) continue to work.

The match_trials() orchestration function remains here temporarily
and will move into MatchingAgent in Phase 3.
"""

from __future__ import annotations

import asyncio

from config import get_settings
from logging_config import get_logger
from models import PatientProfile, TrialMatch
from tools.claude_api import extract_minimal_result as _extract_minimal_result
from tools.claude_api import get_claude_client as _get_client
from tools.claude_api import paced_claude_call as _paced_claude_call
from tools.claude_api import parse_json_response as _parse_json_response
from tools.claude_api import repair_truncated_json as _repair_truncated_json  # noqa: F401
from tools.data_formatter import (
    build_scored_match,
    format_patient_for_prompt,
)
from tools.data_formatter import (
    build_unscored_match as _build_unscored_match,
)
from tools.prompt_renderer import render_prompt
from trials_client import biomarker_search_terms, search_trials

logger = get_logger("kyriaki.matching")


async def _analyze_trial(
    patient: PatientProfile, trial: dict, trial_index: int = 0, total_trials: int = 0
) -> dict | None:
    settings = get_settings()
    label = f"{trial_index}/{total_trials}" if total_trials else ""
    nct_id = trial["nct_id"]
    logger.info("trial.analyze_start", nct_id=nct_id, label=label, title=trial["brief_title"][:60])

    from tools.criteria_parser import parse_eligibility_criteria
    from tools.scoring import calculate_match_score

    eligibility_text = trial["eligibility_criteria"]
    if len(eligibility_text) > 6000:
        eligibility_text = eligibility_text[:6000] + "\n\n[Eligibility text truncated]"

    # Step 1: Parse criteria
    parse_result = parse_eligibility_criteria(eligibility_text)
    if not parse_result.success or parse_result.data["total_criteria"] == 0:
        return None

    parsed = parse_result.data
    criteria_lines = []
    for c in parsed["inclusion_criteria"]:
        criteria_lines.append(f"[{c['id']}] INCLUSION ({c['category']}): {c['text']}")
    for c in parsed["exclusion_criteria"]:
        criteria_lines.append(f"[{c['id']}] EXCLUSION ({c['category']}): {c['text']}")

    # Step 2: Evaluate with Claude
    patient_vars = format_patient_for_prompt(patient)
    prompt_result = render_prompt(
        prompt_name="eligibility_analysis",
        **patient_vars,
        nct_id=nct_id,
        brief_title=trial["brief_title"],
        phase=trial["phase"],
        brief_summary=trial["brief_summary"],
        parsed_criteria="\n".join(criteria_lines),
        enriched_context="",
    )
    if not prompt_result.success:
        logger.error("trial.prompt_render_failed", nct_id=nct_id, error=prompt_result.error)
        return None

    for attempt in range(settings.max_retries + 1):
        try:
            response = await _paced_claude_call(
                _get_client(),
                model=settings.claude_model,
                max_tokens=2500,
                messages=[{"role": "user", "content": prompt_result.data}],
            )
            text = response.content[0].text.strip()
            result = _parse_json_response(text)

            if result is not None and result.get("criterion_evaluations"):
                # Step 3: Score programmatically
                evals = result["criterion_evaluations"]
                flags = result.get("flags_for_oncologist", [])
                score = calculate_match_score(evals, flags)
                logger.info("trial.analyze_complete", nct_id=nct_id, score=score["score"], tier=score["tier"])
                return {
                    "match_score": score["score"],
                    "match_tier": score["tier"],
                    "match_explanation": score["match_explanation"],
                    "inclusion_evaluations": [e for e in evals if e.get("type") == "inclusion"],
                    "exclusion_evaluations": [e for e in evals if e.get("type") == "exclusion"],
                    "flags_for_oncologist": flags,
                    "criteria_met": score["criteria_met"],
                    "criteria_not_met": score["criteria_not_met"],
                    "criteria_unknown": score["criteria_unknown"],
                    "criteria_total": score["criteria_total"],
                }

            if attempt < settings.max_retries:
                logger.warning("trial.parse_failed", nct_id=nct_id, attempt=attempt + 1)
                continue

            logger.error("trial.parse_exhausted", nct_id=nct_id, attempts=settings.max_retries + 1)
            return _extract_minimal_result(text, nct_id)

        except Exception as e:
            if attempt < settings.max_retries:
                logger.warning("trial.analyze_error", nct_id=nct_id, error=str(e), attempt=attempt + 1)
                continue
            logger.error("trial.analyze_failed", nct_id=nct_id, error=str(e))
            return None

    return None


async def _generate_patient_summary(patient: PatientProfile) -> str:
    settings = get_settings()
    patient_vars = format_patient_for_prompt(patient)
    prompt_result = render_prompt(prompt_name="patient_summary", **patient_vars)
    if not prompt_result.success:
        logger.warning("patient_summary.prompt_failed", error=prompt_result.error)
        return _fallback_summary(patient)

    try:
        response = await _paced_claude_call(
            _get_client(),
            model=settings.claude_model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt_result.data}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning("patient_summary.fallback", error=str(e))
        return _fallback_summary(patient)


def _fallback_summary(patient: PatientProfile) -> str:
    treatments_str = ", ".join(patient.prior_treatments) if patient.prior_treatments else None
    biomarkers_str = ", ".join(patient.biomarkers) if patient.biomarkers else None

    summary = f"You are a {patient.age}-year-old navigating {patient.cancer_stage} {patient.cancer_type}."
    if treatments_str:
        summary += f" You have been through {patient.lines_of_therapy} line(s) of treatment including {treatments_str}."
    if biomarkers_str:
        summary += f" Your biomarker profile includes {biomarkers_str}."
    summary += " We are searching for clinical trials that may be a good fit for your specific situation."
    return summary


async def match_trials(patient: PatientProfile, max_results: int = 10) -> dict:
    settings = get_settings()

    candidate_count = min(max(max_results * 2, 6), settings.default_page_size)
    query_intr, query_term = biomarker_search_terms(patient.biomarkers or [])
    trials = await search_trials(
        cancer_type=patient.cancer_type,
        age=patient.age,
        sex=patient.sex,
        page_size=candidate_count,
        query_intr=query_intr,
        query_term=query_term,
    )

    total = len(trials)
    logger.info("match.search_complete", candidate_trials=total)

    # Concurrency is managed by AdaptiveConcurrencyLimiter in paced_claude_call

    async def analyze_with_limit(trial: dict, index: int):
        return trial, await _analyze_trial(patient, trial, index, total)

    summary_task = asyncio.create_task(_generate_patient_summary(patient))
    analysis_tasks = [analyze_with_limit(trial, i + 1) for i, trial in enumerate(trials)]
    results = await asyncio.gather(*analysis_tasks)

    matches: list[TrialMatch] = []
    all_analyses_failed = all(analysis is None for _, analysis in results)

    if all_analyses_failed and trials:
        logger.warning("match.all_analyses_failed", fallback="unscored")
        for trial, _ in results:
            match = _build_unscored_match(trial, patient)
            if match.distance_miles is None or match.distance_miles <= patient.willing_to_travel_miles:
                matches.append(match)
    else:
        for trial, analysis in results:
            if analysis is None:
                continue
            match = build_scored_match(trial, analysis, patient)
            if match is not None:
                matches.append(match)

    matches.sort(key=lambda m: m.match_score, reverse=True)
    matches = matches[:max_results]

    patient_summary = await summary_task

    logger.info("match.complete", total_screened=total, matches_returned=len(matches))

    return {
        "patient_summary": patient_summary,
        "matches": matches,
        "total_trials_screened": total,
    }
