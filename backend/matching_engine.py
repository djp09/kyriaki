import asyncio
import json
import os
import re
from typing import Dict, Optional

import anthropic

from models import PatientProfile, TrialMatch, CriterionEvaluation
from prompts import ELIGIBILITY_ANALYSIS_PROMPT, PATIENT_SUMMARY_PROMPT
from trials_client import search_trials, find_nearest_site

MAX_CONCURRENT_ANALYSES = 1
MODEL = "claude-sonnet-4-20250514"
MAX_RETRIES = 1


def _get_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def _parse_json_response(text: str) -> Optional[Dict]:
    """Parse a JSON response from Claude, handling common issues.

    Handles:
    - Clean JSON
    - JSON wrapped in markdown code fences (```json ... ```)
    - Truncated JSON (attempts to close open braces/brackets)
    - Leading/trailing whitespace or text
    """
    if not text:
        return None

    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        text = re.sub(r"^```\w*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    # Try parsing as-is first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON object from surrounding text
    # Find the first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace : last_brace + 1])
        except json.JSONDecodeError:
            pass

    # Attempt to fix truncated JSON
    if first_brace != -1:
        partial = text[first_brace:]
        repaired = _repair_truncated_json(partial)
        if repaired is not None:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    return None


def _repair_truncated_json(text: str) -> Optional[str]:
    """Try to repair truncated JSON by closing open structures.

    This handles the common case where the model hits max_tokens and the
    response is cut off mid-JSON. We attempt to:
    1. Remove any trailing partial string/value
    2. Close open arrays and objects in the right order
    """
    # Track what's open
    stack = []
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()

    if not stack:
        return text

    # Work with the full text — trim trailing partial content
    truncated = text

    # If we ended inside a string, close it
    if in_string:
        truncated += '"'

    # Remove trailing partial content after the last complete element
    truncated = re.sub(r',\s*"[^"]*$', "", truncated)  # trailing partial key
    truncated = re.sub(r',\s*$', "", truncated)  # trailing comma
    truncated = re.sub(r':\s*"[^"]*$', ': ""', truncated)  # partial string value
    truncated = re.sub(r":\s*$", ': null', truncated)  # key with no value

    # Close remaining open structures
    for closer in reversed(stack):
        truncated += closer

    return truncated


async def _analyze_trial(patient: PatientProfile, trial: Dict) -> Optional[Dict]:
    """Use Claude to analyze a single trial's eligibility criteria against the patient."""
    # Truncate very long eligibility text to avoid blowing up the prompt
    eligibility_text = trial["eligibility_criteria"]
    if len(eligibility_text) > 6000:
        eligibility_text = eligibility_text[:6000] + "\n\n[Eligibility text truncated — focus on the criteria above]"

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
        eligibility_criteria=eligibility_text,
    )

    client = _get_client()

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            result = _parse_json_response(text)

            if result is not None:
                # Validate required fields exist
                if "match_score" not in result:
                    result["match_score"] = 0
                return result

            # Parse failed — retry if we have attempts left
            if attempt < MAX_RETRIES:
                print(f"[MATCH] Parse failed for {trial['nct_id']}, retrying ({attempt + 1}/{MAX_RETRIES})...")
                continue

            print(f"[MATCH] Failed to parse Claude response for {trial['nct_id']} after {MAX_RETRIES + 1} attempts")
            # Last resort: try to extract at least a score from the text
            return _extract_minimal_result(text, trial["nct_id"])

        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"[MATCH] Error analyzing {trial['nct_id']}: {type(e).__name__}: {e}, retrying...")
                continue
            print(f"[MATCH] Error analyzing {trial['nct_id']}: {type(e).__name__}: {e}")
            return None

    return None


def _extract_minimal_result(text: str, nct_id: str) -> Optional[Dict]:
    """Last-resort extraction: try to pull a score and explanation from unparseable text."""
    score_match = re.search(r'"match_score"\s*:\s*(\d+)', text)
    explanation_match = re.search(r'"match_explanation"\s*:\s*"([^"]*)"', text)

    if score_match:
        return {
            "match_score": int(score_match.group(1)),
            "match_explanation": explanation_match.group(1) if explanation_match else "Analysis could not be fully parsed. Please review the trial details with your oncologist.",
            "inclusion_evaluations": [],
            "exclusion_evaluations": [],
            "flags_for_oncologist": ["Full eligibility analysis was incomplete — discuss all criteria with your oncologist"],
        }
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
        # Fallback: generate a reasonable summary locally
        treatments_str = ", ".join(patient.prior_treatments) if patient.prior_treatments else None
        biomarkers_str = ", ".join(patient.biomarkers) if patient.biomarkers else None

        summary = f"You are a {patient.age}-year-old navigating {patient.cancer_stage} {patient.cancer_type}."
        if treatments_str:
            summary += f" You have been through {patient.lines_of_therapy} line(s) of treatment including {treatments_str}."
        if biomarkers_str:
            summary += f" Your biomarker profile includes {biomarkers_str}."
        summary += " We are searching for clinical trials that may be a good fit for your specific situation."
        return summary


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
