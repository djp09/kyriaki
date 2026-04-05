"""Stage 1 — Intake normalization (local Gemma).

Takes messy free-text patient input + any structured form fields and produces
a canonical PatientProfile:
  - cancer_type normalized to NCIt-aligned terminology
  - biomarkers parsed into a structured list (HGNC gene + status)
  - prior treatments parsed into drug names + lines-of-therapy count

PHI stays local: this never calls Claude.
"""

from __future__ import annotations

from backend.gemma_client import get_gemma_client
from pydantic import BaseModel, Field


class NormalizedIntake(BaseModel):
    """Tolerant schema for Gemma extraction — all fields optional, caller merges with form."""

    cancer_type: str | None = Field(
        None,
        description="NCIt-canonical cancer type, e.g. 'Non-Small Cell Lung Carcinoma', 'Triple-Negative Breast Cancer'.",
    )
    cancer_stage: str | None = Field(
        None, description="Clinical stage, e.g. 'Stage IV', 'Stage IIIB'. Null if not mentioned."
    )
    biomarkers: list[str] = Field(
        default_factory=list,
        description="Biomarkers in 'GENE+' / 'GENE-' / 'MARKER level' format, e.g. 'EGFR+', 'PD-L1 80%', 'ALK-'.",
    )
    prior_treatments: list[str] = Field(
        default_factory=list,
        description="Generic drug names (normalize brand names, e.g. Keytruda -> Pembrolizumab). One regimen per entry.",
    )
    lines_of_therapy: int = Field(default=0, ge=0, description="Count of distinct prior therapy lines.")
    ecog_score: int | None = Field(default=None, ge=0, le=4)
    additional_conditions: list[str] = Field(default_factory=list)
    normalization_notes: str = Field(
        default="",
        description="Short note on any ambiguity or assumptions made during normalization.",
    )


