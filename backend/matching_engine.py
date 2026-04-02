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
import json

from config import get_settings
from logging_config import get_logger
from models import PatientProfile, TrialMatch
from tools.claude_api import (
    call_claude_with_retry as _call_claude_with_retry,
    extract_minimal_result as _extract_minimal_result,
    get_claude_client as _get_client,
    paced_claude_call as _paced_claude_call,
    parse_json_response as _parse_json_response,
    repair_truncated_json as _repair_truncated_json,
)
from tools.data_formatter import (
    build_scored_match,
    build_unscored_match as _build_unscored_match,
    format_patient_for_prompt,
)
from tools.prompt_renderer import render_prompt
from tools.trial_search import search_trials_tool
from trials_client import find_nearest_site, search_trials

logger = get_logger("kyriaki.matching")


async def _analyze_trial(
    patient: PatientProfile, trial: dict, trial_index: int = 0, total_trials: int = 0
) -> dict | None:
    settings = get_settings()
    label = f"{trial_index}/{total_trials}" if total_trials else ""
    nct_id = trial["nct_id"]
    logger.info("trial.analyze_start", nct_id=nct_id, label=label, title=trial["brief_title"][:60])

    eligibility_text = trial["eligibility_criteria"]
    if len(eligibility_text) > 6000:
        eligibility_text = eligibility_text[:6000] + "\n\n[Eligibility text truncated — focus on the criteria above]"

    patient_vars = format_patient_for_prompt(patient)
    prompt_result = render_prompt(
        prompt_name="eligibility_analysis",
        **patient_vars,
        nct_id=nct_id,
        brief_title=trial["brief_title"],
        phase=trial["phase"],
        brief_summary=trial["brief_summary"],
        eligibility_criteria=eligibility_text,
    )
    if not prompt_result.success:
        logger.error("trial.prompt_render_failed", nct_id=nct_id, error=prompt_result.error)
        return None

    prompt = prompt_result.data

    for attempt in range(settings.max_retries + 1):
        try:
            response = await _paced_claude_call(
                _get_client(),
                model=settings.claude_model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            result = _parse_json_response(text)

            if result is not None:
                if "match_score" not in result:
                    result["match_score"] = 0
                logger.info("trial.analyze_complete", nct_id=nct_id, score=result["match_score"])
                return result

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
        summary += (
            f" You have been through {patient.lines_of_therapy} line(s) of treatment including {treatments_str}."
        )
    if biomarkers_str:
        summary += f" Your biomarker profile includes {biomarkers_str}."
    summary += " We are searching for clinical trials that may be a good fit for your specific situation."
    return summary


async def match_trials(patient: PatientProfile, max_results: int = 10) -> dict:
    settings = get_settings()

    candidate_count = min(max(max_results * 2, 6), settings.default_page_size)
    trials = await search_trials(
        cancer_type=patient.cancer_type,
        age=patient.age,
        sex=patient.sex,
        page_size=candidate_count,
    )

    total = len(trials)
    logger.info("match.search_complete", candidate_trials=total)

    semaphore = asyncio.Semaphore(settings.max_concurrent_analyses)

    async def analyze_with_limit(trial: dict, index: int):
        async with semaphore:
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
