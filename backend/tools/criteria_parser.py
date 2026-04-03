"""Tool: Eligibility criteria parser.

Splits free-text eligibility criteria from ClinicalTrials.gov into
structured individual criteria with categories. Uses a rule-based
approach first, falling back to Claude for ambiguous blocks.

This runs BEFORE the matching call so Claude evaluates individual
criteria rather than an entire eligibility block at once.
"""

from __future__ import annotations

import re
from typing import Any

from logging_config import get_logger
from tools import ToolResult, ToolSpec, register_tool

logger = get_logger("kyriaki.tools.criteria_parser")

# Categories for criteria classification
# ORDER MATTERS: first match wins. disease_status before biomarker to avoid
# "metastases" matching short biomarker keywords.
CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("diagnosis", ["histolog", "confirm", "diagnos", "patholog", "cytolog"]),
    (
        "disease_status",
        ["measurable", "evaluable", "recist", "lesion", "metastas", "cns", "brain", "leptomeningeal", "spinal cord"],
    ),
    (
        "stage",
        ["stage", "locally advanced", "unresectable", "recurrent", "refractory", "relapsed", "progressive"],
    ),
    (
        "biomarker",
        [
            "mutation",
            "egfr",
            "alk",
            "ros1",
            "braf",
            "kras",
            "her2",
            "pd-l1",
            "brca",
            "ntrk",
            "met amplification",
            "met exon",
            "c-met",
            "ret",
            "fgfr",
            "pik3ca",
            "erbb",
            "msi",
            "mmr",
            "tmb",
            "biomarker",
            "molecular",
            "genomic",
            "expression",
            "amplification",
            "rearrangement",
            "fusion",
            "variant",
            "receptor",
        ],
    ),
    (
        "prior_therapy",
        [
            "prior",
            "previous",
            "treated",
            "therapy",
            "regimen",
            "line",
            "chemotherapy",
            "immunotherapy",
            "radiation",
            "surgery",
            "anti-pd",
            "anti-ctla",
            "checkpoint",
            "tyrosine kinase",
        ],
    ),
    (
        "demographic",
        [
            "age",
            "years old",
            "≥ 18",
            ">= 18",
            "≥18",
            "adult",
            "pediatric",
            "male",
            "female",
            "sex",
            "gender",
            "pregnan",
            "childbearing",
            "contraception",
            "breastfeed",
            "nursing",
        ],
    ),
    ("performance", ["ecog", "karnofsky", "performance status", "ambulatory", "functional status"]),
    (
        "labs",
        [
            "anc",
            "neutrophil",
            "platelet",
            "hemoglobin",
            "creatinine",
            "bilirubin",
            "ast",
            "alt",
            "albumin",
            "inr",
            "wbc",
            "white blood",
            "liver function",
            "renal function",
            "organ function",
            "adequate",
            "laboratory",
        ],
    ),
    (
        "comorbidity",
        [
            "autoimmune",
            "hiv",
            "hepatitis",
            "interstitial lung",
            "pneumonitis",
            "cardiac",
            "heart failure",
            "transplant",
            "active infection",
            "tuberculosis",
            "seizure",
            "stroke",
            "bleeding",
            "thrombo",
        ],
    ),
    ("washout", ["washout", "half-lives", "days prior", "weeks prior", "days before", "weeks before", "within"]),
    ("consent", ["consent", "willing", "able to", "comply", "follow-up"]),
]


def _classify_criterion(text: str) -> str:
    """Classify a criterion into a category based on keyword matching.

    Order matters: categories are checked top-to-bottom, first match wins.
    disease_status must come before biomarker to avoid 'metastases' matching 'met'.
    """
    text_lower = text.lower()
    for category, keywords in CATEGORY_PATTERNS:
        for kw in keywords:
            # For very short keywords (<=3 chars), require word boundary
            if len(kw) <= 3:
                if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                    return category
            elif kw in text_lower:
                return category
    return "other"


def _is_section_header(line: str) -> str | None:
    """Detect inclusion/exclusion section headers. Returns 'inclusion' or 'exclusion' or None."""
    line_lower = line.strip().lower()
    # Common header patterns
    if re.match(r"^(key\s+)?inclusion\s+criteria\s*:?\s*$", line_lower):
        return "inclusion"
    if re.match(r"^(key\s+)?exclusion\s+criteria\s*:?\s*$", line_lower):
        return "exclusion"
    if re.match(r"^inclusion\s*:?\s*$", line_lower):
        return "inclusion"
    if re.match(r"^exclusion\s*:?\s*$", line_lower):
        return "exclusion"
    if "inclusion criteria" in line_lower and len(line_lower) < 40:
        return "inclusion"
    if "exclusion criteria" in line_lower and len(line_lower) < 40:
        return "exclusion"
    return None


