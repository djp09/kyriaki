# Matching Workflow

## Objective
Find clinical trials a cancer patient is likely eligible for, ranked by match confidence score.

## Required Inputs
- `patient`: PatientProfile (validated Pydantic model)
- `max_results`: int (1-50, default 10)

## Steps

### 1. Search Trials
**Tool:** `search_trials`
- Input: patient.cancer_type, patient.age, patient.sex, page_size = min(max(max_results * 2, 6), config.default_page_size)
- Output: list of trial dicts from ClinicalTrials.gov
- Emit: `progress` → `{"step": "searching_trials"}`

### 2. Generate Patient Summary (concurrent with Step 3)
**Tool:** `render_prompt` → `claude_text_call`
- Prompt: `patient_summary`
- Input: patient profile fields via `format_patient_for_prompt`
- Output: plain-language 2-3 sentence patient narrative
- Fallback: deterministic template summary if Claude call fails

### 3. Analyze Eligibility (concurrent, per trial)
**Tool:** `render_prompt` → `claude_json_call`
- Prompt: `eligibility_analysis`
- Concurrency: semaphore with config.max_concurrent_analyses
- Input per trial: patient profile + trial eligibility criteria (truncated to 6000 chars)
- Output per trial: JSON with match_score (0-100), evaluations, flags
- On JSON parse failure: retry up to config.max_retries times
- On exhausted retries: use `extract_minimal_result` regex fallback
- On total failure: return None (handled in Step 4)

### 3.5. Evaluate Borderline Scores (evaluator-optimizer loop)
**Tool:** `evaluate_score`
- Enabled via config.evaluation_enabled (default: True)
- Selects matches with score between config.evaluation_score_min (30) and config.evaluation_score_max (70)
- For each borderline match, a second Sonnet call reviews the initial analysis for:
  - Logical inconsistency (criterion marked "met" when patient data contradicts)
  - Missed hard disqualifiers (required biomarker absent, wrong cancer type)
  - Score-rubric mismatch (score doesn't align with criteria evaluations)
  - Overlooked exclusion criteria
- Concurrency: same semaphore as Step 3
- If evaluator adjusts score: use adjusted score, append reason to flags_for_oncologist
- If evaluator confirms: keep original score
- Emit: `progress` → `{"step": "evaluating_borderline", "count": N}`
- If no borderline matches: skip entirely (zero additional latency/cost)

### 4. Filter by Distance
**Tool:** `build_scored_match` (calls `nearest_site` internally)
- For each successfully analyzed trial, build TrialMatch with nearest site
- Exclude trials where distance > patient.willing_to_travel_miles
- If ALL analyses failed: use `build_unscored_match` for every trial as fallback

### 5. Rank and Trim
- Sort by match_score descending
- Return top max_results

## Expected Output
```json
{
  "patient_summary": "string",
  "matches": [TrialMatch],
  "total_trials_screened": int
}
```

## Edge Cases
- **All Claude analyses fail:** Return unscored matches with advisory flags, filtered by distance
- **No trials found:** Return empty matches with total_trials_screened = 0
- **Claude rate limited:** Handled by paced_claude_call exponential backoff
- **Eligibility text very long:** Truncated to 6000 chars with note
- **Patient summary fails:** Fallback to deterministic template
- **Evaluator fails on a borderline match:** Keep original score, log warning
- **No borderline matches:** Evaluation step skipped entirely (no cost)
