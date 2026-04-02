# Dossier Workflow

## Objective
Produce a Verified Eligibility Dossier with deep, line-by-line criterion analysis for a patient's top trial matches. The dossier is reviewed by a patient navigator before proceeding.

## Required Inputs
- `patient`: dict (patient profile data)
- `matches`: list[dict] (from MatchingAgent output, each with nct_id, match_score, eligibility_criteria, etc.)
- `patient_summary`: str (from MatchingAgent output)
- `top_n`: int (default config.dossier_top_n, usually 3)

## Steps

### 1. Select Top Matches
- Sort matches by match_score descending
- Take first top_n
- Emit: `progress` → `{"step": "deep_analysis", "trial_count": N}`

### 2. Deep Analysis (concurrent, per match)
**Tool:** `render_prompt` → `claude_json_call`
- Prompt: `dossier_analysis`
- Model: config.dossier_model (Opus for higher quality)
- Max tokens: config.dossier_max_tokens (4096)
- Concurrency: semaphore with config.dossier_max_concurrent
- Input per match: patient JSON, trial criteria, initial score and explanation
- Output per match: JSON with revised_score, criteria_analysis, clinical_summary, next_steps, flags
- Emit per match: `progress` → `{"step": "analyzing_trial", "trial_index": i, "total": N, "nct_id": "..."}`

### 3. Assemble Dossier
**Tool:** `build_dossier_section`
- For each analysis result, build a dossier section
- If analysis parse failed: section contains analysis_error flag
- Assemble full dossier with patient_summary, generated_at timestamp, sections array

### 4. Request Human Gate
- Gate type: `dossier_review`
- Requested data: the full dossier
- Task status transitions to `blocked` until navigator approves

## Expected Output
```json
{
  "dossier": {
    "patient_summary": "string",
    "generated_at": "ISO timestamp",
    "sections": [dossier_section]
  }
}
```

## Edge Cases
- **No matching dossier section found:** Individual section gets analysis_error
- **Opus call fails:** Section flagged, doesn't block other sections
- **Navigator rejects:** Task status → failed, pipeline stops
- **Navigator approves with chain_to_trial:** Auto-chains to EnrollmentAgent
