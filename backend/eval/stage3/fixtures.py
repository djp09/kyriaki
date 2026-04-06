"""Stage 3 — Semantic recall fixtures.

Each fixture is a patient profile + a frozen pool of trial summaries
with labeled relevance: which trials SHOULD rank in the top N.

These validate that embedding-based re-ranking improves (or at least
doesn't hurt) trial ordering compared to the ClinicalTrials.gov API's
native relevance ordering.

Key finding to validate: Stage 3 HURTS quality on small pools (<50 trials)
because shallow embeddings replace the API's better relevance ordering.
The pool >= 50 threshold in agents.py should be confirmed by these tests.
"""

from __future__ import annotations


def _make_trial(nct_id: str, title: str, conditions: list[str], phase: str, eligibility_snippet: str) -> dict:
    """Helper to build a trial dict matching the expected shape."""
    return {
        "nct_id": nct_id,
        "brief_title": title,
        "conditions": conditions,
        "phase": phase,
        "eligibility_criteria": eligibility_snippet,
    }


# =====================================================================
# Patient 1: EGFR+ NSCLC — trials should rank EGFR-specific higher
# =====================================================================
EGFR_NSCLC_PATIENT = {
    "cancer_type": "Non-Small Cell Lung Carcinoma",
    "cancer_stage": "Stage IV",
    "biomarkers": ["EGFR L858R+", "PD-L1 40%", "ALK-"],
    "prior_treatments": ["Carboplatin/Pemetrexed"],
    "lines_of_therapy": 1,
    "ecog_score": 1,
}

EGFR_NSCLC_POOL = [
    _make_trial(
        "NCT_EGFR_01",
        "Osimertinib vs Comparator in EGFR-Mutant NSCLC",
        ["NSCLC", "EGFR Mutation"],
        "PHASE3",
        "Inclusion: Confirmed NSCLC with EGFR activating mutation (exon 19del or L858R). ECOG 0-1. Age >= 18.",
    ),
    _make_trial(
        "NCT_EGFR_02",
        "Novel EGFR TKI for T790M-Resistant NSCLC",
        ["NSCLC"],
        "PHASE2",
        "Inclusion: NSCLC with EGFR T790M mutation after prior osimertinib. ECOG 0-1.",
    ),
    _make_trial(
        "NCT_IO_01",
        "Pembrolizumab Plus Chemotherapy for NSCLC",
        ["NSCLC"],
        "PHASE3",
        "Inclusion: Stage IV NSCLC regardless of PD-L1 status. No prior systemic therapy. ECOG 0-1.",
    ),
    _make_trial(
        "NCT_IO_02",
        "Atezolizumab Monotherapy for PD-L1 High NSCLC",
        ["NSCLC"],
        "PHASE3",
        "Inclusion: NSCLC with PD-L1 >= 50%. No EGFR/ALK alterations. Treatment-naive.",
    ),
    _make_trial(
        "NCT_KRAS_01",
        "Sotorasib for KRAS G12C Mutant NSCLC",
        ["NSCLC", "KRAS"],
        "PHASE3",
        "Inclusion: NSCLC with KRAS G12C mutation. Prior platinum-based therapy.",
    ),
    _make_trial(
        "NCT_SCLC_01",
        "Chemo-Immunotherapy for Extensive SCLC",
        ["SCLC"],
        "PHASE3",
        "Inclusion: Histologically confirmed extensive-stage small cell lung cancer.",
    ),
    _make_trial(
        "NCT_BREAST_01",
        "Trastuzumab Deruxtecan for HER2+ Breast Cancer",
        ["Breast Cancer"],
        "PHASE3",
        "Inclusion: HER2-positive metastatic breast cancer. Prior trastuzumab.",
    ),
    _make_trial(
        "NCT_BIOBANK_01",
        "Lung Cancer Biobanking Study",
        ["Lung Cancer"],
        "NA",
        "Inclusion: Any lung cancer diagnosis. Willing to provide tissue samples.",
    ),
]

EGFR_NSCLC_EXPECTED = {
    "should_rank_high": ["NCT_EGFR_01"],  # Direct EGFR L858R match
    "should_rank_medium": ["NCT_EGFR_02", "NCT_IO_01"],  # Related but not exact
    "should_rank_low": ["NCT_SCLC_01", "NCT_BREAST_01", "NCT_BIOBANK_01"],  # Wrong cancer
}

# =====================================================================
# Patient 2: TNBC — trials should rank TNBC-specific higher
# =====================================================================
TNBC_PATIENT = {
    "cancer_type": "Triple-Negative Breast Cancer",
    "cancer_stage": "Stage IV",
    "biomarkers": ["ER-", "PR-", "HER2-", "PD-L1 10%"],
    "prior_treatments": ["AC-T", "Capecitabine"],
    "lines_of_therapy": 2,
    "ecog_score": 1,
}

