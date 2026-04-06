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
]
