"""Tool: Drug name normalization via RxNorm.

Wraps rxnorm_client.py with the ToolResult interface.
"""

from __future__ import annotations

from logging_config import get_logger
from rxnorm_client import drug_names_match, normalize_drug, normalize_drug_list
from tools import ToolResult, ToolSpec, register_tool

logger = get_logger("kyriaki.tools.drug_norm")


async def normalize_drug_tool(*, name: str) -> ToolResult:
    """Normalize a single drug name to its canonical form."""
    result = await normalize_drug(name)
    if result is None:
        return ToolResult(success=True, data={"original": name, "canonical": None, "resolved": False})
    return ToolResult(success=True, data={**result.to_dict(), "resolved": True})


async def normalize_drug_list_tool(*, names: list[str]) -> ToolResult:
    """Normalize a list of drug names concurrently."""
    results = await normalize_drug_list(names)
    return ToolResult(
        success=True,
        data={
            "normalized": {name: r.to_dict() for name, r in results.items()},
            "resolved_count": len(results),
            "total": len(names),
        },
    )


def drug_match_tool(*, name1: str, name2: str) -> ToolResult:
    """Check if two drug names refer to the same drug (local check, no API)."""
    return ToolResult(success=True, data={"match": drug_names_match(name1, name2)})


# --- Register tools ---

register_tool(
    "normalize_drug",
    normalize_drug_tool,
    ToolSpec(
        name="normalize_drug",
        description="Normalize a drug name to its canonical form via RxNorm. Resolves brand names, abbreviations, and investigational codes.",
        parameters={"name": "Drug name to normalize (e.g., 'Keytruda', 'MK-3475')"},
        returns="Dict with original, canonical name, RXCUI, and synonyms",
        examples=[
            "normalize('Keytruda') → canonical='pembrolizumab', rxcui='1547542'",
            "normalize('5-FU') → canonical='fluorouracil'",
        ],
        edge_cases=[
            "Returns resolved=False if name cannot be mapped",
            "Common oncology drugs resolve from local cache (no API call)",
            "Results cached for 24 hours",
        ],
    ),
)

register_tool(
    "normalize_drug_list",
    normalize_drug_list_tool,
    ToolSpec(
        name="normalize_drug_list",
        description="Normalize multiple drug names concurrently. Use for batch normalization of patient's prior treatments.",
        parameters={"names": "List of drug names to normalize"},
        returns="Dict mapping original name → normalized result",
    ),
)

register_tool(
    "drug_match",
    drug_match_tool,
    ToolSpec(
        name="drug_match",
        description="Quick local check if two drug names refer to the same drug (no API call).",
        parameters={"name1": "First drug name", "name2": "Second drug name"},
        returns="Dict with 'match' boolean",
        examples=["drug_match('Keytruda', 'pembrolizumab') → True"],
    ),
)
