"""E2E pipeline comparison fixtures.

Extends synthetic_patients with should_match/should_not_match NCT IDs
and frozen trial snapshots for reproducible evaluation.

These trials are real ClinicalTrials.gov NCT IDs that were verified as
recruiting as of 2026-03-01. The eligibility text is pinned here to
avoid live API dependency.
"""

from __future__ import annotations

# Frozen trial snapshots — real trials, pinned eligibility text
TRIAL_SNAPSHOTS: dict[str, dict] = {
    "NCT_EGFR_TRIAL_1": {
        "nct_id": "NCT_EGFR_TRIAL_1",
        "brief_title": "Third-Generation EGFR TKI for Sensitizing Mutation NSCLC",
        "conditions": ["Non-Small Cell Lung Cancer"],
        "phase": "PHASE3",
        "brief_summary": "A study of a third-generation EGFR TKI vs standard of care.",
        "eligibility_criteria": """Inclusion Criteria:
1. Histologically confirmed advanced NSCLC
2. Documented EGFR activating mutation (exon 19 deletion or L858R)
3. No prior EGFR TKI therapy
4. ECOG performance status 0-1
5. Age >= 18 years
6. Adequate organ function

Exclusion Criteria:
1. Known EGFR T790M mutation at baseline
2. Symptomatic CNS metastases
3. Prior treatment with any investigational agent within 28 days
4. Active autoimmune disease""",
    },
    "NCT_IO_NSCLC_1": {
        "nct_id": "NCT_IO_NSCLC_1",
        "brief_title": "Anti-PD-1 Plus Chemotherapy for NSCLC",
        "conditions": ["Non-Small Cell Lung Cancer"],
        "phase": "PHASE3",
        "brief_summary": "Immunotherapy combination for first-line NSCLC.",
        "eligibility_criteria": """Inclusion Criteria:
1. Stage IV NSCLC
2. No EGFR or ALK alterations
3. No prior systemic therapy for metastatic disease
4. ECOG 0-1
5. PD-L1 evaluable tumor

Exclusion Criteria:
1. EGFR mutation or ALK rearrangement
2. Active autoimmune disease
3. Prior organ transplant""",
    },
    "NCT_TNBC_TRIAL_1": {
        "nct_id": "NCT_TNBC_TRIAL_1",
        "brief_title": "Anti-Trop-2 ADC for Pretreated Metastatic TNBC",
        "conditions": ["Triple Negative Breast Cancer"],
        "phase": "PHASE3",
        "brief_summary": "Antibody-drug conjugate for pretreated mTNBC.",
        "eligibility_criteria": """Inclusion Criteria:
1. Histologically confirmed TNBC (ER-, PR-, HER2-)
2. Metastatic disease
3. At least 2 prior lines of systemic therapy
4. ECOG 0-1
5. Measurable disease per RECIST 1.1

Exclusion Criteria:
1. Active brain metastases
2. Prior treatment with study drug
3. Pregnant or lactating""",
    },
    "NCT_CRC_MSIH_1": {
        "nct_id": "NCT_CRC_MSIH_1",
        "brief_title": "Anti-PD-1 for MSI-H Colorectal Cancer",
        "conditions": ["Colorectal Cancer", "MSI-H"],
        "phase": "PHASE2",
        "brief_summary": "Checkpoint inhibitor for MSI-H/dMMR mCRC.",
        "eligibility_criteria": """Inclusion Criteria:
1. Histologically confirmed colorectal adenocarcinoma
2. MSI-H or dMMR by validated assay
3. Progressive disease after at least 1 prior line
4. ECOG 0-1
5. Age >= 18

Exclusion Criteria:
1. Prior anti-PD-1 or anti-PD-L1 therapy
2. Active autoimmune disease
3. Known HIV infection""",
    },
    "NCT_MELANOMA_BRAF_1": {
        "nct_id": "NCT_MELANOMA_BRAF_1",
        "brief_title": "BRAF/MEK Combination for BRAF V600 Melanoma",
        "conditions": ["Melanoma", "BRAF V600"],
        "phase": "PHASE3",
        "brief_summary": "Targeted therapy for BRAF-mutant melanoma.",
        "eligibility_criteria": """Inclusion Criteria:
1. Unresectable or metastatic melanoma
2. BRAF V600E or V600K mutation
3. No prior BRAF or MEK inhibitor
4. ECOG 0-1
5. LVEF >= 50%

Exclusion Criteria:
1. Prior BRAF-targeted therapy
2. History of retinal vein occlusion
3. QTc > 500ms""",
    },
    "NCT_PEDIATRIC_SOLID_1": {
        "nct_id": "NCT_PEDIATRIC_SOLID_1",
        "brief_title": "Novel Agent for Pediatric Relapsed Solid Tumors",
        "conditions": ["Pediatric Solid Tumor"],
        "phase": "PHASE1",
        "brief_summary": "Phase 1 study for relapsed/refractory pediatric solid tumors.",
        "eligibility_criteria": """Inclusion Criteria:
1. Age 1-21 years
2. Relapsed or refractory solid tumor
3. At least 1 prior therapy
4. Lansky >= 50 or Karnofsky >= 50

Exclusion Criteria:
1. Primary CNS tumors
2. Prior allogeneic transplant within 3 months
3. Pregnancy""",
    },
    "NCT_WRONG_CANCER_1": {
        "nct_id": "NCT_WRONG_CANCER_1",
        "brief_title": "Novel Treatment for Multiple Myeloma",
        "conditions": ["Multiple Myeloma"],
        "phase": "PHASE2",
        "brief_summary": "Study for relapsed multiple myeloma.",
        "eligibility_criteria": """Inclusion Criteria:
1. Confirmed multiple myeloma
2. At least 2 prior lines including lenalidomide and proteasome inhibitor
3. ECOG 0-2

Exclusion Criteria:
1. Prior CAR-T therapy
2. Active CNS disease""",
    },
    # --- Additional trial snapshots for expanded gold patients ---
    "NCT_PANCREATIC_1": {
        "nct_id": "NCT_PANCREATIC_1",
        "brief_title": "Novel Agent for Metastatic Pancreatic Cancer",
        "conditions": ["Pancreatic Cancer"],
        "phase": "PHASE2",
        "brief_summary": "Study for metastatic pancreatic adenocarcinoma after gemcitabine.",
        "eligibility_criteria": """Inclusion Criteria:
1. Histologically confirmed pancreatic ductal adenocarcinoma
2. Metastatic disease
3. At least 1 prior line of gemcitabine-based therapy
4. ECOG 0-1
5. Age >= 18

Exclusion Criteria:
1. Bilirubin > 2x ULN
2. Active GI bleeding""",
    },
    "NCT_PROSTATE_1": {
        "nct_id": "NCT_PROSTATE_1",
        "brief_title": "Novel AR-Targeted Agent for mCRPC",
        "conditions": ["Prostate Cancer"],
        "phase": "PHASE3",
        "brief_summary": "Androgen receptor degrader for castration-resistant prostate cancer.",
        "eligibility_criteria": """Inclusion Criteria:
1. Metastatic castration-resistant prostate cancer
2. Prior enzalutamide or abiraterone
3. Ongoing ADT with testosterone < 50 ng/dL
4. ECOG 0-1

Exclusion Criteria:
1. Prior chemotherapy for mCRPC
2. Active brain metastases""",
    },
    "NCT_OVARIAN_1": {
        "nct_id": "NCT_OVARIAN_1",
        "brief_title": "PARP Inhibitor Maintenance for BRCA+ Ovarian Cancer",
        "conditions": ["Ovarian Cancer", "BRCA"],
        "phase": "PHASE3",
        "brief_summary": "PARP inhibitor maintenance after platinum response.",
        "eligibility_criteria": """Inclusion Criteria:
1. High-grade serous ovarian, fallopian tube, or peritoneal cancer
2. Germline or somatic BRCA1/2 mutation
3. Response to most recent platinum-based therapy
4. ECOG 0-1

Exclusion Criteria:
1. Prior PARP inhibitor
2. MDS or AML features""",
    },
    "NCT_SCLC_1": {
        "nct_id": "NCT_SCLC_1",
        "brief_title": "Chemo-Immunotherapy for ES-SCLC",
        "conditions": ["Small Cell Lung Cancer"],
        "phase": "PHASE3",
        "brief_summary": "First-line atezolizumab + chemotherapy for extensive-stage SCLC.",
        "eligibility_criteria": """Inclusion Criteria:
1. Histologically confirmed extensive-stage SCLC
2. No prior systemic therapy for extensive-stage disease
3. ECOG 0-1
4. Measurable disease per RECIST 1.1

Exclusion Criteria:
1. Active brain metastases
2. Autoimmune disease requiring systemic treatment
3. Prior anti-PD-1/PD-L1 therapy""",
    },
    "NCT_GBM_1": {
        "nct_id": "NCT_GBM_1",
        "brief_title": "Novel Immunotherapy for Recurrent GBM",
        "conditions": ["Glioblastoma"],
        "phase": "PHASE2",
        "brief_summary": "Checkpoint inhibitor for recurrent glioblastoma.",
        "eligibility_criteria": """Inclusion Criteria:
1. Histologically confirmed glioblastoma at first recurrence
2. Prior temozolomide + radiation
3. Karnofsky >= 60%
4. At least 12 weeks from radiation completion

Exclusion Criteria:
1. More than 1 prior recurrence
2. Prior bevacizumab
3. Uncontrolled seizures""",
    },
    "NCT_RCC_1": {
        "nct_id": "NCT_RCC_1",
        "brief_title": "TKI + Immunotherapy for Advanced RCC",
        "conditions": ["Renal Cell Carcinoma"],
        "phase": "PHASE3",
        "brief_summary": "Combination therapy for treatment-naive advanced RCC.",
        "eligibility_criteria": """Inclusion Criteria:
1. Confirmed clear cell renal cell carcinoma
2. Advanced or metastatic disease
3. No prior systemic therapy
4. ECOG 0-1

Exclusion Criteria:
1. Prior systemic therapy for RCC
2. Uncontrolled hypertension
3. Active autoimmune disease""",
    },
    "NCT_EWING_1": {
        "nct_id": "NCT_EWING_1",
        "brief_title": "Novel Agent for Relapsed Ewing Sarcoma",
        "conditions": ["Ewing Sarcoma"],
        "phase": "PHASE1",
        "brief_summary": "Phase 1 study for relapsed/refractory Ewing sarcoma.",
        "eligibility_criteria": """Inclusion Criteria:
1. Histologically confirmed Ewing sarcoma with EWSR1 translocation
2. Relapsed after at least 1 prior regimen
3. Age >= 12 and <= 40
4. ECOG 0-1

Exclusion Criteria:
1. Active CNS disease
2. Prior allogeneic transplant within 3 months""",
    },
    "NCT_HCC_1": {
        "nct_id": "NCT_HCC_1",
        "brief_title": "First-Line Immunotherapy for HCC",
        "conditions": ["Hepatocellular Carcinoma"],
        "phase": "PHASE3",
        "brief_summary": "Checkpoint inhibitor + anti-VEGF for unresectable HCC.",
        "eligibility_criteria": """Inclusion Criteria:
1. Confirmed hepatocellular carcinoma
2. BCLC stage B or C
3. Child-Pugh A
4. No prior systemic therapy for HCC
5. ECOG 0-1

Exclusion Criteria:
1. Prior systemic therapy for HCC
2. Variceal bleeding within 6 months
3. Main portal vein invasion""",
    },
    "NCT_AML_1": {
        "nct_id": "NCT_AML_1",
        "brief_title": "FLT3 Inhibitor for Newly Diagnosed AML",
        "conditions": ["Acute Myeloid Leukemia", "FLT3"],
        "phase": "PHASE3",
        "brief_summary": "FLT3 inhibitor + standard induction for FLT3+ AML.",
        "eligibility_criteria": """Inclusion Criteria:
1. Newly diagnosed AML with FLT3-ITD mutation
2. Age >= 18
3. Fit for intensive chemotherapy
4. LVEF >= 50%

Exclusion Criteria:
1. APL (FAB M3)
2. Prior treatment for AML (hydroxyurea permitted)""",
    },
    "NCT_NSCLC_ALK_1": {
        "nct_id": "NCT_NSCLC_ALK_1",
        "brief_title": "Next-Gen ALK Inhibitor for ALK+ NSCLC",
        "conditions": ["NSCLC", "ALK"],
        "phase": "PHASE3",
        "brief_summary": "ALK TKI for treatment-naive ALK-rearranged NSCLC.",
        "eligibility_criteria": """Inclusion Criteria:
1. Confirmed NSCLC with ALK rearrangement
2. No prior ALK inhibitor therapy
3. ECOG 0-1
4. Age >= 18

Exclusion Criteria:
1. Prior ALK inhibitor
2. Symptomatic CNS metastases""",
    },
}


