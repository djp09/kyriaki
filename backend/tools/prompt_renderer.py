"""Tool: Prompt rendering with validation.

Validates that all required template variables are provided before rendering.
Catches missing-variable errors early instead of deep inside Claude API calls.
"""

from __future__ import annotations

import prompts
from logging_config import get_logger
from tools import ToolResult, register_tool

logger = get_logger("kyriaki.tools.prompt_renderer")

# Schema: prompt name -> (template attribute on prompts module, required variable names)
PROMPT_SCHEMAS: dict[str, dict] = {
    "eligibility_analysis": {
        "template_attr": "ELIGIBILITY_ANALYSIS_PROMPT",
        "required": [
            "cancer_type",
            "cancer_stage",
            "biomarkers",
            "prior_treatments",
            "lines_of_therapy",
            "age",
            "sex",
            "ecog_score",
            "key_labs",
            "additional_conditions",
            "additional_notes",
            "nct_id",
            "brief_title",
            "phase",
            "brief_summary",
            "eligibility_criteria",
        ],
    },
    "patient_summary": {
        "template_attr": "PATIENT_SUMMARY_PROMPT",
        "required": [
            "cancer_type",
            "cancer_stage",
            "biomarkers",
            "prior_treatments",
            "lines_of_therapy",
            "age",
            "sex",
            "ecog_score",
        ],
    },
    "dossier_analysis": {
        "template_attr": "DOSSIER_ANALYSIS_PROMPT",
        "required": [
            "patient_json",
            "nct_id",
            "brief_title",
            "eligibility_criteria",
            "initial_score",
            "initial_explanation",
        ],
    },
    "enrollment_packet": {
        "template_attr": "ENROLLMENT_PACKET_PROMPT",
        "required": [
            "patient_json",
            "nct_id",
            "brief_title",
            "revised_score",
            "clinical_summary",
            "criteria_json",
        ],
    },
    "patient_prep": {
        "template_attr": "PATIENT_PREP_PROMPT",
        "required": [
            "cancer_type",
            "cancer_stage",
            "age",
            "brief_title",
            "site_name",
            "site_city",
            "site_state",
            "screening_checklist",
        ],
    },
    "outreach_message": {
        "template_attr": "OUTREACH_MESSAGE_PROMPT",
        "required": [
            "nct_id",
            "brief_title",
            "site_name",
            "site_city",
            "site_state",
            "contact_name",
            "patient_summary",
            "match_score",
            "match_rationale",
        ],
    },
    "score_evaluation": {
        "template_attr": "SCORE_EVALUATION_PROMPT",
        "required": [
            "cancer_type",
            "cancer_stage",
            "biomarkers",
            "prior_treatments",
            "lines_of_therapy",
            "age",
            "sex",
            "ecog_score",
            "nct_id",
            "brief_title",
            "eligibility_criteria",
            "initial_score",
            "initial_explanation",
            "criteria_json",
        ],
    },
}


def render_prompt(*, prompt_name: str, **variables) -> ToolResult:
    """Validate variables and render a prompt template. Returns the rendered string."""
    schema = PROMPT_SCHEMAS.get(prompt_name)
    if not schema:
        return ToolResult(
            success=False, error=f"Unknown prompt: {prompt_name}. Available: {list(PROMPT_SCHEMAS.keys())}"
        )

    missing = [k for k in schema["required"] if k not in variables]
    if missing:
        return ToolResult(success=False, error=f"Missing variables for '{prompt_name}': {missing}")

    template = getattr(prompts, schema["template_attr"])
    try:
        rendered = template.format(**variables)
        return ToolResult(success=True, data=rendered)
    except KeyError as e:
        return ToolResult(success=False, error=f"Template variable error: {e}")


# --- Register tool ---

register_tool("render_prompt", render_prompt)
