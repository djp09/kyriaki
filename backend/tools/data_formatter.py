"""Tool: Data formatting and assembly.

Pure data transformations — no AI, no network calls.
Builds TrialMatch objects, dossier sections, patient data for prompts.
"""

from __future__ import annotations

import json
from typing import Any

from logging_config import get_logger
from models import CriterionEvaluation, PatientProfile, TrialMatch
from tools import register_tool
from trials_client import find_nearest_site

logger = get_logger("kyriaki.tools.data_formatter")


def build_scored_match(trial: dict, analysis: dict, patient: PatientProfile) -> TrialMatch | None:
    """Build a TrialMatch from trial data + Claude analysis, with distance filtering."""
    nearest_site, distance = find_nearest_site(trial.get("locations", []), patient.location_zip)

    if distance is not None and distance > patient.willing_to_travel_miles:
        return None

    return TrialMatch(
        nct_id=trial["nct_id"],
        brief_title=trial["brief_title"],
        phase=trial["phase"],
        overall_status=trial["overall_status"],
        conditions=trial["conditions"],
        brief_summary=trial["brief_summary"],
        eligibility_criteria=trial["eligibility_criteria"],
        match_score=analysis.get("match_score", 0),
        match_explanation=analysis.get("match_explanation", ""),
        inclusion_evaluations=[CriterionEvaluation(**e) for e in analysis.get("inclusion_evaluations", [])],
        exclusion_evaluations=[CriterionEvaluation(**e) for e in analysis.get("exclusion_evaluations", [])],
        flags_for_oncologist=analysis.get("flags_for_oncologist", []),
        nearest_site=nearest_site,
        distance_miles=distance,
        interventions=trial.get("interventions", []),
    )


def build_unscored_match(trial: dict, patient: PatientProfile) -> TrialMatch:
    """Build a TrialMatch without analysis (fallback when all analyses fail)."""
    nearest_site, distance = find_nearest_site(trial.get("locations", []), patient.location_zip)
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


def build_dossier_section(match: dict, analysis_result: dict | None) -> dict:
    """Build a dossier section from deep analysis, with error fallback."""
    if analysis_result is None:
        logger.warning("dossier.parse_failed", nct_id=match["nct_id"])
        return {
            "nct_id": match["nct_id"],
            "brief_title": match["brief_title"],
            "analysis_error": "Failed to parse deep analysis response",
        }
    analysis_result["nct_id"] = match["nct_id"]
    analysis_result["brief_title"] = match["brief_title"]
    return analysis_result


def format_patient_for_prompt(patient: PatientProfile) -> dict[str, Any]:
    """Format a PatientProfile into the dict shape prompts expect."""
    return {
        "cancer_type": patient.cancer_type,
        "cancer_stage": patient.cancer_stage,
        "biomarkers": ", ".join(patient.biomarkers) or "None reported",
        "prior_treatments": ", ".join(patient.prior_treatments) or "None",
        "lines_of_therapy": patient.lines_of_therapy,
        "age": patient.age,
        "sex": patient.sex,
        "ecog_score": patient.ecog_score if patient.ecog_score is not None else "Not reported",
        "key_labs": json.dumps(patient.key_labs) if patient.key_labs else "Not reported",
        "additional_conditions": ", ".join(patient.additional_conditions) or "None reported",
        "additional_notes": patient.additional_notes or "None",
    }


def extract_contacts(trial: dict, max_sites: int = 5) -> list[dict]:
    """Extract contact information from trial location data."""
    contacts = []
    for loc in trial.get("locations", [])[:max_sites]:
        for contact in loc.get("contacts", []):
            contacts.append(
                {
                    "name": contact.get("name", ""),
                    "role": contact.get("role", ""),
                    "phone": contact.get("phone", ""),
                    "email": contact.get("email", ""),
                    "facility": loc.get("facility", ""),
                    "city": loc.get("city", ""),
                    "state": loc.get("state", ""),
                }
            )
    return contacts


# --- Register tools ---

register_tool("build_scored_match", build_scored_match)
register_tool("build_unscored_match", build_unscored_match)
register_tool("build_dossier_section", build_dossier_section)
register_tool("format_patient_for_prompt", format_patient_for_prompt)
register_tool("extract_contacts", extract_contacts)