def _split_criteria_text(text: str) -> list[dict[str, Any]]:
    """Split eligibility criteria text into individual criteria.

    Handles common ClinicalTrials.gov formatting:
    - Numbered lists (1., 2., etc.)
    - Bulleted lists (-, *, •)
    - Newline-separated items
    - Inclusion/Exclusion section headers
    """
    lines = text.strip().split("\n")
    criteria = []
    current_type = "inclusion"  # default until we see a header
    current_criterion = ""
    criterion_id = 0

    for line in lines:
        line = line.strip()
        if not line:
            # Empty line — flush current criterion
            if current_criterion.strip():
                criterion_id += 1
                criteria.append(
                    {
                        "id": f"{'inc' if current_type == 'inclusion' else 'exc'}_{criterion_id}",
                        "text": current_criterion.strip(),
                        "type": current_type,
                        "category": _classify_criterion(current_criterion),
                    }
                )
                current_criterion = ""
            continue

        # Check for section header
        header = _is_section_header(line)
        if header:
            # Flush any pending criterion
            if current_criterion.strip():
                criterion_id += 1
                criteria.append(
                    {
                        "id": f"{'inc' if current_type == 'inclusion' else 'exc'}_{criterion_id}",
                        "text": current_criterion.strip(),
                        "type": current_type,
                        "category": _classify_criterion(current_criterion),
                    }
                )
                current_criterion = ""
            current_type = header
            continue

        # Check for list item start (numbered or bulleted)
        is_list_item = bool(re.match(r"^(\d+[\.\)]\s*|-\s+|\*\s+|•\s+|–\s+)", line))

        if is_list_item:
            # Flush previous criterion
            if current_criterion.strip():
                criterion_id += 1
                criteria.append(
                    {
                        "id": f"{'inc' if current_type == 'inclusion' else 'exc'}_{criterion_id}",
                        "text": current_criterion.strip(),
                        "type": current_type,
                        "category": _classify_criterion(current_criterion),
                    }
                )
            # Start new criterion (strip the bullet/number)
            current_criterion = re.sub(r"^(\d+[\.\)]\s*|-\s+|\*\s+|•\s+|–\s+)", "", line)
        else:
            # Continuation of current criterion
            if current_criterion:
                current_criterion += " " + line
            else:
                current_criterion = line

    # Flush last criterion
    if current_criterion.strip():
        criterion_id += 1
        criteria.append(
            {
                "id": f"{'inc' if current_type == 'inclusion' else 'exc'}_{criterion_id}",
                "text": current_criterion.strip(),
                "type": current_type,
                "category": _classify_criterion(current_criterion),
            }
        )

    return criteria


def parse_eligibility_criteria(eligibility_text: str) -> ToolResult:
    """Parse free-text eligibility criteria into structured individual criteria.

    Returns ToolResult with data = {
        "inclusion_criteria": [...],
        "exclusion_criteria": [...],
        "total_criteria": int,
    }
    """
    if not eligibility_text or not eligibility_text.strip():
        return ToolResult(success=False, error="Empty eligibility text")

    all_criteria = _split_criteria_text(eligibility_text)

    # Filter out very short criteria (likely parsing artifacts)
    all_criteria = [c for c in all_criteria if len(c["text"]) >= 10]

    inclusion = [c for c in all_criteria if c["type"] == "inclusion"]
    exclusion = [c for c in all_criteria if c["type"] == "exclusion"]

    # If we got zero inclusion criteria, the text might not have clear headers.
    # Treat everything as inclusion (conservative — nothing excluded).
    if not inclusion and all_criteria:
        for c in all_criteria:
            c["type"] = "inclusion"
            c["id"] = c["id"].replace("exc_", "inc_")
        inclusion = all_criteria
        exclusion = []

    logger.info(
        "criteria.parsed",
        inclusion=len(inclusion),
        exclusion=len(exclusion),
        total=len(all_criteria),
    )

    return ToolResult(
        success=True,
        data={
            "inclusion_criteria": inclusion,
            "exclusion_criteria": exclusion,
            "total_criteria": len(all_criteria),
        },
    )


# --- Register tool ---

register_tool(
    "parse_eligibility_criteria",
    parse_eligibility_criteria,
    ToolSpec(
        name="parse_eligibility_criteria",
        description="Parse free-text eligibility criteria into structured individual criteria with categories.",
        parameters={"eligibility_text": "Raw eligibility criteria text from ClinicalTrials.gov"},
        returns="Dict with inclusion_criteria[], exclusion_criteria[], total_criteria",
        edge_cases=[
            "Returns all as inclusion if no exclusion header found (conservative)",
            "Filters out criteria shorter than 10 chars (parsing artifacts)",
            "Handles numbered lists, bulleted lists, and plain newline-separated text",
        ],
    ),
)
