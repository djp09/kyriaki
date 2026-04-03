"""Tool: Biomarker actionability lookups via CIViC.

Wraps civic_client.py with the ToolResult interface.
"""

from __future__ import annotations

from civic_client import format_biomarker_context, lookup_biomarkers, lookup_gene
from logging_config import get_logger
from tools import ToolResult, ToolSpec, register_tool

logger = get_logger("kyriaki.tools.biomarker")


async def lookup_gene_tool(*, gene_name: str) -> ToolResult:
    """Look up all CIViC evidence for a gene."""
    evidence = await lookup_gene(gene_name)
    return ToolResult(
        success=True,
        data={
            "gene": gene_name,
            "evidence": [e.to_dict() for e in evidence],
            "count": len(evidence),
            "therapeutic_count": sum(1 for e in evidence if e.is_therapeutic),
        },
    )


async def enrich_biomarkers_tool(
    *, biomarkers: list[str], cancer_type: str | None = None
) -> ToolResult:
    """Look up CIViC evidence for patient biomarkers and format for prompt injection."""
    enrichments = await lookup_biomarkers(biomarkers, cancer_type=cancer_type)
    context_block = format_biomarker_context(enrichments)
    return ToolResult(
        success=True,
        data={
            "enrichments": enrichments,
            "context_block": context_block,
            "genes_found": len(enrichments),
            "total_biomarkers": len(biomarkers),
        },
    )


# --- Register tools ---

register_tool(
    "lookup_gene",
    lookup_gene_tool,
    ToolSpec(
        name="lookup_gene",
        description="Look up all CIViC evidence for a cancer gene. Returns therapeutic evidence sorted by evidence level.",
        parameters={"gene_name": "Gene name (e.g., 'EGFR', 'BRAF', 'ALK')"},
        returns="Dict with evidence items, counts, and therapeutic relevance",
        examples=[
            "lookup_gene('EGFR') → evidence for EGFR variants and therapies",
            "lookup_gene('BRAF') → V600E sensitivity to dabrafenib+trametinib",
        ],
        edge_cases=[
            "Returns empty evidence list if gene not in CIViC",
            "Results cached for 1 hour",
        ],
    ),
)

register_tool(
    "enrich_biomarkers",
    enrich_biomarkers_tool,
    ToolSpec(
        name="enrich_biomarkers",
        description="Look up CIViC evidence for a list of patient biomarkers. Returns enrichment data and a pre-formatted context block for prompt injection.",
        parameters={
            "biomarkers": "List of patient-reported biomarkers (e.g., ['EGFR+', 'PD-L1 80%', 'ALK-'])",
            "cancer_type": "Optional cancer type for filtering evidence relevance",
        },
        returns="Dict with enrichments list, formatted context block, and counts",
        examples=[
            "enrich_biomarkers(['EGFR L858R', 'PD-L1 80%'], cancer_type='NSCLC') → actionable drug recommendations",
        ],
        edge_cases=[
            "Biomarkers that can't be mapped to genes are skipped",
            "CIViC API failures return empty results (graceful degradation)",
        ],
    ),
)
