import asyncio
import json
import os
from typing import Dict, Optional

import anthropic

from models import PatientProfile, TrialMatch, CriterionEvaluation
from prompts import ELIGIBILITY_ANALYSIS_PROMPT, PATIENT_SUMMARY_PROMPT
from trials_client import search_trials, find_nearest_site

MAX_CONCURRENT_ANALYSES = 1
MODEL = "claude-sonnet-4-20250514"


def _get_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


async def _analyze_trial(patient: PatientProfile, trial: Dict) -> Optional[Dict]:
    """Use Claude to analyze a single trial's eligibility criteria against the patient."""
    prompt = ELIGIBILITY_ANALYSIS_PROMPT.format(
        cancer_type=patient.cancer_type,
        cancer_stage=patient.cancer_stage,
        biomarkers=", ".join(patient.biomarkers) or "None reported",
        prior_treatments=", ".join(patient.prior_treatments) or "None",
        lines_of_therapy=patient.lines_of_therapy,
        age=patient.age,
        sex=patient.sex,
        ecog_score=patient.ecog_score if patient.ecog_score is not None else "Not reported",
        key_labs=json.dumps(patient.key_labs) if patient.key_labs else "Not reported",
        additional_conditions=", ".join(patient.additional_conditions) or "None reported",
        additional_notes=patient.additional_notes or "None",
        nct_id=trial["nct_id"],
        brief_title=trial["brief_title"],
        phase=trial["phase"],
        brief_summary=trial["brief_summary"],
        eligibility_criteria=trial["eligibility_criteria"],
    )

    try:
        response = await _get_client().messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        return json.loads(text)
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"[MATCH] Failed to parse Claude response for {trial['nct_id']}: {e}")
        return None
    except Exception as e:
        print(f"[MATCH] Error analyzing {trial['nct_id']}: {type(e).__name__}: {e}")
        return None


async def _generate_patient_summary(patient: PatientProfile) -> str:
    """Generate a brief empathetic summary of the patient's profile."""
    prompt = PATIENT_SUMMARY_PROMPT.format(
        cancer_type=patient.cancer_type,
        cancer_stage=patient.cancer_stage,
        biomarkers=", ".join(patient.biomarkers) or "None reported",
        prior_treatments=", ".join(patient.prior_treatments) or "None",
        lines_of_therapy=patient.lines_of_therapy,
        age=patient.age,
        sex=patient.sex,
        ecog_score=patient.ecog_score if patient.ecog_score is not None else "Not reported",
    )

    try:
        response = await _get_client().messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[MATCH] Patient summary error: {type(e).__name__}: {e}")
        return f"{patient.age}-year-old {patient.sex} with {patient.cancer_stage} {patient.cancer_type}."


async def match_trials(patient: PatientProfile, max_results: int = 10) -> Dict:
    """Full matching pipeline: search -> analyze -> rank -> return."""

    # Step 1: Search ClinicalTrials.gov
    trials = await search_trials(
        cancer_type=patient.cancer_type,
        age=patient.age,
        sex=patient.sex,
    )

    # Step 2: Analyze each trial with Claude (with concurrency limit)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)

    async def analyze_with_limit(trial):
        async with semaphore:
            return trial, await _analyze_trial(patient, trial)

    # Run patient summary generation concurrently with trial analyses
    summary_task = asyncio.create_task(_generate_patient_summary(patient))
    analysis_tasks = [analyze_with_limit(trial) for trial in trials]
    results = await asyncio.gather(*analysis_tasks)

    # Step 3: Build TrialMatch objects and rank
    matches = []
    for trial, analysis in results:
        if analysis is None:
            continue

        nearest_site, distance = find_nearest_site(
            trial.get("locations", []), patient.location_zip
        )

        # Skip trials beyond travel distance (if we have distance info)
        if distance is not None and distance > patient.willing_to_travel_miles:
            continue

        matches.append(
            TrialMatch(
                nct_id=trial["nct_id"],
                brief_title=trial["brief_title"],
                phase=trial["phase"],
                overall_status=trial["overall_status"],
                conditions=trial["conditions"],
                brief_summary=trial["brief_summary"],
                eligibility_criteria=trial["eligibility_criteria"],
                match_score=analysis.get("match_score", 0),
                match_explanation=analysis.get("match_explanation", ""),
                inclusion_evaluations=[
                    CriterionEvaluation(**e)
                    for e in analysis.get("inclusion_evaluations", [])
                ],
                exclusion_evaluations=[
                    CriterionEvaluation(**e)
                    for e in analysis.get("exclusion_evaluations", [])
                ],
                flags_for_oncologist=analysis.get("flags_for_oncologist", []),
                nearest_site=nearest_site,
                distance_miles=distance,
                interventions=trial.get("interventions", []),
            )
        )

    # Sort by match score descending
    matches.sort(key=lambda m: m.match_score, reverse=True)
    matches = matches[:max_results]

    patient_summary = await summary_task

    return {
        "patient_summary": patient_summary,
        "matches": matches,
        "total_trials_screened": len(trials),
    }
