"""Tool: Clinical trial search and retrieval.

Wraps trials_client.py functions with the ToolResult interface.
The underlying trials_client handles caching, retries, and data extraction.
"""

from __future__ import annotations

from logging_config import get_logger
from tools import ToolResult, ToolSpec, register_tool
from trials_client import find_nearest_site, get_trial, merge_and_deduplicate, search_nci_trials, search_trials

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


async def search_nci_trials_tool(
    *,
    cancer_type: str,
    age: int | None = None,
    sex: str | None = None,
    page_size: int = 10,
) -> ToolResult:
    """Search for NCI-sponsored oncology trials (curated subset)."""
    try:
        trials = await search_nci_trials(cancer_type, age, sex, page_size)
        return ToolResult(success=True, data=trials)
    except Exception as e:
        logger.error("tool.search_nci_failed", error=str(e))
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


async def search_and_merge_tool(
    *,
    cancer_type: str,
    age: int | None = None,
    sex: str | None = None,
    page_size: int = 10,
    query_intr: str | None = None,
    query_term: str | None = None,
    include_nci: bool = True,
) -> ToolResult:
    """Search both ClinicalTrials.gov and NCI, merge and deduplicate.

    This is the primary search entry point for the matching pipeline.
    """
    import asyncio

    tasks = [search_trials(cancer_type, age, sex, page_size, query_intr=query_intr, query_term=query_term)]
    if include_nci:
        tasks.append(search_nci_trials(cancer_type, age, sex, page_size))

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        return ToolResult(success=False, error=f"Search failed: {e}")

    trial_lists = []
    for r in results:
        if isinstance(r, list):
            trial_lists.append(r)
        elif isinstance(r, Exception):
            logger.warning("tool.search_partial_failure", error=str(r))

    if not trial_lists:
        return ToolResult(success=False, error="All searches failed")

    merged = merge_and_deduplicate(trial_lists)
    return ToolResult(
        success=True,
        data=merged,
        # Track provenance in error field (repurposed as metadata)
    )


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
register_tool(
    "search_nci_trials",
    search_nci_trials_tool,
    ToolSpec(
        name="search_nci_trials",
        description="Search NCI-sponsored oncology trials (curated subset of ClinicalTrials.gov).",
        parameters={
            "cancer_type": "Condition to search",
            "age": "Patient age for filtering",
            "sex": "Patient sex for filtering",
            "page_size": "Max results (default 10)",
        },
        returns="List of NCI-curated trial dicts",
        edge_cases=["Returns empty list on failure (graceful degradation)"],
    ),
)
register_tool(
    "search_and_merge",
    search_and_merge_tool,
    ToolSpec(
        name="search_and_merge",
        description="Search ClinicalTrials.gov + NCI concurrently, merge and deduplicate by NCT ID. Primary search entry point.",
        parameters={
            "cancer_type": "Condition to search",
            "age": "Patient age for filtering",
            "sex": "Patient sex for filtering",
            "page_size": "Max results per source",
            "query_intr": "Intervention filter",
            "query_term": "General search term",
            "include_nci": "Include NCI search (default True)",
        },
        returns="Deduplicated list of trials from both sources",
    ),
)
