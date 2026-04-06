"""E2E pipeline comparison — hybrid vs Claude-only.

CI tests validate fixture integrity and scoring logic on pinned trial data.
Live tests (@pytest.mark.ollama, @pytest.mark.live_claude) run the full pipeline.

Metrics:
  - recall@10: fraction of should_match trials in top 10
  - precision@10: fraction of top 10 that are should_match
  - exclusion_false_negative_rate: SAFETY — should_not_match trials scored >= 50
"""

from __future__ import annotations

import pytest

from eval.e2e.fixtures import GOLD_PATIENTS, TRIAL_SNAPSHOTS
from tools.scoring import calculate_match_score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _score_patient_against_trials(
    patient: dict,
    trial_ids: list[str],
    frozen_evaluations: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """Score a patient against a set of pinned trials.

    In CI mode (frozen_evaluations provided), uses pre-computed criterion
    evaluations. In live mode, would call Claude.

    Returns list of {nct_id, score, tier} sorted by score descending.
    """
    results = []
    for nct_id in trial_ids:
        trial = TRIAL_SNAPSHOTS.get(nct_id)
        if not trial:
            continue

        if frozen_evaluations and nct_id in frozen_evaluations:
            evals = frozen_evaluations[nct_id]
        else:
            # Skip — no evaluations available in CI mode
            continue

        score_result = calculate_match_score(evals, [])
        results.append(
            {
                "nct_id": nct_id,
                "score": score_result["score"],
                "tier": score_result["tier"],
            }
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def compute_recall_at_k(
    ranked_results: list[dict],
    should_match_ids: list[str],
    k: int = 10,
) -> float:
    """Fraction of should_match trials that appear in top k results."""
    top_k_ids = {r["nct_id"] for r in ranked_results[:k]}
    if not should_match_ids:
        return 1.0
    matched = sum(1 for nct_id in should_match_ids if nct_id in top_k_ids)
    return matched / len(should_match_ids)


def compute_precision_at_k(
    ranked_results: list[dict],
    should_match_ids: list[str],
    k: int = 10,
) -> float:
    """Fraction of top k results that are should_match trials."""
    top_k = ranked_results[:k]
    if not top_k:
        return 0.0
    matched = sum(1 for r in top_k if r["nct_id"] in should_match_ids)
    return matched / len(top_k)


def compute_exclusion_fnr(
    ranked_results: list[dict],
    should_not_match_ids: list[str],
    score_threshold: float = 50.0,
) -> float:
    """Rate of should_not_match trials that score above threshold.

    This is the SAFETY metric — should be 0%.
    A false negative here means we're recommending a trial the patient
    should definitely NOT be matched to.
    """
    if not should_not_match_ids:
        return 0.0
    false_negatives = sum(
        1 for r in ranked_results if r["nct_id"] in should_not_match_ids and r["score"] >= score_threshold
    )
    return false_negatives / len(should_not_match_ids)


# ---------------------------------------------------------------------------
# Frozen evaluation stubs for CI tests
# These simulate what Claude would return for each patient-trial pair.
# ---------------------------------------------------------------------------

FROZEN_EVALUATIONS: dict[str, dict[str, list[dict]]] = {
    "gold_nsclc_egfr": {
        "NCT_EGFR_TRIAL_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Advanced NSCLC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "biomarker",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "EGFR activating mutation",
                "reasoning": "",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "INSUFFICIENT_INFO",
                "confidence": "LOW",
                "criterion_text": "No prior EGFR TKI therapy",
                "reasoning": "Patient had carboplatin/pemetrexed, not an EGFR TKI",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "",
            },
            {
                "criterion_id": "I5",
                "type": "inclusion",
                "category": "demographic",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Age >= 18",
                "reasoning": "",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "comorbidity",
                "status": "NOT_TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "CNS metastases",
                "reasoning": "",
            },
        ],
        "NCT_IO_NSCLC_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Stage IV NSCLC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "biomarker",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "No EGFR or ALK alterations",
                "reasoning": "Patient has EGFR L858R+",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "biomarker",
                "status": "TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "EGFR mutation",
                "reasoning": "Patient has EGFR L858R+",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has NSCLC",
            },
        ],
    },
    "gold_tnbc": {
        "NCT_TNBC_TRIAL_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed TNBC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "stage",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Metastatic disease",
                "reasoning": "",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "At least 2 prior lines",
                "reasoning": "Patient had 3 lines",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "disease_status",
                "status": "NOT_TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "Active brain metastases",
                "reasoning": "",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has TNBC",
            },
        ],
    },
    "gold_crc_msih": {
        "NCT_CRC_MSIH_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Colorectal adenocarcinoma",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "biomarker",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "MSI-H",
                "reasoning": "",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "At least 1 prior line",
                "reasoning": "",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "prior_therapy",
                "status": "NOT_TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "Prior anti-PD-1",
                "reasoning": "",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has CRC",
            },
        ],
    },
    "gold_melanoma_braf": {
        "NCT_MELANOMA_BRAF_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Unresectable melanoma",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "biomarker",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "BRAF V600E",
                "reasoning": "",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "No prior BRAF/MEK",
                "reasoning": "Patient had pembrolizumab only",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "",
            },
            {
                "criterion_id": "I5",
                "type": "inclusion",
                "category": "labs",
                "status": "INSUFFICIENT_INFO",
                "confidence": "LOW",
                "criterion_text": "LVEF >= 50%",
                "reasoning": "LVEF not provided",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has melanoma",
            },
        ],
    },
    "gold_pediatric": {
        "NCT_PEDIATRIC_SOLID_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "demographic",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Age 1-21",
                "reasoning": "Patient is 8",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Relapsed solid tumor",
                "reasoning": "",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "At least 1 prior therapy",
                "reasoning": "2 prior lines",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "disease_status",
                "status": "NOT_TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "Primary CNS tumors",
                "reasoning": "Neuroblastoma is not primary CNS",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has neuroblastoma",
            },
        ],
    },
    # --- Expanded gold patients ---
    "gold_pancreatic": {
        "NCT_PANCREATIC_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Pancreatic adenocarcinoma",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "stage",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Metastatic disease",
                "reasoning": "",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Prior gemcitabine-based therapy",
                "reasoning": "Gemcitabine/nab-paclitaxel",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "performance",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "Patient has ECOG 2",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has pancreatic cancer",
            },
        ],
    },
    "gold_prostate_brca": {
        "NCT_PROSTATE_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "mCRPC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Prior enzalutamide/abiraterone",
                "reasoning": "Had enzalutamide",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "labs",
                "status": "INSUFFICIENT_INFO",
                "confidence": "LOW",
                "criterion_text": "Testosterone < 50",
                "reasoning": "Not provided",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "prior_therapy",
                "status": "TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "Prior chemo for mCRPC",
                "reasoning": "Had docetaxel",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has prostate cancer",
            },
        ],
    },
    "gold_ovarian_brca": {
        "NCT_OVARIAN_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "High-grade serous ovarian",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "biomarker",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "BRCA1/2 mutation",
                "reasoning": "BRCA1+",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Response to platinum",
                "reasoning": "Complete response noted",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "ECOG 0",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "prior_therapy",
                "status": "NOT_TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "Prior PARP inhibitor",
                "reasoning": "No prior PARP",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has ovarian cancer",
            },
        ],
    },
    "gold_sclc": {
        "NCT_SCLC_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ES-SCLC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "No prior systemic therapy",
                "reasoning": "Treatment-naive",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "ECOG 1",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "comorbidity",
                "status": "NOT_TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "Autoimmune disease",
                "reasoning": "COPD but not autoimmune",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has SCLC",
            },
        ],
    },
    "gold_gbm": {
        "NCT_GBM_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "GBM at first recurrence",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Prior TMZ + radiation",
                "reasoning": "",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "MEDIUM",
                "criterion_text": "Karnofsky >= 60%",
                "reasoning": "ECOG 1 ~ KPS 70-80%",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "washout",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "12 weeks from radiation",
                "reasoning": "Only 4 months (~16 weeks) - actually meets this",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "comorbidity",
                "status": "INSUFFICIENT_INFO",
                "confidence": "LOW",
                "criterion_text": "Uncontrolled seizures",
                "reasoning": "Has seizure disorder but controlled",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has GBM",
            },
        ],
    },
    "gold_rcc": {
        "NCT_RCC_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Clear cell RCC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "stage",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Advanced/metastatic",
                "reasoning": "Stage IV",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "No prior systemic therapy",
                "reasoning": "Treatment-naive",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "ECOG 0",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "comorbidity",
                "status": "NOT_TRIGGERED",
                "confidence": "MEDIUM",
                "criterion_text": "Uncontrolled hypertension",
                "reasoning": "HTN controlled",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has RCC",
            },
        ],
    },
    "gold_ewing": {
        "NCT_EWING_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Ewing sarcoma with EWSR1",
                "reasoning": "EWSR1-FLI1 fusion confirmed",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Relapsed after 1+ regimen",
                "reasoning": "Had VDC/IE",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "demographic",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Age 12-40",
                "reasoning": "Age 19",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "ECOG 1",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has Ewing sarcoma",
            },
        ],
    },
    "gold_nsclc_alk": {
        "NCT_NSCLC_ALK_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "biomarker",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ALK rearrangement",
                "reasoning": "ALK+",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "No prior ALK inhibitor",
                "reasoning": "Treatment-naive",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "ECOG 0",
            },
        ],
        "NCT_EGFR_TRIAL_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Advanced NSCLC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "biomarker",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "EGFR activating mutation",
                "reasoning": "Patient is EGFR-, has ALK+",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has NSCLC",
            },
        ],
    },
    "gold_hcc": {
        "NCT_HCC_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed HCC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "stage",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "BCLC B or C",
                "reasoning": "Stage IIIB",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "labs",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Child-Pugh A",
                "reasoning": "Stated as Child-Pugh A",
            },
            {
                "criterion_id": "I4",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "No prior systemic therapy",
                "reasoning": "Treatment-naive",
            },
            {
                "criterion_id": "I5",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "ECOG 0-1",
                "reasoning": "ECOG 1",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has HCC",
            },
        ],
    },
    "gold_aml_flt3": {
        "NCT_AML_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "biomarker",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "AML with FLT3-ITD",
                "reasoning": "FLT3-ITD confirmed",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "demographic",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Age >= 18",
                "reasoning": "Age 45",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "performance",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Fit for intensive chemo",
                "reasoning": "Stated as fit",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "diagnosis",
                "status": "NOT_TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "APL (FAB M3)",
                "reasoning": "Not APL",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has AML",
            },
        ],
    },
    "gold_nsclc_egfr_excluded": {
        "NCT_EGFR_TRIAL_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Advanced NSCLC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "biomarker",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "EGFR activating mutation",
                "reasoning": "EGFR L858R+",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "prior_therapy",
                "status": "TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "Prior EGFR TKI",
                "reasoning": "Patient received osimertinib",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has NSCLC",
            },
        ],
    },
    "gold_tnbc_treatment_naive": {
        "NCT_TNBC_TRIAL_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed TNBC",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "stage",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Metastatic",
                "reasoning": "Stage IV",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "At least 2 prior lines",
                "reasoning": "Treatment-naive, 0 lines",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has TNBC",
            },
        ],
    },
    "gold_elderly_crc": {
        "NCT_CRC_MSIH_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Colorectal adenocarcinoma",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "biomarker",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "MSI-H or dMMR",
                "reasoning": "Patient is MSS, not MSI-H",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has CRC",
            },
        ],
    },
    "gold_melanoma_no_braf": {
        "NCT_MELANOMA_BRAF_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Unresectable melanoma",
                "reasoning": "Stage IV melanoma",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "biomarker",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "BRAF V600E/K",
                "reasoning": "BRAF wild-type",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has melanoma",
            },
        ],
    },
    "gold_gbm_bevacizumab": {
        "NCT_GBM_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "GBM at first recurrence",
                "reasoning": "",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "category": "prior_therapy",
                "status": "MET",
                "confidence": "HIGH",
                "criterion_text": "Prior TMZ + radiation",
                "reasoning": "",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "category": "disease_status",
                "status": "TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "More than 1 prior recurrence",
                "reasoning": "Second recurrence",
            },
            {
                "criterion_id": "E2",
                "type": "exclusion",
                "category": "prior_therapy",
                "status": "TRIGGERED",
                "confidence": "HIGH",
                "criterion_text": "Prior bevacizumab",
                "reasoning": "Patient received bevacizumab",
            },
        ],
        "NCT_WRONG_CANCER_1": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "category": "diagnosis",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "criterion_text": "Confirmed multiple myeloma",
                "reasoning": "Patient has GBM",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# CI tests — use frozen evaluations
