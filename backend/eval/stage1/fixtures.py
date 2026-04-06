"""Stage 1 — Intake normalization fixtures.

Each fixture is a messy patient input with known canonical output.
Organized by category: biomarker polarity (SAFETY-CRITICAL), cancer type,
drug normalization, regimen preservation, lines of therapy.

For CI tests: mock GemmaClient.generate() to return expected_output.
For live tests (@pytest.mark.ollama): send to Gemma and compare.
"""

from __future__ import annotations

from intake import NormalizedIntake

# =====================================================================
# BIOMARKER POLARITY — SAFETY-CRITICAL (gate: 100% accuracy)
# =====================================================================

BIOMARKER_POLARITY_FIXTURES: list[dict] = [
    {
        "id": "bp_alk_positive_word",
        "description": "ALK-positive should parse as ALK+, not ALK-",
        "input_text": "62yo female with NSCLC, ALK-positive, stage IV",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
            biomarkers=["ALK+"],
        ),
        "critical_check": {"biomarkers": ["ALK+"]},
    },
    {
        "id": "bp_alk_negative_word",
        "description": "ALK negative should parse as ALK-",
        "input_text": "55yo male, NSCLC stage IIIB, ALK negative, EGFR mutation detected",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IIIB",
            biomarkers=["ALK-", "EGFR+"],
        ),
        "critical_check": {"biomarkers": ["ALK-", "EGFR+"]},
    },
    {
        "id": "bp_egfr_mutation_implies_positive",
        "description": "'EGFR mutation' implies positive (mutation = detected)",
        "input_text": "Patient with EGFR mutation, lung adenocarcinoma, stage IV",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
            biomarkers=["EGFR+"],
        ),
        "critical_check": {"biomarkers": ["EGFR+"]},
    },
    {
        "id": "bp_kras_wildtype_negative",
        "description": "wild-type KRAS should parse as KRAS-",
        "input_text": "Colorectal cancer, MSI-H, KRAS wild-type, BRAF wild-type",
        "expected_output": NormalizedIntake(
            cancer_type="Colorectal Carcinoma",
            biomarkers=["MSI-H", "KRAS-", "BRAF-"],
        ),
        "critical_check": {"biomarkers": ["MSI-H", "KRAS-", "BRAF-"]},
    },
    {
        "id": "bp_brca1_mutated_positive",
        "description": "'BRCA1 mutated' should parse as BRCA1+",
        "input_text": "Ovarian cancer patient, BRCA1 mutated, stage IIIC",
        "expected_output": NormalizedIntake(
            cancer_type="Ovarian Carcinoma",
            cancer_stage="Stage IIIC",
            biomarkers=["BRCA1+"],
        ),
        "critical_check": {"biomarkers": ["BRCA1+"]},
    },
    {
        "id": "bp_her2_negative",
        "description": "HER2 negative should parse as HER2-",
        "input_text": "Triple negative breast cancer, ER negative, PR negative, HER2 negative",
        "expected_output": NormalizedIntake(
            cancer_type="Triple-Negative Breast Cancer",
            biomarkers=["ER-", "PR-", "HER2-"],
        ),
        "critical_check": {"biomarkers": ["ER-", "PR-", "HER2-"]},
    },
    {
        "id": "bp_pdl1_expression_level",
        "description": "PD-L1 with percentage should keep as-is",
        "input_text": "NSCLC with PD-L1 expression 80%, stage IV",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
            biomarkers=["PD-L1 80%"],
        ),
        "critical_check": {"biomarkers": ["PD-L1 80%"]},
    },
    {
        "id": "bp_alk_rearrangement_positive",
        "description": "ALK rearrangement implies positive",
        "input_text": "Patient with ALK rearrangement, NSCLC, never smoker",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            biomarkers=["ALK+"],
        ),
        "critical_check": {"biomarkers": ["ALK+"]},
    },
    {
        "id": "bp_no_egfr_mutation_negative",
        "description": "'no EGFR mutation' should be EGFR-",
        "input_text": "Lung cancer stage IV, no EGFR mutation detected, ALK rearrangement positive",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
            biomarkers=["EGFR-", "ALK+"],
        ),
        "critical_check": {"biomarkers": ["EGFR-", "ALK+"]},
    },
    {
        "id": "bp_braf_v600e_specific_mutation",
        "description": "BRAF V600E should keep mutation code",
        "input_text": "Melanoma, BRAF V600E mutation, stage IIIC",
        "expected_output": NormalizedIntake(
            cancer_type="Cutaneous Melanoma",
            cancer_stage="Stage IIIC",
            biomarkers=["BRAF V600E"],
        ),
        "critical_check": {"biomarkers": ["BRAF V600E"]},
    },
    {
        "id": "bp_kras_g12c_specific_mutation",
        "description": "KRAS G12C should keep mutation code",
        "input_text": "NSCLC with KRAS G12C, PD-L1 low, stage IV",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
            biomarkers=["KRAS G12C", "PD-L1 low"],
        ),
        "critical_check": {"biomarkers": ["KRAS G12C"]},
    },
    {
        "id": "bp_her2_3plus_ihc_positive",
        "description": "HER2 3+ (IHC score) should parse as HER2+",
        "input_text": "Breast cancer, HER2 3+ by IHC, ER positive",
        "expected_output": NormalizedIntake(
            cancer_type="Hormone Receptor-Positive HER2-Negative Breast Cancer",
            biomarkers=["HER2+", "ER+"],
        ),
        "critical_check": {"biomarkers": ["HER2+"]},
    },
    {
        "id": "bp_egfr_not_detected_negative",
        "description": "'EGFR not detected' should be EGFR-",
        "input_text": "Lung adeno, EGFR not detected, ALK not detected, ROS1 negative",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            biomarkers=["EGFR-", "ALK-", "ROS1-"],
        ),
        "critical_check": {"biomarkers": ["EGFR-", "ALK-", "ROS1-"]},
    },
]

