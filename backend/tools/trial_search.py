"""Tool: Clinical trial search and retrieval.

Wraps trials_client.py functions with the ToolResult interface.
The underlying trials_client handles caching, retries, and data extraction.
"""

from __future__ import annotations

from logging_config import get_logger
from tools import ToolResult, ToolSpec, register_tool
from trials_client import find_nearest_site, get_trial, search_trials

logger = get_logger("kyriaki.tools.trial_search")


async def search_trials_tool(
    *,
    cancer_type: str,
    age: int | None = None,
    sex: str | None = None,
    page_size: int = 10,
    query_intr: str | None = None,
    query_term: str | None = None,
) -> ToolResult:
    """Search ClinicalTrials.gov for recruiting trials matching criteria."""
    try:
        trials = await search_trials(cancer_type, age, sex, page_size, query_intr=query_intr, query_term=query_term)
        return ToolResult(success=True, data=trials)
    except Exception as e:
        logger.error("tool.search_trials_failed", error=str(e))
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


async def fetch_trial_tool(*, nct_id: str) -> ToolResult:
    """Fetch a single trial by NCT ID."""
    try:
        trial = await get_trial(nct_id)
        if trial is None:
            return ToolResult(success=False, error=f"Trial {nct_id} not found")
        return ToolResult(success=True, data=trial)
    except Exception as e:
        logger.error("tool.fetch_trial_failed", nct_id=nct_id, error=str(e))
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def nearest_site_tool(*, locations: list[dict], patient_zip: str) -> ToolResult:
    """Find the nearest trial site to a patient's ZIP code."""
    site, distance = find_nearest_site(locations, patient_zip)
    return ToolResult(success=True, data={"site": site, "distance": distance})


# --- Register tools with specs ---

register_tool(
    "search_trials",
    search_trials_tool,
    ToolSpec(
        name="search_trials",
        description="Search ClinicalTrials.gov for recruiting trials matching criteria.",
        parameters={
            "cancer_type": "Condition to search (e.g., 'Non-Small Cell Lung Cancer')",
            "age": "Patient age for filtering",
            "sex": "Patient sex for filtering",
            "page_size": "Max results (default 10, max 100)",
            "query_intr": "Intervention search (e.g., 'osimertinib', 'pembrolizumab')",
            "query_term": "General term search (e.g., 'immunotherapy EGFR')",
        },
        returns="List of trial dicts with nct_id, brief_title, eligibility_criteria, locations, etc.",
        examples=[
            "search(cancer_type='NSCLC') → broad condition search",
            "search(cancer_type='NSCLC', query_intr='osimertinib') → targeted EGFR therapy search",
            "search(cancer_type='breast cancer', query_term='HER2 positive') → biomarker-specific",
        ],
        edge_cases=[
            "Returns empty list if no trials match — broaden search terms",
            "Never search for just 'cancer' — always include specific type",
            "Results are cached for 5 minutes — same query returns same results",
            "page_size capped at 100 by ClinicalTrials.gov API",
        ],
    ),
)
register_tool(
    "fetch_trial",
    fetch_trial_tool,
    ToolSpec(
        name="fetch_trial",
        description="Fetch a single trial by NCT ID for detailed data (sites, contacts, status).",
        parameters={"nct_id": "Trial identifier (e.g., 'NCT04410796')"},
        returns="Full trial dict with locations, contacts, eligibility criteria",
        edge_cases=["Returns success=False if trial not found or API error"],
    ),
)
register_tool(
    "nearest_site",
    nearest_site_tool,
    ToolSpec(
        name="nearest_site",
        description="Find the nearest trial site to a patient's ZIP code.",
        parameters={"locations": "List of trial location dicts", "patient_zip": "Patient ZIP code"},
        returns="Dict with 'site' (nearest site info) and 'distance' (miles)",
    ),
)