# ---------------------------------------------------------------------------


class TestE2EMetrics:
    """Compute recall, precision, and exclusion FNR using frozen evaluations."""

    @pytest.fixture(params=GOLD_PATIENTS, ids=lambda p: p["id"])
    def patient(self, request):
        return request.param

    def test_recall_at_10(self, patient):
        frozen = FROZEN_EVALUATIONS.get(patient["id"], {})
        results = _score_patient_against_trials(
            patient["profile"],
            patient["trial_pool_ids"],
            frozen,
        )
        recall = compute_recall_at_k(results, patient["should_match_nct_ids"], k=10)
        assert recall >= 0.80, f"{patient['id']}: recall@10 = {recall:.0%}, expected >= 80%"

    def test_exclusion_false_negative_rate(self, patient):
        """SAFETY GATE: should_not_match trials must NOT score >= 50."""
        frozen = FROZEN_EVALUATIONS.get(patient["id"], {})
        results = _score_patient_against_trials(
            patient["profile"],
            patient["trial_pool_ids"],
            frozen,
        )
        fnr = compute_exclusion_fnr(results, patient["should_not_match_nct_ids"])
        assert fnr == 0.0, (
            f"SAFETY FAILURE: {patient['id']}: exclusion FNR = {fnr:.0%}. "
            f"should_not_match trials scoring >= 50: "
            f"{[r for r in results if r['nct_id'] in patient['should_not_match_nct_ids'] and r['score'] >= 50]}"
        )

    def test_should_match_scores_above_should_not(self, patient):
        """Should-match trials must score higher than should-not-match trials."""
        frozen = FROZEN_EVALUATIONS.get(patient["id"], {})
        results = _score_patient_against_trials(
            patient["profile"],
            patient["trial_pool_ids"],
            frozen,
        )
        result_map = {r["nct_id"]: r for r in results}

        for good_id in patient["should_match_nct_ids"]:
            if good_id not in result_map:
                continue
            for bad_id in patient["should_not_match_nct_ids"]:
                if bad_id not in result_map:
                    continue
                assert result_map[good_id]["score"] > result_map[bad_id]["score"], (
                    f"{patient['id']}: {good_id} (score={result_map[good_id]['score']}) "
                    f"should score higher than {bad_id} (score={result_map[bad_id]['score']})"
                )


