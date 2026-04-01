import asyncio
import json
import os
import time
from typing import Dict, List, Optional

import anthropic

from models import PatientProfile, TrialMatch, CriterionEvaluation
from prompts import ELIGIBILITY_ANALYSIS_PROMPT, PATIENT_SUMMARY_PROMPT
from trials_client import search_trials, find_nearest_site

MAX_CONCURRENT_ANALYSES = 1
MODEL = "claude-sonnet-4-20250514"

# Delay between sequential Claude API calls (seconds) to stay under output token rate limits
INTER_CALL_DELAY = 2.0


def _get_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


async def _call_claude_with_retry(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    max_tokens: int,
    messages: list,
    max_retries: int = 3,
) -> anthropic.types.Message:
    """Call Claude API with exponential backoff retry on rate limit (429) errors."""
    for attempt in range(max_retries):
        try:
            return await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
            )
        except anthropic.RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt * 2  # 2s, 4s, 8s
            print(f"[MATCH] Rate limited (429), retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
            await asyncio.sleep(wait_time)
        except anthropic.APIStatusError as e:
            if e.status_code == 429:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2 ** attempt * 2
                print(f"[MATCH] Rate limited (429), retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                await asyncio.sleep(wait_time)
            else:
                raise
    # Should not reach here, but just in case
    raise RuntimeError("Exhausted retries without success or exception")


# Timestamp of last Claude API call, used to pace sequential calls
_last_call_time: float = 0.0
_call_lock = asyncio.Lock()


async def _paced_claude_call(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    max_tokens: int,
    messages: list,
) -> anthropic.types.Message:
    """Call Claude with rate-limit-aware pacing and retry."""
    global _last_call_time
    async with _call_lock:
        now = time.monotonic()
        elapsed = now - _last_call_time
        if elapsed < INTER_CALL_DELAY:
            await asyncio.sleep(INTER_CALL_DELAY - elapsed)
        result = await _call_claude_with_retry(
            client, model=model, max_tokens=max_tokens, messages=messages
        )
        _last_call_time = time.monotonic()
        return result


async def _analyze_trial(
    patient: PatientProfile, trial: Dict, trial_index: int = 0, total_trials: int = 0
) -> Optional[Dict]:
    """Use Claude to analyze a single trial's eligibility criteria against the patient."""
    label = f"{trial_index}/{total_trials}" if total_trials else ""
    nct_id = trial["nct_id"]
    print(f"[MATCH] Analyzing trial {label}: {nct_id} — {trial['brief_title'][:60]}...")

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
        nct_id=nct_id,
        brief_title=trial["brief_title"],
        phase=trial["phase"],
        brief_summary=trial["brief_summary"],
        eligibility_criteria=trial["eligibility_criteria"],
    )

    try:
        response = await _paced_claude_call(
            _get_client(),
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
        print(f"[MATCH] Failed to parse Claude response for {nct_id}: {e}")
        return None
    except Exception as e:
        print(f"[MATCH] Error analyzing {nct_id}: {type(e).__name__}: {e}")
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
        response = await _paced_claude_call(
            _get_client(),
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[MATCH] Patient summary error: {type(e).__name__}: {e}")
        return f"{patient.age}-year-old {patient.sex} with {patient.cancer_stage} {patient.cancer_type}."


def _build_unscored_match(trial: Dict, patient: PatientProfile) -> TrialMatch:
    """Build a TrialMatch with score 0 from raw trial data (used as fallback)."""
    nearest_site, distance = find_nearest_site(
        trial.get("locations", []), patient.location_zip
    )
    return TrialMatch(
        nct_id=trial["nct_id"],
        brief_title=trial["brief_title"],
        phase=trial["phase"],
        overall_status=trial["overall_status"],
        conditions=trial["conditions"],
        brief_summary=trial["brief_summary"],
        eligibility_criteria=trial["eligibility_criteria"],
        match_score=0,
        match_explanation="Unable to analyze eligibility — raw trial listing provided for your oncologist to review.",
        inclusion_evaluations=[],
        exclusion_evaluations=[],
        flags_for_oncologist=["All criteria need manual review — automated analysis was unavailable."],
        nearest_site=nearest_site,
        distance_miles=distance,
        interventions=trial.get("interventions", []),
    )


async def match_trials(patient: PatientProfile, max_results: int = 10) -> Dict:
    """Full matching pipeline: search -> analyze -> rank -> return."""

    # Step 1: Search ClinicalTrials.gov
    trials = await search_trials(
        cancer_type=patient.cancer_type,
        age=patient.age,
        sex=patient.sex,
    )

    total = len(trials)
    print(f"[MATCH] Found {total} candidate trials, beginning analysis...")

    # Step 2: Analyze each trial with Claude (with concurrency limit)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)

    async def analyze_with_limit(trial: Dict, index: int):
        async with semaphore:
            return trial, await _analyze_trial(patient, trial, index, total)

    # Run patient summary generation concurrently with trial analyses
    summary_task = asyncio.create_task(_generate_patient_summary(patient))
    analysis_tasks = [analyze_with_limit(trial, i + 1) for i, trial in enumerate(trials)]
    results = await asyncio.gather(*analysis_tasks)

    # Step 3: Build TrialMatch objects and rank
    matches: List[TrialMatch] = []
    all_analyses_failed = all(analysis is None for _, analysis in results)

    if all_analyses_failed and trials:
        # Fallback: return unscored trial list so the patient still gets something
        print("[MATCH] All Claude analyses failed — returning unscored trial list as fallback.")
        for trial, _ in results:
            match = _build_unscored_match(trial, patient)
            if match.distance_miles is None or match.distance_miles <= patient.willing_to_travel_miles:
                matches.append(match)
    else:
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
        "total_trials_screened": total,
    }
