"""Head-to-head Gemma vs Claude on Stage 5 — criterion evaluation fixtures.

Each fixture is a (criterion_text, patient_snippet, expected_status) tuple
with a difficulty category. Used to compare Gemma and Claude accuracy on
the same eligibility reasoning task.

Difficulty categories:
  - simple: straightforward, single-fact check
  - multi_step: requires combining multiple patient facts
  - drug_knowledge: requires knowing drug mechanisms/classes
  - temporal: involves time-based reasoning (washout, duration)
  - negation: "no history of", "must not have" — tests polarity handling
"""

from __future__ import annotations

CRITERION_FIXTURES: list[dict] = [
    # =====================================================================
    # SIMPLE — straightforward single-fact checks
    # =====================================================================
    {
        "id": "simple_age_met",
        "category": "simple",
        "criterion_text": "Age >= 18 years",
        "criterion_type": "inclusion",
        "patient_snippet": {"age": 58, "sex": "female"},
        "expected_status": "MET",
    },
    {
        "id": "simple_age_not_met",
        "category": "simple",
        "criterion_text": "Age >= 18 years",
        "criterion_type": "inclusion",
        "patient_snippet": {"age": 8, "sex": "male"},
        "expected_status": "NOT_MET",
    },
    {
        "id": "simple_ecog_met",
        "category": "simple",
        "criterion_text": "ECOG performance status 0-1",
        "criterion_type": "inclusion",
        "patient_snippet": {"ecog_score": 1},
        "expected_status": "MET",
    },
    {
        "id": "simple_ecog_not_met",
        "category": "simple",
        "criterion_text": "ECOG performance status 0-1",
        "criterion_type": "inclusion",
        "patient_snippet": {"ecog_score": 2},
        "expected_status": "NOT_MET",
    },
    {
        "id": "simple_sex_met",
        "category": "simple",
        "criterion_text": "Female patients only",
        "criterion_type": "inclusion",
        "patient_snippet": {"sex": "female"},
        "expected_status": "MET",
    },
    {
        "id": "simple_diagnosis_met",
        "category": "simple",
        "criterion_text": "Histologically confirmed non-small cell lung cancer",
        "criterion_type": "inclusion",
        "patient_snippet": {"cancer_type": "Non-Small Cell Lung Cancer"},
        "expected_status": "MET",
    },
    {
        "id": "simple_diagnosis_not_met",
        "category": "simple",
        "criterion_text": "Histologically confirmed non-small cell lung cancer",
        "criterion_type": "inclusion",
        "patient_snippet": {"cancer_type": "Triple Negative Breast Cancer"},
        "expected_status": "NOT_MET",
    },
    {
        "id": "simple_stage_met",
        "category": "simple",
        "criterion_text": "Stage IIIB or Stage IV disease",
        "criterion_type": "inclusion",
        "patient_snippet": {"cancer_stage": "Stage IV"},
        "expected_status": "MET",
    },
    {
        "id": "simple_biomarker_met",
        "category": "simple",
        "criterion_text": "Documented EGFR activating mutation",
        "criterion_type": "inclusion",
        "patient_snippet": {"biomarkers": ["EGFR L858R+"]},
        "expected_status": "MET",
    },
    {
        "id": "simple_biomarker_not_met",
        "category": "simple",
        "criterion_text": "BRAF V600E mutation confirmed",
        "criterion_type": "inclusion",
        "patient_snippet": {"biomarkers": ["EGFR L858R+", "ALK-"]},
        "expected_status": "NOT_MET",
    },
    # =====================================================================
    # MULTI-STEP — requires combining multiple patient facts
    # =====================================================================
    {
        "id": "multi_prior_therapy_exception",
        "category": "multi_step",
        "criterion_text": "Prior immunotherapy unless discontinued for toxicity more than 6 months ago",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "prior_treatments": ["Pembrolizumab"],
            "additional_notes": "Stopped pembrolizumab 3 months ago due to immune-related pneumonitis",
        },
        "expected_status": "TRIGGERED",
    },
    {
        "id": "multi_prior_therapy_exception_clear",
        "category": "multi_step",
        "criterion_text": "Prior immunotherapy unless discontinued for toxicity more than 6 months ago",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "prior_treatments": ["Pembrolizumab"],
            "additional_notes": "Stopped pembrolizumab 8 months ago due to immune-related pneumonitis",
        },
        "expected_status": "NOT_TRIGGERED",
    },
    {
        "id": "multi_lines_and_biomarker",
        "category": "multi_step",
        "criterion_text": "At least 2 prior lines of therapy including a platinum-based regimen",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "prior_treatments": ["Carboplatin/Pemetrexed", "Docetaxel"],
            "lines_of_therapy": 2,
        },
        "expected_status": "MET",
    },
    {
        "id": "multi_lines_no_platinum",
        "category": "multi_step",
        "criterion_text": "At least 2 prior lines of therapy including a platinum-based regimen",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "prior_treatments": ["Pembrolizumab", "Docetaxel"],
            "lines_of_therapy": 2,
        },
        "expected_status": "NOT_MET",
    },
    {
        "id": "multi_biomarker_and_stage",
        "category": "multi_step",
        "criterion_text": "EGFR mutation-positive Stage IV NSCLC with CNS metastases",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "cancer_type": "Non-Small Cell Lung Cancer",
            "cancer_stage": "Stage IV",
            "biomarkers": ["EGFR L858R+"],
            "additional_conditions": [],
        },
        # No CNS metastases mentioned
        "expected_status": "INSUFFICIENT_INFO",
    },
    # =====================================================================
    # DRUG KNOWLEDGE — requires knowing drug mechanisms/classes
    # =====================================================================
    {
        "id": "drug_osimertinib_is_egfr_tki",
        "category": "drug_knowledge",
        "criterion_text": "Prior treatment with a third-generation EGFR TKI",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "prior_treatments": ["Osimertinib"],
        },
        "expected_status": "TRIGGERED",
    },
    {
        "id": "drug_pembrolizumab_is_pd1",
        "category": "drug_knowledge",
        "criterion_text": "Prior anti-PD-1 or anti-PD-L1 therapy",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "prior_treatments": ["Pembrolizumab"],
        },
        "expected_status": "TRIGGERED",
    },
    {
        "id": "drug_olaparib_is_parp",
        "category": "drug_knowledge",
        "criterion_text": "Prior PARP inhibitor therapy",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "prior_treatments": ["Olaparib"],
        },
        "expected_status": "TRIGGERED",
    },
    {
        "id": "drug_bevacizumab_is_vegf",
        "category": "drug_knowledge",
        "criterion_text": "No prior anti-VEGF therapy",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "prior_treatments": ["FOLFOX/Bevacizumab"],
        },
        "expected_status": "TRIGGERED",
    },
    {
        "id": "drug_not_egfr_tki",
        "category": "drug_knowledge",
        "criterion_text": "Prior EGFR TKI therapy",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "prior_treatments": ["Carboplatin/Pemetrexed"],
        },
        "expected_status": "NOT_TRIGGERED",
    },
    {
        "id": "drug_dabrafenib_is_braf",
        "category": "drug_knowledge",
        "criterion_text": "Prior BRAF inhibitor therapy",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "prior_treatments": ["Dabrafenib/Trametinib"],
        },
        "expected_status": "TRIGGERED",
    },
    {
        "id": "drug_enzalutamide_is_hormonal",
        "category": "drug_knowledge",
        "criterion_text": "Prior novel hormonal agent (abiraterone, enzalutamide, or apalutamide)",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "prior_treatments": ["Enzalutamide"],
        },
        "expected_status": "MET",
    },
    # =====================================================================
    # TEMPORAL — time-based reasoning
    # =====================================================================
    {
        "id": "temporal_washout_met",
        "category": "temporal",
        "criterion_text": "At least 4 weeks since last systemic therapy",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "additional_notes": "Last dose of chemotherapy was 6 weeks ago",
        },
        "expected_status": "MET",
    },
    {
        "id": "temporal_washout_not_met",
        "category": "temporal",
        "criterion_text": "At least 4 weeks since last systemic therapy",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "additional_notes": "Completed last cycle of chemotherapy 2 weeks ago",
        },
        "expected_status": "NOT_MET",
    },
    {
        "id": "temporal_washout_unknown",
        "category": "temporal",
        "criterion_text": "At least 4 weeks since last systemic therapy",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "prior_treatments": ["Carboplatin/Pemetrexed"],
            # No date of last treatment
        },
        "expected_status": "INSUFFICIENT_INFO",
    },
    {
        "id": "temporal_radiation_washout",
        "category": "temporal",
        "criterion_text": "At least 12 weeks from completion of cranial radiation",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "additional_notes": "Completed whole brain radiation 4 weeks ago",
        },
        "expected_status": "NOT_MET",
    },
    {
        "id": "temporal_progression_within",
        "category": "temporal",
        "criterion_text": "Disease progression within 6 months of completing adjuvant therapy",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "additional_notes": "Completed adjuvant therapy, progressed 3 months later",
        },
        "expected_status": "MET",
    },
    # =====================================================================
    # NEGATION — "no history of", "must not have"
    # =====================================================================
    {
        "id": "negation_no_autoimmune_clear",
        "category": "negation",
        "criterion_text": "No history of autoimmune disease requiring systemic treatment",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "additional_conditions": [],
        },
        "expected_status": "NOT_TRIGGERED",
    },
    {
        "id": "negation_no_autoimmune_triggered",
        "category": "negation",
        "criterion_text": "No history of autoimmune disease requiring systemic treatment",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "additional_conditions": ["Rheumatoid arthritis (on methotrexate)"],
        },
        "expected_status": "TRIGGERED",
    },
    {
        "id": "negation_no_brain_mets_clear",
        "category": "negation",
        "criterion_text": "No active brain metastases (treated, stable brain metastases allowed)",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "additional_conditions": ["Brain metastases (treated, stable, off steroids for 4 weeks)"],
        },
        "expected_status": "NOT_TRIGGERED",
    },
    {
        "id": "negation_no_brain_mets_triggered",
        "category": "negation",
        "criterion_text": "No active brain metastases (treated, stable brain metastases allowed)",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "additional_conditions": ["New brain metastases diagnosed last week"],
        },
        "expected_status": "TRIGGERED",
    },
    {
        "id": "negation_no_prior_transplant",
        "category": "negation",
        "criterion_text": "No prior organ or allogeneic stem cell transplant",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "additional_conditions": [],
            "prior_treatments": ["Induction chemotherapy", "Autologous stem cell transplant"],
        },
        # Autologous != allogeneic
        "expected_status": "NOT_TRIGGERED",
    },
    {
        "id": "negation_no_hiv",
        "category": "negation",
        "criterion_text": "Known HIV-positive status",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "additional_conditions": [],
        },
        # Not mentioned = insufficient info (some trials require testing)
        "expected_status": "INSUFFICIENT_INFO",
    },
    # =====================================================================
    # More edge cases for each category to reach 50 fixtures
    # =====================================================================
    {
        "id": "simple_pdl1_high",
        "category": "simple",
        "criterion_text": "PD-L1 expression >= 50% by IHC",
        "criterion_type": "inclusion",
        "patient_snippet": {"biomarkers": ["PD-L1 80%"]},
        "expected_status": "MET",
    },
    {
        "id": "simple_pdl1_low",
        "category": "simple",
        "criterion_text": "PD-L1 expression >= 50% by IHC",
        "criterion_type": "inclusion",
        "patient_snippet": {"biomarkers": ["PD-L1 10%"]},
        "expected_status": "NOT_MET",
    },
    {
        "id": "simple_msih_met",
        "category": "simple",
        "criterion_text": "MSI-H or dMMR confirmed by validated assay",
        "criterion_type": "inclusion",
        "patient_snippet": {"biomarkers": ["MSI-H"]},
        "expected_status": "MET",
    },
    {
        "id": "multi_ecog_and_age",
        "category": "multi_step",
        "criterion_text": "ECOG 0-1 and age 18-75 years",
        "criterion_type": "inclusion",
        "patient_snippet": {"ecog_score": 0, "age": 52},
        "expected_status": "MET",
    },
    {
        "id": "multi_ecog_and_age_fail",
        "category": "multi_step",
        "criterion_text": "ECOG 0-1 and age 18-75 years",
        "criterion_type": "inclusion",
        "patient_snippet": {"ecog_score": 0, "age": 78},
        "expected_status": "NOT_MET",
    },
    {
        "id": "drug_trastuzumab_is_her2",
        "category": "drug_knowledge",
        "criterion_text": "Prior anti-HER2 therapy",
        "criterion_type": "inclusion",
        "patient_snippet": {"prior_treatments": ["Trastuzumab/Pertuzumab"]},
        "expected_status": "MET",
    },
    {
        "id": "drug_folfox_is_platinum",
        "category": "drug_knowledge",
        "criterion_text": "Prior platinum-based chemotherapy",
        "criterion_type": "inclusion",
        "patient_snippet": {"prior_treatments": ["FOLFOX"]},
        # FOLFOX contains oxaliplatin, a platinum agent
        "expected_status": "MET",
    },
    {
        "id": "drug_sotorasib_is_kras",
        "category": "drug_knowledge",
        "criterion_text": "Prior KRAS G12C inhibitor",
        "criterion_type": "exclusion",
        "patient_snippet": {"prior_treatments": ["Sotorasib"]},
        "expected_status": "TRIGGERED",
    },
    {
        "id": "temporal_vaccine_washout",
        "category": "temporal",
        "criterion_text": "Received a live vaccine within 30 days of planned first dose",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "additional_notes": "Received flu shot 2 weeks ago",
        },
        # Flu shot is typically inactivated, not live
        "expected_status": "NOT_TRIGGERED",
    },
    {
        "id": "negation_no_cardiac_clear",
        "category": "negation",
        "criterion_text": "No clinically significant cardiac disease within 6 months",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "additional_conditions": ["Hypertension (controlled)"],
        },
        # Controlled hypertension is not "clinically significant cardiac disease"
        "expected_status": "NOT_TRIGGERED",
    },
    {
        "id": "negation_no_cardiac_triggered",
        "category": "negation",
        "criterion_text": "No clinically significant cardiac disease within 6 months",
        "criterion_type": "exclusion",
        "patient_snippet": {
            "additional_conditions": ["Myocardial infarction 3 months ago"],
        },
        "expected_status": "TRIGGERED",
    },
    {
        "id": "simple_karnofsky_met",
        "category": "simple",
        "criterion_text": "Karnofsky Performance Status >= 70%",
        "criterion_type": "inclusion",
        "patient_snippet": {"ecog_score": 1},
        # ECOG 1 ≈ Karnofsky 70-80%
        "expected_status": "MET",
    },
    {
        "id": "multi_castration_resistant",
        "category": "multi_step",
        "criterion_text": "Metastatic castration-resistant prostate cancer with ongoing ADT and testosterone < 50 ng/dL",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "cancer_type": "Prostate Cancer",
            "cancer_stage": "Stage IV",
            "additional_notes": "Castration-resistant, on LHRH agonist",
        },
        # Testosterone level not provided
        "expected_status": "INSUFFICIENT_INFO",
    },
    {
        "id": "drug_crizotinib_is_alk",
        "category": "drug_knowledge",
        "criterion_text": "Prior ALK inhibitor therapy",
        "criterion_type": "exclusion",
        "patient_snippet": {"prior_treatments": ["Crizotinib"]},
        "expected_status": "TRIGGERED",
    },
    {
        "id": "negation_no_pregnancy_male",
        "category": "negation",
        "criterion_text": "Not pregnant or breastfeeding",
        "criterion_type": "exclusion",
        "patient_snippet": {"sex": "male", "age": 65},
        "expected_status": "NOT_TRIGGERED",
    },
    {
        "id": "simple_labs_unknown",
        "category": "simple",
        "criterion_text": "ANC >= 1500/uL",
        "criterion_type": "inclusion",
        "patient_snippet": {"key_labs": {"wbc": 6.0}},
        # WBC provided but not ANC specifically
        "expected_status": "INSUFFICIENT_INFO",
    },
    {
        "id": "temporal_surgery_washout",
        "category": "temporal",
        "criterion_text": "At least 28 days since major surgery with complete wound healing",
        "criterion_type": "inclusion",
        "patient_snippet": {
            "additional_notes": "Had tumor resection surgery 5 weeks ago, wound healed",
        },
        "expected_status": "MET",
    },
]

# Grouped by category for per-type accuracy reporting
FIXTURES_BY_CATEGORY = {}
for f in CRITERION_FIXTURES:
    cat = f["category"]
    FIXTURES_BY_CATEGORY.setdefault(cat, []).append(f)