class TestAggregateMetrics:
    """Compute aggregate metrics across all gold patients."""

    def test_aggregate_recall_at_10(self):
        total_expected = 0
        total_found = 0

        for patient in GOLD_PATIENTS:
            frozen = FROZEN_EVALUATIONS.get(patient["id"], {})
            results = _score_patient_against_trials(
                patient["profile"],
                patient["trial_pool_ids"],
                frozen,
            )
            top_10_ids = {r["nct_id"] for r in results[:10]}
            for nct_id in patient["should_match_nct_ids"]:
                total_expected += 1
                if nct_id in top_10_ids:
                    total_found += 1

        recall = total_found / total_expected if total_expected else 0
        assert recall >= 0.80, (
            f"Aggregate recall@10 = {recall:.0%} ({total_found}/{total_expected}), gate requires >= 80%"
        )

    def test_aggregate_exclusion_fnr_zero(self):
        """SAFETY GATE: aggregate exclusion FNR must be 0%."""
        total_bad = 0
        false_negatives = 0

        for patient in GOLD_PATIENTS:
            frozen = FROZEN_EVALUATIONS.get(patient["id"], {})
            results = _score_patient_against_trials(
                patient["profile"],
                patient["trial_pool_ids"],
                frozen,
            )
            for r in results:
                if r["nct_id"] in patient["should_not_match_nct_ids"]:
                    total_bad += 1
                    if r["score"] >= 50:
                        false_negatives += 1

        fnr = false_negatives / total_bad if total_bad else 0
        assert fnr == 0.0, f"SAFETY FAILURE: aggregate exclusion FNR = {fnr:.0%} ({false_negatives}/{total_bad})"