# =====================================================================
# CANCER TYPE CANONICALIZATION
# =====================================================================

CANCER_TYPE_FIXTURES: list[dict] = [
    {
        "id": "ct_nsclc_abbreviation",
        "description": "NSCLC abbreviation → canonical form",
        "input_text": "60yo male with NSCLC, stage IV",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
        ),
        "critical_check": {"cancer_type": "Non-Small Cell Lung Carcinoma"},
    },
    {
        "id": "ct_tnbc_full_name",
        "description": "Triple negative breast cancer → canonical form",
        "input_text": "Diagnosed with triple negative breast cancer last year",
        "expected_output": NormalizedIntake(
            cancer_type="Triple-Negative Breast Cancer",
        ),
        "critical_check": {"cancer_type": "Triple-Negative Breast Cancer"},
    },
    {
        "id": "ct_colon_cancer",
        "description": "Colon cancer → Colorectal Carcinoma",
        "input_text": "72yo with colon cancer, stage III, MSI-H",
        "expected_output": NormalizedIntake(
            cancer_type="Colorectal Carcinoma",
            cancer_stage="Stage III",
            biomarkers=["MSI-H"],
        ),
        "critical_check": {"cancer_type": "Colorectal Carcinoma"},
    },
    {
        "id": "ct_metastatic_nsclc",
        "description": "Metastatic NSCLC → cancer type + Stage IV",
        "input_text": "Patient with metastatic NSCLC, EGFR+",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
            biomarkers=["EGFR+"],
        ),
        "critical_check": {"cancer_type": "Non-Small Cell Lung Carcinoma", "cancer_stage": "Stage IV"},
    },
    {
        "id": "ct_gbm",
        "description": "GBM abbreviation → Glioblastoma Multiforme",
        "input_text": "Recurrent GBM, IDH wild-type, MGMT unmethylated",
        "expected_output": NormalizedIntake(
            cancer_type="Glioblastoma Multiforme",
            cancer_stage="Recurrent",
            biomarkers=["IDH-", "MGMT unmethylated"],
        ),
        "critical_check": {"cancer_type": "Glioblastoma Multiforme"},
    },
    {
        "id": "ct_pancreatic_pdac",
        "description": "Pancreatic → Pancreatic Ductal Adenocarcinoma",
        "input_text": "68yo with pancreatic cancer, locally advanced",
        "expected_output": NormalizedIntake(
            cancer_type="Pancreatic Ductal Adenocarcinoma",
            cancer_stage="Stage III",
        ),
        "critical_check": {"cancer_type": "Pancreatic Ductal Adenocarcinoma"},
    },
]

# =====================================================================
# DRUG BRAND → GENERIC NORMALIZATION
# =====================================================================

DRUG_NORMALIZATION_FIXTURES: list[dict] = [
    {
        "id": "drug_keytruda",
        "description": "Keytruda → Pembrolizumab",
        "input_text": "Treated with Keytruda for 8 months, then progressed",
        "expected_output": NormalizedIntake(
            prior_treatments=["Pembrolizumab"],
            lines_of_therapy=1,
        ),
        "critical_check": {"prior_treatments": ["Pembrolizumab"]},
    },
    {
        "id": "drug_herceptin",
        "description": "Herceptin → Trastuzumab",
        "input_text": "Breast cancer, received Herceptin + Perjeta",
        "expected_output": NormalizedIntake(
            prior_treatments=["Trastuzumab/Pertuzumab"],
            lines_of_therapy=1,
        ),
        "critical_check": {"prior_treatments": ["Trastuzumab/Pertuzumab"]},
    },
    {
        "id": "drug_tagrisso",
        "description": "Tagrisso → Osimertinib",
        "input_text": "NSCLC, took Tagrisso as first line, then carboplatin/pemetrexed",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            prior_treatments=["Osimertinib", "Carboplatin/Pemetrexed"],
            lines_of_therapy=2,
        ),
        "critical_check": {"prior_treatments": ["Osimertinib", "Carboplatin/Pemetrexed"]},
    },
    {
        "id": "drug_lynparza",
        "description": "Lynparza → Olaparib",
        "input_text": "Ovarian cancer, on Lynparza maintenance after carboplatin/paclitaxel",
        "expected_output": NormalizedIntake(
            cancer_type="Ovarian Carcinoma",
            prior_treatments=["Carboplatin/Paclitaxel", "Olaparib"],
            lines_of_therapy=2,
        ),
        "critical_check": {"prior_treatments": ["Carboplatin/Paclitaxel", "Olaparib"]},
    },
    {
        "id": "drug_opdivo",
        "description": "Opdivo → Nivolumab",
        "input_text": "Melanoma, previously treated with Opdivo for 1 year",
        "expected_output": NormalizedIntake(
            cancer_type="Cutaneous Melanoma",
            prior_treatments=["Nivolumab"],
            lines_of_therapy=1,
        ),
        "critical_check": {"prior_treatments": ["Nivolumab"]},
    },
]

