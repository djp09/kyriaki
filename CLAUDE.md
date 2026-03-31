# Kyriaki — Clinical Trial Matching Engine

## Mission

Save lives by transforming the clinical trial "paperwork marathon" into a seamless, agent-led connection to the medicine of tomorrow. Kyriaki is an AI-powered patient agent for oncology clinical trial enrollment.

## What We're Building (Phase 1 MVP)

A **trial matching engine** that takes a cancer patient's profile and returns a ranked list of clinical trials they're likely eligible for, with plain-language explanations.

### The Flow

1. Patient fills out a structured intake form (cancer type, stage, biomarkers, prior treatments, key labs, location, travel willingness)
2. System queries ClinicalTrials.gov API for relevant recruiting trials
3. Claude analyzes each trial's eligibility criteria against the patient profile
4. Returns a ranked list with match scores, plain-language reasoning, and key logistics (location, phase, what's involved)

### What the AI Produces

- A ranked list of eligible trials with plain-language summaries
- For each trial: location, phase, what's involved, why the patient likely qualifies, any potential disqualifiers to discuss with their doctor
- Eventually: a shareable PDF the patient can bring to their oncologist

## Tech Stack

- **Backend:** Python 3.11+ with FastAPI
- **AI:** Claude API (Sonnet for intake processing, Opus for protocol/eligibility reasoning)
- **Database:** PostgreSQL (can start with SQLite for prototype)
- **Trial Data:** ClinicalTrials.gov API v2, refreshed nightly in production (live queries fine for prototype)
- **Frontend:** React (Vite) — simple multi-step intake form + results display
- **Hosting (later):** HIPAA-eligible cloud (AWS/GCP with BAA) — local dev for now

## ClinicalTrials.gov API v2 Reference

**Base URL:** `https://clinicaltrials.gov/api/v2`
**Rate Limit:** 10 requests/second
**Docs:** https://clinicaltrials.gov/data-api/api

### Key Endpoints

**Search studies:**
```
GET /studies?query.cond={condition}&filter.overallStatus=RECRUITING&pageSize=50
```

**Useful query parameters:**
- `query.cond` — condition (e.g., "lung cancer", "triple negative breast cancer")
- `query.intr` — intervention
- `query.term` — general search term
- `filter.overallStatus` — RECRUITING, ENROLLING_BY_INVITATION, ACTIVE_NOT_RECRUITING
- `filter.geo` — geographic filtering with distance()
- `fields` — comma-separated list of fields to return
- `pageSize` — max 1000, default 10
- `pageToken` — for pagination

**Recommended fields for matching:**
```
NCTId,BriefTitle,OfficialTitle,Condition,Phase,EligibilityModule,ContactsLocationsModule,DescriptionModule,StatusModule,ArmsInterventionsModule
```

### Study Data Structure

Studies are nested under `protocolSection`:

```
protocolSection.identificationModule.nctId          — "NCT04567890"
protocolSection.identificationModule.briefTitle     — study title
protocolSection.statusModule.overallStatus           — "RECRUITING"
protocolSection.statusModule.phases                  — ["PHASE2", "PHASE3"]

protocolSection.eligibilityModule.eligibilityCriteria — FREE TEXT (inclusion/exclusion)
protocolSection.eligibilityModule.sex                — "ALL" | "MALE" | "FEMALE"
protocolSection.eligibilityModule.minimumAge         — "18 Years"
protocolSection.eligibilityModule.maximumAge         — "75 Years"
protocolSection.eligibilityModule.healthyVolunteersAllowed — boolean

protocolSection.conditionsModule.conditions          — ["Lung Cancer", "NSCLC"]

protocolSection.contactsLocationsModule.locations[]  — array of trial sites
  .facility  — hospital/clinic name
  .city, .state, .zip, .country
  .geoPoint.lat, .geoPoint.lon                      — for distance calculation
  .status    — site-level recruiting status
  .contacts[] — site-specific contacts

protocolSection.descriptionModule.briefSummary       — study description
protocolSection.armsInterventionsModule              — treatment arms and interventions
```

**Critical note:** `eligibilityCriteria` is free-form text, not structured data. This is where Claude's reasoning is essential — it parses the natural language criteria and evaluates each against the patient profile.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  React Frontend │────▶│  FastAPI Backend  │────▶│ ClinicalTrials.gov  │
│  (intake form + │     │                  │     │      API v2          │
│   results view) │     │  /api/intake     │     └─────────────────────┘
└─────────────────┘     │  /api/match      │
                        │  /api/trials     │────▶┌─────────────────────┐
                        │                  │     │    Claude API        │
                        └──────────────────┘     │  (eligibility        │
                                                 │   reasoning)         │
                                                 └─────────────────────┘
```

### Backend Endpoints

- `POST /api/intake` — receive and validate patient profile
- `POST /api/match` — run the full matching pipeline: search trials → Claude eligibility analysis → ranked results
- `GET /api/trials/{nct_id}` — get full details for a specific trial
- `GET /api/health` — healthcheck

### Patient Profile Schema (intake form fields)

```python
class PatientProfile:
    cancer_type: str              # e.g., "Non-Small Cell Lung Cancer"
    cancer_stage: str             # e.g., "Stage IV", "Stage IIIB"
    biomarkers: list[str]         # e.g., ["EGFR+", "PD-L1 80%", "ALK-"]
    prior_treatments: list[str]   # e.g., ["Carboplatin/Pemetrexed", "Pembrolizumab"]
    lines_of_therapy: int         # how many prior lines
    age: int
    sex: str                      # "male", "female"
    ecog_score: int | None        # 0-4 performance status
    key_labs: dict | None         # e.g., {"wbc": 5.2, "platelets": 180}
    location_zip: str             # for proximity matching
    willing_to_travel_miles: int  # max travel distance
    additional_conditions: list[str]  # comorbidities
    additional_notes: str | None  # free text from patient
```

### Matching Engine Logic

1. **Pre-filter** — query ClinicalTrials.gov for recruiting trials matching cancer type. Filter by age, sex, geographic radius.
2. **Claude analysis** — for each candidate trial, send Claude the patient profile + full eligibility criteria text. Ask it to:
   - Evaluate each inclusion criterion (met / not met / unknown)
   - Evaluate each exclusion criterion (triggered / not triggered / unknown)
   - Assign a match confidence score (0-100)
   - Write a plain-language explanation of why the patient does or doesn't match
   - Flag any criteria that need the patient's oncologist to confirm
3. **Rank** — sort by match score, surface top results
4. **Enrich** — add logistics: distance to nearest site, trial phase, what treatment involves

## Focus Cancers (Start Here)

- Stage IV non-small cell lung cancer (NSCLC) — high urgency, many trials
- Triple-negative breast cancer (TNBC) — high unmet need
- Rare pediatric cancers — underserved, mission-aligned

## Key Design Principles

- **Patient-first language** — all outputs should be understandable by a non-medical person
- **Clinical decision SUPPORT, not decision MAKING** — always frame as "discuss with your oncologist"
- **Never submit anything on behalf of the patient** without explicit action
- **Free for patients, always** — this is the mission
- **Concierge hybrid model** — AI does 90%+ of the work, humans sign off at gates
- **Don't over-engineer** — this is a solo founder on evenings/weekends. Working > perfect.

## Project Structure (suggested)

```
kyriaki/
├── CLAUDE.md                  # this file
├── backend/
│   ├── main.py                # FastAPI app
│   ├── models.py              # Pydantic schemas (PatientProfile, TrialMatch, etc.)
│   ├── trials_client.py       # ClinicalTrials.gov API client
│   ├── matching_engine.py     # Claude-powered eligibility analysis
│   ├── prompts.py             # Prompt templates for Claude
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── IntakeForm.jsx       # multi-step patient intake
│   │   │   ├── TrialResults.jsx     # ranked match results
│   │   │   └── TrialDetail.jsx      # expanded trial view
│   │   └── api.js                   # backend API calls
│   ├── package.json
│   └── vite.config.js
└── README.md
```

## Environment Variables Needed

```
ANTHROPIC_API_KEY=your-key-here
```

## What NOT to Build Yet

- User authentication / accounts
- Database persistence (in-memory or file-based is fine for prototype)
- HIPAA compliance infrastructure
- FHIR/TEFCA health record integration
- PDF report generation
- Patient navigator review workflow
- Payment or revenue features

## Reference Documents

See these files in the project root for full business context:
- `Kyriaki_Refined_Plan_v2.md` — full phased plan
- `Kyriaki_Market_Validation_Report.md` — competitive landscape and market analysis
- `Kyriaki_Business_Plan_2026_1.md` — original business plan