INTAKE_NORMALIZATION_PROMPT = """\
You are a clinical intake normalizer for an oncology trial-matching engine. \
Extract and canonicalize structured patient data from the free-text input below.

## SAFETY-CRITICAL: Biomarker polarity
Getting polarity (+/-) wrong can route a patient to trials they are ineligible for.
Use these exact rules:

**POSITIVE (+) — mark with "+" when the text contains any of:**
"positive", "+", "mutated", "mutation", "mutant", "amplified", "amplification",
"rearranged", "rearrangement", "fusion", "translocation", "expressing", "high",
"detected", "found", "present", specific mutation codes (e.g. "G12C", "L858R", "T790M",
"V600E", "exon 19 del", "c.35G>A")

**NEGATIVE (-) — mark with "-" ONLY when the text contains any of:**
"negative", "-", "wild-type", "wt", "not detected", "absent", "no mutation",
"non-mutated", "unamplified", "low" (for expression markers only)

**If polarity is ambiguous or unstated, OMIT the biomarker entirely** rather than guessing.

Examples:
- "ALK-positive" → "ALK+"  (NOT "ALK-")
- "EGFR mutation" → "EGFR+"  (mutation means positive)
- "KRAS G12C" → "KRAS G12C"  (specific mutation — use mutation code, no +/-)
- "BRCA1+" → "BRCA1+"
- "ALK negative" / "ALK wild-type" → "ALK-"
- "PD-L1 80%" → "PD-L1 80%"  (expression level — keep as-is)
- "HER2 3+" (IHC score) → "HER2+"

## Cancer type (NCIt-aligned canonical terms)
Use these canonical forms exactly. If input matches a synonym, emit the canonical name:

| Input synonyms | Canonical form |
|---|---|
| NSCLC, non-small cell lung, lung adenocarcinoma | Non-Small Cell Lung Carcinoma |
| metastatic NSCLC, mNSCLC, stage IV lung | Non-Small Cell Lung Carcinoma (stage captured separately) |
| SCLC, small cell lung | Small Cell Lung Carcinoma |
| TNBC, triple negative breast | Triple-Negative Breast Cancer |
| HR+/HER2- breast | Hormone Receptor-Positive HER2-Negative Breast Cancer |
| CRC, colorectal | Colorectal Carcinoma |
| mCRC, metastatic colorectal | Metastatic Colorectal Carcinoma |
| GBM, glioblastoma | Glioblastoma Multiforme |
| AML | Acute Myeloid Leukemia |
| CML | Chronic Myeloid Leukemia |
| multiple myeloma, MM | Multiple Myeloma |
| RCC, renal cell | Renal Cell Carcinoma |
| HCC, hepatocellular | Hepatocellular Carcinoma |
| ovarian, EOC | Ovarian Carcinoma |
| pancreatic, PDAC | Pancreatic Ductal Adenocarcinoma |
| prostate, mCRPC | Prostate Adenocarcinoma |
| melanoma | Cutaneous Melanoma |

If the cancer is not in this table, use your best NCIt-style canonical form.
If only "lung cancer" is given with no subtype, note the ambiguity and default to
"Non-Small Cell Lung Carcinoma" (85% of lung cancers).

## Prior treatments & lines of therapy
Extract GENERIC drug names (never brand names). Common mappings:

| Brand | Generic |
|---|---|
| Keytruda | Pembrolizumab |
| Opdivo | Nivolumab |
| Tecentriq | Atezolizumab |
| Tagrisso | Osimertinib |
| Tarceva | Erlotinib |
| Iressa | Gefitinib |
| Xalkori | Crizotinib |
| Alecensa | Alectinib |
| Avastin | Bevacizumab |
| Herceptin | Trastuzumab |
| Perjeta | Pertuzumab |
| Lynparza | Olaparib |
| Rubraca | Rucaparib |
| Zejula | Niraparib |
| Ibrance | Palbociclib |
| Verzenio | Abemaciclib |

**Regimens: keep combinations as ONE entry** (one line of therapy = one regimen).
Known regimens (do NOT split into components):
- FOLFOX, FOLFIRI, FOLFIRINOX, CAPOX, XELOX, FLOT
- AC-T, TC, TCH, TCHP, AC, EC
- R-CHOP, R-EPOCH, R-ICE, ABVD, BEACOPP
- VRD, RVD, KRD, DVd, DRd

When a regimen is named with an addition (e.g. "FOLFIRI+bev", "FOLFOX + panitumumab"),
keep as ONE entry: "FOLFIRI/Bevacizumab".

**lines_of_therapy = count of distinct regimens the patient has received.**
- "FOLFOX, then FOLFIRI+bev" → 2 lines
- "AC-T" (single combined regimen) → 1 line
- "pembrolizumab + chemo, then osimertinib" → 2 lines

**Non-acronym regimens** — when drugs are given as a combination (not a named acronym),
keep them as ONE entry joined with "/":
- "carboplatin and pemetrexed" → "Carboplatin/Pemetrexed"  (1 line)
- "pembrolizumab plus chemotherapy" → "Pembrolizumab/Chemotherapy"  (1 line)
- "trastuzumab + pertuzumab" → "Trastuzumab/Pertuzumab"  (1 line)

## Cancer stage
Normalize to Roman numeral format with "Stage" prefix:
- "stage 4" / "stage four" / "stage iv" → "Stage IV"
- "stage 3b" / "stage IIIB" → "Stage IIIB"
- "stage 2a" → "Stage IIA"
- "metastatic" / "mCRC" / "mNSCLC" → "Stage IV" (metastatic = Stage IV)
- "recurrent" → use "Recurrent" (not a numbered stage)
- "early stage" → leave as null + note in normalization_notes (too vague)

## ECOG
Integer 0-4 only. Null if not stated numerically. Do NOT infer from qualitative
descriptions ("feels good", "tired easily") — use null + note in normalization_notes.

## Unknowns
Leave fields null/empty rather than guessing. Note all ambiguity in `normalization_notes`.

## Patient Input
{free_text}

## Structured Form Fields (if provided — treat as ground truth, do not overwrite)
{form_hints}
"""


async def normalize_intake(
    free_text: str,
    form_hints: dict | None = None,
) -> NormalizedIntake:
    """Run Gemma intake normalization on free-text patient input.

    Args:
        free_text: Raw patient description, notes, or unstructured input.
        form_hints: Any already-structured form fields (used as ground truth).

    Returns:
        NormalizedIntake with canonical fields. Caller should merge with form data.
    """
    hints_str = "(none)"
    if form_hints:
        hints_str = "\n".join(f"- {k}: {v}" for k, v in form_hints.items() if v)

    prompt = INTAKE_NORMALIZATION_PROMPT.format(
        free_text=free_text.strip() or "(empty)",
        form_hints=hints_str,
    )

    client = get_gemma_client()
    result = await client.generate(prompt, schema=NormalizedIntake)
    assert isinstance(result, NormalizedIntake)
    return result