TNBC_POOL = [
    _make_trial(
        "NCT_TNBC_01",
        "Anti-Trop-2 ADC for Metastatic TNBC",
        ["Triple Negative Breast Cancer"],
        "PHASE3",
        "Inclusion: Metastatic TNBC. At least 2 prior lines of therapy. ECOG 0-1.",
    ),
    _make_trial(
        "NCT_TNBC_02",
        "Pembrolizumab + Chemo for Untreated mTNBC",
        ["TNBC"],
        "PHASE3",
        "Inclusion: Treatment-naive metastatic TNBC. PD-L1 CPS >= 10.",
    ),
    _make_trial(
        "NCT_HER2_01",
        "Trastuzumab for HER2-Positive Breast Cancer",
        ["Breast Cancer", "HER2+"],
        "PHASE3",
        "Inclusion: HER2-positive breast cancer. Prior taxane therapy.",
    ),
    _make_trial(
        "NCT_OVARIAN_01",
        "PARP Inhibitor for BRCA+ Ovarian Cancer",
        ["Ovarian Cancer"],
        "PHASE3",
        "Inclusion: High-grade serous ovarian cancer. BRCA1/2 mutation.",
    ),
    _make_trial(
        "NCT_MELANOMA_01",
        "Checkpoint Inhibitor for Advanced Melanoma",
        ["Melanoma"],
        "PHASE2",
        "Inclusion: Unresectable melanoma. No prior immunotherapy.",
    ),
]

TNBC_EXPECTED = {
    "should_rank_high": ["NCT_TNBC_01"],  # Exact match
    "should_rank_medium": ["NCT_TNBC_02"],  # Right cancer, wrong treatment line
    "should_rank_low": ["NCT_OVARIAN_01", "NCT_MELANOMA_01"],  # Wrong cancer
}

# =====================================================================
# Patient 3: MSI-H CRC — biomarker-driven trial matching
# =====================================================================
MSIH_CRC_PATIENT = {
    "cancer_type": "Colorectal Carcinoma",
    "cancer_stage": "Stage IV",
    "biomarkers": ["MSI-H", "KRAS G12D"],
    "prior_treatments": ["FOLFOX/Bevacizumab"],
    "lines_of_therapy": 1,
    "ecog_score": 0,
}

MSIH_CRC_POOL = [
    _make_trial(
        "NCT_MSIH_01",
        "Anti-PD-1 for MSI-H Solid Tumors",
        ["MSI-H", "Solid Tumors"],
        "PHASE2",
        "Inclusion: MSI-H or dMMR confirmed. Progressive after prior therapy.",
    ),
    _make_trial(
        "NCT_CRC_01",
        "FOLFIRI + Cetuximab for KRAS Wild-Type mCRC",
        ["Colorectal Cancer"],
        "PHASE3",
        "Inclusion: KRAS wild-type metastatic CRC. Prior oxaliplatin-based therapy.",
    ),
    _make_trial(
        "NCT_CRC_02",
        "Regorafenib for Refractory mCRC",
        ["Colorectal Cancer"],
        "PHASE3",
        "Inclusion: Metastatic CRC. Progressed on 2+ prior lines.",
    ),
    _make_trial(
        "NCT_LUNG_01",
        "Pembrolizumab for NSCLC",
        ["NSCLC"],
        "PHASE3",
        "Inclusion: Stage IV NSCLC. PD-L1 >= 50%.",
    ),
    _make_trial(
        "NCT_PANCREATIC_01",
        "FOLFIRINOX for Pancreatic Cancer",
        ["Pancreatic Cancer"],
        "PHASE3",
        "Inclusion: Metastatic pancreatic ductal adenocarcinoma.",
    ),
]

MSIH_CRC_EXPECTED = {
    "should_rank_high": ["NCT_MSIH_01"],  # Direct MSI-H match
    "should_rank_medium": ["NCT_CRC_02"],  # Right cancer, no biomarker match
    "should_rank_low": ["NCT_LUNG_01", "NCT_PANCREATIC_01"],  # Wrong cancer
}


# All fixtures for parameterized tests
SEMANTIC_RECALL_FIXTURES = [
    {
        "id": "sr_egfr_nsclc",
        "description": "EGFR+ NSCLC patient: EGFR trials should rank highest",
        "patient": EGFR_NSCLC_PATIENT,
        "trial_pool": EGFR_NSCLC_POOL,
        "expected": EGFR_NSCLC_EXPECTED,
    },
    {
        "id": "sr_tnbc",
        "description": "TNBC patient: TNBC trials should rank above HER2+ and other cancers",
        "patient": TNBC_PATIENT,
        "trial_pool": TNBC_POOL,
        "expected": TNBC_EXPECTED,
    },
    {
        "id": "sr_msih_crc",
        "description": "MSI-H CRC patient: MSI-H trials should rank highest, wrong cancers lowest",
        "patient": MSIH_CRC_PATIENT,
        "trial_pool": MSIH_CRC_POOL,
        "expected": MSIH_CRC_EXPECTED,
    },
]