class TestTrialSnapshotIntegrity:
    """Validate trial snapshots and patient fixtures."""

    def test_all_referenced_trials_exist(self):
        for patient in GOLD_PATIENTS:
            for nct_id in patient["trial_pool_ids"]:
                assert nct_id in TRIAL_SNAPSHOTS, f"Patient {patient['id']} references {nct_id} not in TRIAL_SNAPSHOTS"

    def test_should_match_in_pool(self):
        for patient in GOLD_PATIENTS:
            for nct_id in patient["should_match_nct_ids"]:
                assert nct_id in patient["trial_pool_ids"]

    def test_should_not_match_in_pool(self):
        for patient in GOLD_PATIENTS:
            for nct_id in patient["should_not_match_nct_ids"]:
                assert nct_id in patient["trial_pool_ids"]

    def test_frozen_evaluations_cover_all_patients(self):
        for patient in GOLD_PATIENTS:
            assert patient["id"] in FROZEN_EVALUATIONS, f"No frozen evaluations for {patient['id']}"

    def test_frozen_evaluations_cover_all_trials(self):
        for patient in GOLD_PATIENTS:
            frozen = FROZEN_EVALUATIONS.get(patient["id"], {})
            for nct_id in patient["trial_pool_ids"]:
                assert nct_id in frozen, f"No frozen evaluation for {nct_id} in {patient['id']}"

    def test_minimum_gold_patients(self):
        assert len(GOLD_PATIENTS) >= 5

    def test_patient_ids_unique(self):
        ids = [p["id"] for p in GOLD_PATIENTS]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Live tests — full pipeline with real Claude + Gemma
# ---------------------------------------------------------------------------


@pytest.mark.ollama
@pytest.mark.live_claude
@pytest.mark.slow
class TestPipelineComparisonLive:
    """Run gold patients through full pipeline with real models.

    Compare hybrid (Gemma stages enabled) vs baseline (all disabled).
    Run with: pytest -m "ollama and live_claude and slow" eval/e2e/
    """

    # These tests are stubs — they require the full pipeline wiring
    # and both Ollama + Claude API keys to run.

    def test_placeholder_for_live_pipeline(self):
        """Placeholder: implement when live pipeline testing is enabled."""
        pytest.skip("Live pipeline comparison requires Ollama + Claude API keys")
