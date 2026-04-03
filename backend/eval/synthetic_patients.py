"""Synthetic patient profiles for evaluation.

Each patient has:
- A realistic clinical profile
- expected_good_matches: trials they SHOULD score high on (>= 50)
- expected_bad_matches: trials they SHOULD score low on (< 30) or be EXCLUDED
- expected_tier: the rough tier we expect for good matches

These are hand-curated based on reading actual ClinicalTrials.gov eligibility
criteria for the listed NCT IDs. The goal is to test score differentiation
and criterion-level accuracy, not retrieval.
"""

from __future__ import annotations

SYNTHETIC_PATIENTS = [
    # --- Patient 1: Classic EGFR+ NSCLC, good candidate for EGFR trials ---
    {
        "id": "eval_nsclc_egfr",
        "label": "NSCLC EGFR+ Stage IV, 1 prior line",
        "profile": {
            "cancer_type": "Non-Small Cell Lung Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["EGFR L858R+", "PD-L1 40%", "ALK-"],
            "prior_treatments": ["Carboplatin/Pemetrexed"],
            "lines_of_therapy": 1,
            "age": 58,
            "sex": "female",
            "ecog_score": 1,
            "key_labs": {"wbc": 6.1, "platelets": 210, "creatinine": 0.8},
            "location_zip": "10001",
            "willing_to_travel_miles": 100,
            "additional_conditions": [],
            "additional_notes": None,
        },
        "expected_good_criteria": {
            # These criterion types should be MET for EGFR-targeted trials
            "diagnosis": "MET",
            "biomarker": "MET",  # EGFR L858R matches EGFR mutation requirement
            "demographic": "MET",
            "performance": "MET",
        },
    },
    # --- Patient 2: TNBC, heavily pre-treated ---
    {
        "id": "eval_tnbc_heavy",
        "label": "TNBC Stage IV, 3 prior lines",
        "profile": {
            "cancer_type": "Triple Negative Breast Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["ER-", "PR-", "HER2-", "PD-L1 10%", "BRCA1 wild-type"],
            "prior_treatments": ["AC-T", "Capecitabine", "Sacituzumab govitecan"],
            "lines_of_therapy": 3,
            "age": 47,
            "sex": "female",
            "ecog_score": 1,
            "key_labs": {"wbc": 4.8, "platelets": 165, "hemoglobin": 11.2},
            "location_zip": "90210",
            "willing_to_travel_miles": 200,
            "additional_conditions": [],
            "additional_notes": "Progressed on sacituzumab govitecan after 4 cycles",
        },
        "expected_good_criteria": {
            "diagnosis": "MET",
            "stage": "MET",
            "demographic": "MET",
        },
    },
    # --- Patient 3: Pediatric neuroblastoma ---
    {
        "id": "eval_peds_neuro",
        "label": "Neuroblastoma, 8yo, high-risk",
        "profile": {
            "cancer_type": "Neuroblastoma",
            "cancer_stage": "Stage IV",
            "biomarkers": ["MYCN amplified"],
            "prior_treatments": ["Induction chemotherapy", "Stem cell transplant"],
            "lines_of_therapy": 2,
            "age": 8,
            "sex": "male",
            "ecog_score": 1,
            "key_labs": None,
            "location_zip": "19104",
            "willing_to_travel_miles": 500,
            "additional_conditions": [],
            "additional_notes": "High-risk neuroblastoma, post-transplant relapse",
        },
        "expected_good_criteria": {
            "diagnosis": "MET",
            "demographic": "MET",  # pediatric trials accept age 8
        },
    },
    # --- Patient 4: Colorectal, MSI-H ---
    {
        "id": "eval_crc_msih",
        "label": "Colorectal MSI-H Stage IV, 1 prior line",
        "profile": {
            "cancer_type": "Colorectal Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["MSI-H", "KRAS G12D", "BRAF wild-type"],
            "prior_treatments": ["FOLFOX + Bevacizumab"],
            "lines_of_therapy": 1,
            "age": 65,
            "sex": "male",
            "ecog_score": 0,
            "key_labs": {"wbc": 7.2, "platelets": 280, "creatinine": 1.0, "hemoglobin": 13.5},
            "location_zip": "77030",
            "willing_to_travel_miles": 150,
            "additional_conditions": ["Type 2 Diabetes", "Hypertension"],
            "additional_notes": None,
        },
        "expected_good_criteria": {
            "diagnosis": "MET",
            "biomarker": "MET",  # MSI-H is actionable
            "performance": "MET",
            "labs": "MET",
        },
    },
    # --- Patient 5: Melanoma, BRAF V600E ---
    {
        "id": "eval_melanoma_braf",
        "label": "Melanoma BRAF V600E Stage IIIC",
        "profile": {
            "cancer_type": "Melanoma",
            "cancer_stage": "Stage IIIC",
            "biomarkers": ["BRAF V600E", "PD-L1 60%"],
            "prior_treatments": ["Pembrolizumab"],
            "lines_of_therapy": 1,
            "age": 52,
            "sex": "male",
            "ecog_score": 0,
            "key_labs": {"wbc": 5.5, "platelets": 220, "ldh": 190},
            "location_zip": "33136",
            "willing_to_travel_miles": 100,
            "additional_conditions": [],
            "additional_notes": "Progressed on pembrolizumab after 8 months",
        },
        "expected_good_criteria": {
            "diagnosis": "MET",
            "biomarker": "MET",
            "demographic": "MET",
        },
    },
    # --- Patient 6: Pancreatic, late stage, limited options ---
    {
        "id": "eval_pancreatic",
        "label": "Pancreatic Stage IV, 2 prior lines",
        "profile": {
            "cancer_type": "Pancreatic Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["KRAS G12V"],
            "prior_treatments": ["FOLFIRINOX", "Gemcitabine/nab-paclitaxel"],
            "lines_of_therapy": 2,
            "age": 71,
            "sex": "female",
            "ecog_score": 2,
            "key_labs": {"wbc": 3.8, "platelets": 120, "bilirubin": 1.8, "albumin": 2.9},
            "location_zip": "60637",
            "willing_to_travel_miles": 50,
            "additional_conditions": ["Biliary stent"],
            "additional_notes": "Recent biliary stent placement, moderate fatigue",
        },
        "expected_good_criteria": {
            "diagnosis": "MET",
            "stage": "MET",
        },
    },
    # --- Patient 7: Prostate, BRCA2+ ---
    {
        "id": "eval_prostate_brca",
        "label": "Prostate mCRPC, BRCA2+",
        "profile": {
            "cancer_type": "Prostate Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["BRCA2 mutation", "AR-V7 negative"],
            "prior_treatments": ["Enzalutamide", "Docetaxel", "Olaparib"],
            "lines_of_therapy": 3,
            "age": 68,
            "sex": "male",
            "ecog_score": 1,
            "key_labs": {"psa": 45.2, "wbc": 5.0, "hemoglobin": 10.8},
            "location_zip": "02115",
            "willing_to_travel_miles": 100,
            "additional_conditions": ["Bone metastases"],
            "additional_notes": "Castration-resistant, progressed on olaparib",
        },
        "expected_good_criteria": {
            "diagnosis": "MET",
            "biomarker": "MET",
        },
    },
    # --- Patient 8: Young adult with Ewing sarcoma ---
    {
        "id": "eval_ewing",
        "label": "Ewing sarcoma, 19yo, relapsed",
        "profile": {
            "cancer_type": "Ewing Sarcoma",
            "cancer_stage": "Recurrent",
            "biomarkers": ["EWSR1-FLI1 fusion"],
            "prior_treatments": ["VDC/IE"],
            "lines_of_therapy": 1,
            "age": 19,
            "sex": "female",
            "ecog_score": 1,
            "key_labs": None,
            "location_zip": "55455",
            "willing_to_travel_miles": 500,
            "additional_conditions": [],
            "additional_notes": "Relapsed 6 months after completing treatment",
        },
        "expected_good_criteria": {
            "diagnosis": "MET",
            "demographic": "MET",
        },
    },
    # --- Patient 9: SCLC, limited stage ---
    {
        "id": "eval_sclc",
        "label": "SCLC limited stage",
        "profile": {
            "cancer_type": "Small Cell Lung Cancer",
            "cancer_stage": "Limited Stage",
            "biomarkers": [],
            "prior_treatments": [],
            "lines_of_therapy": 0,
            "age": 72,
            "sex": "male",
            "ecog_score": 1,
            "key_labs": {"wbc": 8.5, "platelets": 300},
            "location_zip": "37232",
            "willing_to_travel_miles": 100,
            "additional_conditions": ["COPD", "Former smoker"],
            "additional_notes": "Newly diagnosed, treatment-naive",
        },
        "expected_good_criteria": {
            "diagnosis": "MET",
            "demographic": "MET",
        },
    },
    # --- Patient 10: GBM, poor prognosis ---
    {
        "id": "eval_gbm",
        "label": "Glioblastoma, MGMT unmethylated",
        "profile": {
            "cancer_type": "Glioblastoma",
            "cancer_stage": "Recurrent",
            "biomarkers": ["MGMT unmethylated", "IDH wild-type"],
            "prior_treatments": ["Temozolomide + Radiation", "Bevacizumab"],
            "lines_of_therapy": 2,
            "age": 55,
            "sex": "male",
            "ecog_score": 2,
            "key_labs": None,
            "location_zip": "21287",
            "willing_to_travel_miles": 200,
            "additional_conditions": ["Seizure disorder (controlled)"],
            "additional_notes": "Recurrent GBM after standard treatment",
        },
        "expected_good_criteria": {
            "diagnosis": "MET",
            "stage": "MET",
        },
    },
]
