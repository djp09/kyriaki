from __future__ import annotations

from pydantic import BaseModel, Field


class PatientProfile(BaseModel):
    cancer_type: str = Field(..., max_length=256, examples=["Non-Small Cell Lung Cancer"])
    cancer_stage: str = Field(..., max_length=64, examples=["Stage IV"])
    biomarkers: list[str] = Field(default_factory=list, examples=[["EGFR+", "PD-L1 80%", "ALK-"]])
    prior_treatments: list[str] = Field(default_factory=list, examples=[["Carboplatin/Pemetrexed", "Pembrolizumab"]])
    lines_of_therapy: int = Field(default=0, ge=0)
    age: int = Field(..., ge=0, le=120)
    sex: str = Field(..., pattern="^(male|female)$")
    ecog_score: int | None = Field(default=None, ge=0, le=4)
    key_labs: dict | None = None
    location_zip: str = Field(..., min_length=5, max_length=10)
    willing_to_travel_miles: int = Field(default=50, ge=0)
    additional_conditions: list[str] = Field(default_factory=list)
    additional_notes: str | None = Field(default=None, max_length=5000)


class CriterionEvaluation(BaseModel):
    criterion: str
    criterion_id: str = ""
    type: str = ""  # "inclusion" or "exclusion"
    status: str  # "MET", "NOT_MET", "INSUFFICIENT_INFO" (inclusion) / "TRIGGERED", "NOT_TRIGGERED", "INSUFFICIENT_INFO" (exclusion)
    confidence: str = "MEDIUM"  # "HIGH", "MEDIUM", "LOW"
    explanation: str
    patient_data_used: list[str] = Field(default_factory=list)


class TrialMatch(BaseModel):
    nct_id: str
    brief_title: str
    phase: str
    overall_status: str
    conditions: list[str]
    brief_summary: str
    eligibility_criteria: str
    match_score: float = Field(ge=0, le=100)
    match_tier: str = "UNKNOWN"  # STRONG_MATCH, POTENTIAL_MATCH, PARTIAL_MATCH, UNLIKELY_MATCH, EXCLUDED
    match_explanation: str
    inclusion_evaluations: list[CriterionEvaluation]
    exclusion_evaluations: list[CriterionEvaluation]
    flags_for_oncologist: list[str]
    criteria_met: int = 0
    criteria_not_met: int = 0
    criteria_unknown: int = 0
    criteria_total: int = 0
    nearest_site: dict | None = None
    distance_miles: float | None = None
    interventions: list[str] = Field(default_factory=list)


class MatchRequest(BaseModel):
    patient: PatientProfile
    max_results: int = Field(default=10, ge=1, le=50)


class MatchResponse(BaseModel):
    patient_summary: str
    matches: list[TrialMatch]
    total_trials_screened: int
    disclaimer: str = (
        "These results are for informational purposes only and do not constitute medical advice. "
        "Please discuss all findings with your oncologist before making any treatment decisions."
    )


# --- Inter-agent boundary schemas ---
# These validate the shape of data passed between agents via input_data/output_data.
# Catches mismatches early instead of KeyErrors deep in Claude calls.


class MatchingInput(BaseModel):
    """Input schema for MatchingAgent."""

    patient: dict
    max_results: int = Field(default=10, ge=1, le=50)


class DossierInput(BaseModel):
    """Input schema for DossierAgent — single trial analysis."""

    patient: dict
    match: dict  # single match to deep-analyze
    nct_id: str
    patient_summary: str = ""


class EnrollmentInput(BaseModel):
    """Input schema for EnrollmentAgent."""

    patient: dict
    dossier: dict
    trial_nct_id: str


class OutreachInput(BaseModel):
    """Input schema for OutreachAgent."""

    outreach_draft: dict = Field(default_factory=dict)
    trial_nct_id: str = ""
    patient: dict = Field(default_factory=dict)


class MonitorInput(BaseModel):
    """Input schema for MonitorAgent."""

    watches: list[dict] = Field(default_factory=list)


# --- Agent orchestration models ---


class TaskResponse(BaseModel):
    task_id: str
    agent_type: str
    status: str
    output_data: dict | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


class DossierRequest(BaseModel):
    matching_task_id: str
    nct_id: str  # specific trial to analyze


class GateResolution(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected)$")
    resolved_by: str = Field(..., min_length=1)
    notes: str | None = None
    chain_to_trial: str | None = None  # NCT ID to auto-chain enrollment after dossier approval


class EnrollmentRequest(BaseModel):
    dossier_task_id: str
    trial_nct_id: str


class OutreachRequest(BaseModel):
    enrollment_task_id: str


class MonitorRequest(BaseModel):
    patient_id: str


class GateResponse(BaseModel):
    gate_id: str
    task_id: str
    gate_type: str
    status: str
    requested_data: dict | None = None
    resolution_data: dict | None = None
    created_at: str
    resolved_at: str | None = None
    resolved_by: str | None = None


class EventResponse(BaseModel):
    event_id: str
    task_id: str
    event_type: str
    data: dict
    created_at: str


class TaskDetailResponse(TaskResponse):
    """TaskResponse extended with parent linkage and gates."""

    parent_task_id: str | None = None
    gates: list[GateResponse] = Field(default_factory=list)


class ActivityItem(BaseModel):
    type: str  # "task", "event", "gate"
    timestamp: str
    data: dict


# --- Ground truth feedback models ---


class OutcomeUpdate(BaseModel):
    """Manual outcome recording by a navigator."""

    site_response: str | None = Field(default=None, pattern="^(accepted|declined|no_response)$")
    screening_result: str | None = Field(default=None, pattern="^(eligible|ineligible|withdrawn)$")
    notes: str | None = None


class OutcomeResponse(BaseModel):
    patient_id: str
    nct_id: str
    match_score: int | None = None
    revised_score: int | None = None
    navigator_decision: str | None = None
    site_response: str | None = None
    screening_result: str | None = None
    outcome_notes: str | None = None
    created_at: str
    updated_at: str


class DocumentExtractionResponse(BaseModel):
    """Response from document upload + AI extraction."""

    document_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    extracted: dict  # Partial PatientProfile fields
    extraction_notes: str = ""
    token_usage: dict | None = None


class OutcomeStats(BaseModel):
    total_outcomes: int
    by_navigator_decision: dict  # {"approved": 5, "rejected": 2}
    by_screening_result: dict  # {"eligible": 3, "ineligible": 1, ...}
    avg_score_by_decision: dict  # {"approved": 72.5, "rejected": 35.0}
    avg_score_by_screening: dict  # {"eligible": 80.0, "ineligible": 40.0}
    score_accuracy: dict  # {"high_score_eligible_pct": 0.85, ...}