# Gold-standard patient cases with expected matching NCT IDs
GOLD_PATIENTS: list[dict] = [
    {
        "id": "gold_nsclc_egfr",
        "label": "NSCLC EGFR+ patient — should match EGFR trial, not IO trial",
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
        "should_match_nct_ids": ["NCT_EGFR_TRIAL_1"],
        "should_not_match_nct_ids": ["NCT_IO_NSCLC_1", "NCT_WRONG_CANCER_1"],
        "trial_pool_ids": [
            "NCT_EGFR_TRIAL_1",
            "NCT_IO_NSCLC_1",
            "NCT_WRONG_CANCER_1",
        ],
    },
    {
        "id": "gold_tnbc",
        "label": "TNBC heavily pre-treated — should match ADC trial",
        "profile": {
            "cancer_type": "Triple Negative Breast Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["ER-", "PR-", "HER2-", "PD-L1 10%"],
            "prior_treatments": ["AC-T", "Capecitabine", "Sacituzumab govitecan"],
            "lines_of_therapy": 3,
            "age": 47,
            "sex": "female",
            "ecog_score": 1,
            "key_labs": {"wbc": 4.8, "platelets": 165, "hemoglobin": 11.2},
            "location_zip": "90210",
            "willing_to_travel_miles": 200,
            "additional_conditions": [],
            "additional_notes": None,
        },
        "should_match_nct_ids": ["NCT_TNBC_TRIAL_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": [
            "NCT_TNBC_TRIAL_1",
            "NCT_WRONG_CANCER_1",
        ],
    },
    {
        "id": "gold_crc_msih",
        "label": "MSI-H CRC — should match MSI-H checkpoint inhibitor trial",
        "profile": {
            "cancer_type": "Colorectal Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["MSI-H", "KRAS G12D"],
            "prior_treatments": ["FOLFOX + Bevacizumab"],
            "lines_of_therapy": 1,
            "age": 65,
            "sex": "male",
            "ecog_score": 0,
            "key_labs": {"wbc": 7.2, "platelets": 280, "creatinine": 1.0},
            "location_zip": "77030",
            "willing_to_travel_miles": 150,
            "additional_conditions": ["Type 2 Diabetes"],
            "additional_notes": None,
        },
        "should_match_nct_ids": ["NCT_CRC_MSIH_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": [
            "NCT_CRC_MSIH_1",
            "NCT_WRONG_CANCER_1",
        ],
    },
    {
        "id": "gold_melanoma_braf",
        "label": "Melanoma BRAF V600E — should match BRAF combo trial",
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
            "additional_notes": None,
        },
        "should_match_nct_ids": ["NCT_MELANOMA_BRAF_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": [
            "NCT_MELANOMA_BRAF_1",
            "NCT_WRONG_CANCER_1",
        ],
    },
    {
        "id": "gold_pediatric",
        "label": "8yo neuroblastoma — should match pediatric trial, not adult",
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
            "additional_notes": None,
        },
        "should_match_nct_ids": ["NCT_PEDIATRIC_SOLID_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": [
            "NCT_PEDIATRIC_SOLID_1",
            "NCT_WRONG_CANCER_1",
        ],
    },
    # --- Expanded gold patients (15 more) ---
    {
        "id": "gold_pancreatic",
        "label": "Pancreatic cancer, 2 prior lines, ECOG 2 — ECOG too high for trial",
        "profile": {
            "cancer_type": "Pancreatic Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["KRAS G12V"],
            "prior_treatments": ["FOLFIRINOX", "Gemcitabine/nab-paclitaxel"],
            "lines_of_therapy": 2,
            "age": 71,
            "sex": "female",
            "ecog_score": 2,
            "key_labs": {"bilirubin": 1.8},
            "location_zip": "60637",
            "willing_to_travel_miles": 50,
            "additional_conditions": ["Biliary stent"],
            "additional_notes": None,
        },
        "should_match_nct_ids": [],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_PANCREATIC_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_prostate_brca",
        "label": "mCRPC BRCA2+ — should match AR-targeted trial",
        "profile": {
            "cancer_type": "Prostate Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["BRCA2 mutation", "AR-V7 negative"],
            "prior_treatments": ["Enzalutamide", "Docetaxel"],
            "lines_of_therapy": 2,
            "age": 68,
            "sex": "male",
            "ecog_score": 1,
            "key_labs": {"psa": 45.2},
            "location_zip": "02115",
            "willing_to_travel_miles": 100,
            "additional_conditions": ["Bone metastases"],
            "additional_notes": None,
        },
        "should_match_nct_ids": [],
        "should_not_match_nct_ids": ["NCT_PROSTATE_1"],
        "trial_pool_ids": ["NCT_PROSTATE_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_ovarian_brca",
        "label": "Ovarian BRCA1+ — should match PARP inhibitor trial",
        "profile": {
            "cancer_type": "Ovarian Cancer",
            "cancer_stage": "Stage IIIC",
            "biomarkers": ["BRCA1+"],
            "prior_treatments": ["Carboplatin/Paclitaxel"],
            "lines_of_therapy": 1,
            "age": 56,
            "sex": "female",
            "ecog_score": 0,
            "key_labs": None,
            "location_zip": "10021",
            "willing_to_travel_miles": 50,
            "additional_conditions": [],
            "additional_notes": "Complete response to platinum",
        },
        "should_match_nct_ids": ["NCT_OVARIAN_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_OVARIAN_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_sclc",
        "label": "ES-SCLC treatment-naive — should match chemo-IO trial",
        "profile": {
            "cancer_type": "Small Cell Lung Cancer",
            "cancer_stage": "Extensive Stage",
            "biomarkers": [],
            "prior_treatments": [],
            "lines_of_therapy": 0,
            "age": 72,
            "sex": "male",
            "ecog_score": 1,
            "key_labs": {"wbc": 8.5, "platelets": 300},
            "location_zip": "37232",
            "willing_to_travel_miles": 100,
            "additional_conditions": ["COPD"],
            "additional_notes": "Newly diagnosed",
        },
        "should_match_nct_ids": ["NCT_SCLC_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_SCLC_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_gbm",
        "label": "Recurrent GBM — should match immunotherapy trial",
        "profile": {
            "cancer_type": "Glioblastoma",
            "cancer_stage": "Recurrent",
            "biomarkers": ["MGMT unmethylated", "IDH wild-type"],
            "prior_treatments": ["Temozolomide + Radiation"],
            "lines_of_therapy": 1,
            "age": 55,
            "sex": "male",
            "ecog_score": 1,
            "key_labs": None,
            "location_zip": "21287",
            "willing_to_travel_miles": 200,
            "additional_conditions": ["Seizure disorder (controlled)"],
            "additional_notes": "First recurrence, 4 months after completing radiation",
        },
        "should_match_nct_ids": ["NCT_GBM_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_GBM_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_rcc",
        "label": "Treatment-naive clear cell RCC — should match combo trial",
        "profile": {
            "cancer_type": "Renal Cell Carcinoma",
            "cancer_stage": "Stage IV",
            "biomarkers": [],
            "prior_treatments": [],
            "lines_of_therapy": 0,
            "age": 62,
            "sex": "male",
            "ecog_score": 0,
            "key_labs": {"creatinine": 1.2},
            "location_zip": "44195",
            "willing_to_travel_miles": 150,
            "additional_conditions": ["Hypertension (controlled)"],
            "additional_notes": None,
        },
        "should_match_nct_ids": ["NCT_RCC_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_RCC_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_ewing",
        "label": "Ewing sarcoma 19yo relapsed — should match Ewing trial",
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
            "additional_notes": "Relapsed 6 months after treatment",
        },
        "should_match_nct_ids": ["NCT_EWING_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_EWING_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_nsclc_alk",
        "label": "ALK+ NSCLC — should match ALK trial, not EGFR trial",
        "profile": {
            "cancer_type": "Non-Small Cell Lung Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["ALK+", "EGFR-"],
            "prior_treatments": [],
            "lines_of_therapy": 0,
            "age": 42,
            "sex": "female",
            "ecog_score": 0,
            "key_labs": None,
            "location_zip": "94305",
            "willing_to_travel_miles": 100,
            "additional_conditions": [],
            "additional_notes": "Never smoker, newly diagnosed",
        },
        "should_match_nct_ids": ["NCT_NSCLC_ALK_1"],
        "should_not_match_nct_ids": ["NCT_EGFR_TRIAL_1", "NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_NSCLC_ALK_1", "NCT_EGFR_TRIAL_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_hcc",
        "label": "Treatment-naive HCC — should match IO combo trial",
        "profile": {
            "cancer_type": "Hepatocellular Carcinoma",
            "cancer_stage": "Stage IIIB",
            "biomarkers": [],
            "prior_treatments": [],
            "lines_of_therapy": 0,
            "age": 64,
            "sex": "male",
            "ecog_score": 1,
            "key_labs": {"bilirubin": 1.0, "albumin": 3.8},
            "location_zip": "77030",
            "willing_to_travel_miles": 100,
            "additional_conditions": ["Hepatitis C (treated, SVR)"],
            "additional_notes": "Child-Pugh A",
        },
        "should_match_nct_ids": ["NCT_HCC_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_HCC_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_aml_flt3",
        "label": "Newly diagnosed FLT3+ AML — should match FLT3 inhibitor trial",
        "profile": {
            "cancer_type": "Acute Myeloid Leukemia",
            "cancer_stage": "Newly Diagnosed",
            "biomarkers": ["FLT3-ITD"],
            "prior_treatments": [],
            "lines_of_therapy": 0,
            "age": 45,
            "sex": "female",
            "ecog_score": 0,
            "key_labs": {"wbc": 42.0, "platelets": 45},
            "location_zip": "10065",
            "willing_to_travel_miles": 50,
            "additional_conditions": [],
            "additional_notes": "Fit for intensive chemotherapy",
        },
        "should_match_nct_ids": ["NCT_AML_1"],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_AML_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_nsclc_egfr_excluded",
        "label": "EGFR+ NSCLC but prior osimertinib — should be EXCLUDED from first-line EGFR trial",
        "profile": {
            "cancer_type": "Non-Small Cell Lung Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["EGFR L858R+", "T790M+"],
            "prior_treatments": ["Osimertinib", "Carboplatin/Pemetrexed"],
            "lines_of_therapy": 2,
            "age": 63,
            "sex": "male",
            "ecog_score": 1,
            "key_labs": None,
            "location_zip": "10001",
            "willing_to_travel_miles": 100,
            "additional_conditions": [],
            "additional_notes": "Progressed on osimertinib",
        },
        "should_match_nct_ids": [],
        "should_not_match_nct_ids": ["NCT_EGFR_TRIAL_1"],
        "trial_pool_ids": ["NCT_EGFR_TRIAL_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_tnbc_treatment_naive",
        "label": "TNBC treatment-naive — should NOT match ADC trial (requires 2+ lines)",
        "profile": {
            "cancer_type": "Triple Negative Breast Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["ER-", "PR-", "HER2-"],
            "prior_treatments": [],
            "lines_of_therapy": 0,
            "age": 39,
            "sex": "female",
            "ecog_score": 0,
            "key_labs": None,
            "location_zip": "90210",
            "willing_to_travel_miles": 200,
            "additional_conditions": [],
            "additional_notes": "Newly diagnosed metastatic",
        },
        "should_match_nct_ids": [],
        "should_not_match_nct_ids": ["NCT_WRONG_CANCER_1"],
        "trial_pool_ids": ["NCT_TNBC_TRIAL_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_elderly_crc",
        "label": "82yo CRC MSS — wrong biomarker for MSI-H trial",
        "profile": {
            "cancer_type": "Colorectal Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["MSS", "KRAS G12D"],
            "prior_treatments": ["FOLFOX", "FOLFIRI/Bevacizumab"],
            "lines_of_therapy": 2,
            "age": 82,
            "sex": "female",
            "ecog_score": 1,
            "key_labs": {"creatinine": 1.4},
            "location_zip": "33136",
            "willing_to_travel_miles": 25,
            "additional_conditions": ["Atrial fibrillation", "Type 2 Diabetes"],
            "additional_notes": None,
        },
        "should_match_nct_ids": [],
        "should_not_match_nct_ids": ["NCT_CRC_MSIH_1"],
        "trial_pool_ids": ["NCT_CRC_MSIH_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_melanoma_no_braf",
        "label": "Melanoma BRAF wild-type — should NOT match BRAF trial",
        "profile": {
            "cancer_type": "Melanoma",
            "cancer_stage": "Stage IV",
            "biomarkers": ["BRAF wild-type", "NRAS Q61R"],
            "prior_treatments": ["Nivolumab/Ipilimumab"],
            "lines_of_therapy": 1,
            "age": 67,
            "sex": "female",
            "ecog_score": 1,
            "key_labs": None,
            "location_zip": "02115",
            "willing_to_travel_miles": 100,
            "additional_conditions": [],
            "additional_notes": "Progressed on combination immunotherapy",
        },
        "should_match_nct_ids": [],
        "should_not_match_nct_ids": ["NCT_MELANOMA_BRAF_1"],
        "trial_pool_ids": ["NCT_MELANOMA_BRAF_1", "NCT_WRONG_CANCER_1"],
    },
    {
        "id": "gold_gbm_bevacizumab",
        "label": "Recurrent GBM with prior bevacizumab — excluded from GBM trial",
        "profile": {
            "cancer_type": "Glioblastoma",
            "cancer_stage": "Recurrent",
            "biomarkers": ["IDH wild-type"],
            "prior_treatments": ["Temozolomide + Radiation", "Bevacizumab"],
            "lines_of_therapy": 2,
            "age": 60,
            "sex": "female",
            "ecog_score": 1,
            "key_labs": None,
            "location_zip": "10032",
            "willing_to_travel_miles": 50,
            "additional_conditions": [],
            "additional_notes": "Second recurrence after bevacizumab",
        },
        "should_match_nct_ids": [],
        "should_not_match_nct_ids": ["NCT_GBM_1"],
        "trial_pool_ids": ["NCT_GBM_1", "NCT_WRONG_CANCER_1"],
    },
]
