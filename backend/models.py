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
    status: str  # "met", "not_met", "unknown"
    explanation: str


class TrialMatch(BaseModel):
    nct_id: str
    brief_title: str
    phase: str
    overall_status: str
    conditions: list[str]
    brief_summary: str
    eligibility_criteria: str
    match_score: int = Field(ge=0, le=100)
    match_explanation: str
    inclusion_evaluations: list[CriterionEvaluation]
    exclusion_evaluations: list[CriterionEvaluation]
    flags_for_oncologist: list[str]
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
    top_n: int = Field(default=3, ge=1, le=10)


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