# =====================================================================
# REGIMEN PRESERVATION (don't split combined regimens)
# =====================================================================

REGIMEN_FIXTURES: list[dict] = [
    {
        "id": "regimen_act_single_line",
        "description": "AC-T is one regimen, one line",
        "input_text": "Breast cancer, completed AC-T regimen",
        "expected_output": NormalizedIntake(
            prior_treatments=["AC-T"],
            lines_of_therapy=1,
        ),
        "critical_check": {"prior_treatments": ["AC-T"], "lines_of_therapy": 1},
    },
    {
        "id": "regimen_folfox_then_folfiri",
        "description": "FOLFOX then FOLFIRI = 2 lines, each kept as single entry",
        "input_text": "CRC patient, received FOLFOX first line then FOLFIRI second line",
        "expected_output": NormalizedIntake(
            cancer_type="Colorectal Carcinoma",
            prior_treatments=["FOLFOX", "FOLFIRI"],
            lines_of_therapy=2,
        ),
        "critical_check": {"prior_treatments": ["FOLFOX", "FOLFIRI"], "lines_of_therapy": 2},
    },
    {
        "id": "regimen_folfiri_plus_bev",
        "description": "FOLFIRI+bev → FOLFIRI/Bevacizumab as one entry",
        "input_text": "Metastatic CRC, treated with FOLFIRI plus bevacizumab",
        "expected_output": NormalizedIntake(
            cancer_type="Metastatic Colorectal Carcinoma",
            cancer_stage="Stage IV",
            prior_treatments=["FOLFIRI/Bevacizumab"],
            lines_of_therapy=1,
        ),
        "critical_check": {"lines_of_therapy": 1},
    },
    {
        "id": "regimen_rchop",
        "description": "R-CHOP stays as single regimen",
        "input_text": "DLBCL, completed 6 cycles of R-CHOP",
        "expected_output": NormalizedIntake(
            prior_treatments=["R-CHOP"],
            lines_of_therapy=1,
        ),
        "critical_check": {"prior_treatments": ["R-CHOP"], "lines_of_therapy": 1},
    },
]

# =====================================================================
# LINES OF THERAPY COUNTING
# =====================================================================

LINES_OF_THERAPY_FIXTURES: list[dict] = [
    {
        "id": "lot_treatment_naive",
        "description": "Treatment-naive → 0 lines",
        "input_text": "Newly diagnosed NSCLC, no prior treatment",
        "expected_output": NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            prior_treatments=[],
            lines_of_therapy=0,
        ),
        "critical_check": {"lines_of_therapy": 0},
    },
    {
        "id": "lot_three_lines",
        "description": "Three sequential regimens = 3 lines",
        "input_text": "mCRPC patient, received enzalutamide, then docetaxel, then olaparib",
        "expected_output": NormalizedIntake(
            cancer_type="Prostate Adenocarcinoma",
            cancer_stage="Stage IV",
            prior_treatments=["Enzalutamide", "Docetaxel", "Olaparib"],
            lines_of_therapy=3,
        ),
        "critical_check": {"lines_of_therapy": 3},
    },
    {
        "id": "lot_combo_is_one_line",
        "description": "Combination given together = 1 line",
        "input_text": "Treated with pembrolizumab plus chemotherapy as first line",
        "expected_output": NormalizedIntake(
            prior_treatments=["Pembrolizumab/Chemotherapy"],
            lines_of_therapy=1,
        ),
        "critical_check": {"lines_of_therapy": 1},
    },
]


# All fixtures combined for parameterized tests
ALL_STAGE1_FIXTURES = (
    BIOMARKER_POLARITY_FIXTURES
    + CANCER_TYPE_FIXTURES
    + DRUG_NORMALIZATION_FIXTURES
    + REGIMEN_FIXTURES
    + LINES_OF_THERAPY_FIXTURES
)
