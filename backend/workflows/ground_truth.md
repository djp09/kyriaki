# Ground Truth Feedback Workflow

## Objective
Track real-world outcomes for patient-trial pairings to measure scoring accuracy and identify systematic biases over time.

## How Outcomes Are Recorded

### Automatic (wired into gate resolution)
1. **Dossier gate approved** → `navigator_decision: "approved"`, match_score and revised_score captured
2. **Dossier gate rejected** → `navigator_decision: "rejected"`
3. **Outreach gate approved** → `site_response: "accepted"`

### Manual (via API endpoint)
4. **POST /api/outcomes/{patient_id}/{nct_id}** → `screening_result`, `site_response`, notes

## Outcome Lifecycle
```
Match scored (AI) → Navigator reviews dossier → Site responds → Patient screened
     ↓                    ↓                         ↓              ↓
 match_score        navigator_decision         site_response  screening_result
```

Each step updates the same `trial_outcomes` row (upsert on patient_id + nct_id).

## Tools
- `upsert_outcome` — create or update an outcome record
- `get_outcomes_for_patient` — list all outcomes for a patient
- `compute_outcome_stats` — aggregate accuracy statistics

## Stats Computed
- Count by navigator decision (approved/rejected)
- Count by screening result (eligible/ineligible/withdrawn)
- Average score by decision and screening result
- Score accuracy: % of high-score (>=65) matches that were actually eligible
- Score accuracy: % of low-score (<40) matches that were actually ineligible

## API Endpoints
- `POST /api/outcomes/{patient_id}/{nct_id}` — record/update outcome
- `GET /api/outcomes/{patient_id}` — list patient outcomes
- `GET /api/outcomes/stats` — aggregated accuracy stats

## How to Use This Data
- If avg_score for "rejected" matches is consistently >50, scoring is inflated
- If high_score_eligible_pct is low, the scoring rubric needs tightening
- If low_score_ineligible_pct is low, we're being too conservative
- Feed these insights into prompt tuning for ELIGIBILITY_ANALYSIS_PROMPT
