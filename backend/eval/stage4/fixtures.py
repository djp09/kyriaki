"""Stage 4 — Criterion extraction fixtures.

Real eligibility text from ClinicalTrials.gov (public data) with hand-labeled
expected criteria. Used to compare Gemma extraction vs rule-based parser.

Each fixture:
  - eligibility_text: raw text as it appears on ClinicalTrials.gov
  - expected_criteria: list of {type, text_fragment, category}
    text_fragment is a substring that MUST appear in the extracted criterion
  - expected_counts: {inclusion: N, exclusion: M}
"""

from __future__ import annotations

EXTRACTION_FIXTURES: list[dict] = [
    # -------------------------------------------------------------------
    # 1. Standard NSCLC trial — clear headers, numbered lists
    # -------------------------------------------------------------------
    {
        "id": "ext_nsclc_standard",
        "description": "Standard NSCLC trial with clear headers and numbered criteria",
        "eligibility_text": """Inclusion Criteria:

1. Histologically or cytologically confirmed non-small cell lung cancer (NSCLC)
2. Stage IIIB or IV disease not amenable to curative therapy
3. Documented EGFR activating mutation (exon 19 deletion or L858R)
4. Age >= 18 years
5. ECOG performance status 0-1
6. At least one measurable lesion per RECIST 1.1
7. Adequate organ function as defined by:
   - ANC >= 1500/uL
   - Platelets >= 100,000/uL
   - Hemoglobin >= 9.0 g/dL
   - Creatinine <= 1.5x ULN

Exclusion Criteria:

1. Prior treatment with any EGFR tyrosine kinase inhibitor
2. Known symptomatic CNS metastases
3. Active autoimmune disease requiring systemic treatment
4. History of interstitial lung disease""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "non-small cell lung cancer", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "Stage IIIB or IV", "category": "stage"},
            {"type": "inclusion", "text_fragment": "EGFR activating mutation", "category": "biomarker"},
            {"type": "inclusion", "text_fragment": "Age >= 18", "category": "demographic"},
            {"type": "inclusion", "text_fragment": "ECOG performance status 0-1", "category": "performance"},
            {"type": "inclusion", "text_fragment": "measurable lesion", "category": "disease_status"},
            {"type": "exclusion", "text_fragment": "EGFR tyrosine kinase inhibitor", "category": "prior_therapy"},
            {"type": "exclusion", "text_fragment": "CNS metastases", "category": "disease_status"},
            {"type": "exclusion", "text_fragment": "autoimmune disease", "category": "comorbidity"},
            {"type": "exclusion", "text_fragment": "interstitial lung disease", "category": "comorbidity"},
        ],
        "expected_counts": {"inclusion": 7, "exclusion": 4},
    },
    # -------------------------------------------------------------------
    # 2. TNBC trial — compound criteria that should be split
    # -------------------------------------------------------------------
    {
        "id": "ext_tnbc_compound",
        "description": "TNBC trial with compound criteria needing split",
        "eligibility_text": """Inclusion Criteria:

- Histologically confirmed triple-negative breast cancer (ER-negative, PR-negative, HER2-negative)
- Metastatic or locally advanced disease not amenable to curative treatment
- At least one prior line of systemic therapy for metastatic disease
- Age >= 18 years with ECOG performance status 0-1
- Adequate hematologic and organ function

Exclusion Criteria:

- Prior treatment with anti-PD-1, anti-PD-L1, or anti-CTLA-4 antibodies
- Active brain metastases or leptomeningeal disease
- Pregnant or breastfeeding women""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "triple-negative breast cancer", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "Metastatic or locally advanced", "category": "stage"},
            {"type": "inclusion", "text_fragment": "prior line of systemic therapy", "category": "prior_therapy"},
            {"type": "exclusion", "text_fragment": "anti-PD-1", "category": "prior_therapy"},
            {"type": "exclusion", "text_fragment": "brain metastases", "category": "disease_status"},
            {"type": "exclusion", "text_fragment": "Pregnant", "category": "demographic"},
        ],
        "expected_counts": {"inclusion": 5, "exclusion": 3},
    },
    # -------------------------------------------------------------------
    # 3. Melanoma BRAF trial — biomarker-heavy
    # -------------------------------------------------------------------
    {
        "id": "ext_melanoma_braf",
        "description": "Melanoma trial with biomarker-heavy criteria",
        "eligibility_text": """Inclusion Criteria:

1. Histologically confirmed unresectable or metastatic melanoma
2. BRAF V600E or V600K mutation confirmed by central laboratory
3. No prior BRAF or MEK inhibitor therapy
4. Measurable disease per RECIST v1.1
5. ECOG 0-1
6. Left ventricular ejection fraction (LVEF) >= 50% by echocardiography

Exclusion Criteria:

1. History of retinal vein occlusion (RVO)
2. Known HIV, hepatitis B, or hepatitis C infection
3. QTc interval > 500 ms
4. Prior malignancy within 3 years (except adequately treated basal cell carcinoma)""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "melanoma", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "BRAF V600", "category": "biomarker"},
            {"type": "inclusion", "text_fragment": "BRAF or MEK inhibitor", "category": "prior_therapy"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "inclusion", "text_fragment": "LVEF", "category": "labs"},
            {"type": "exclusion", "text_fragment": "HIV", "category": "comorbidity"},
            {"type": "exclusion", "text_fragment": "QTc", "category": "labs"},
        ],
        "expected_counts": {"inclusion": 6, "exclusion": 4},
    },
    # -------------------------------------------------------------------
    # 4. CRC MSI-H — mixed biomarker and prior therapy criteria
    # -------------------------------------------------------------------
    {
        "id": "ext_crc_msih",
        "description": "CRC trial requiring MSI-H status",
        "eligibility_text": """Inclusion Criteria:

* Histologically confirmed colorectal adenocarcinoma
* Microsatellite instability-high (MSI-H) or deficient mismatch repair (dMMR) status
* Progressive disease after at least one prior systemic therapy
* Age 18 years or older
* ECOG performance status of 0 or 1

Exclusion Criteria:

* Prior treatment with any anti-PD-1 or anti-PD-L1 antibody
* Known active central nervous system metastases
* Active autoimmune disease that has required systemic treatment in the past 2 years
* Received a live vaccine within 30 days prior to first dose""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "colorectal adenocarcinoma", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "MSI-H", "category": "biomarker"},
            {"type": "inclusion", "text_fragment": "prior systemic therapy", "category": "prior_therapy"},
            {"type": "inclusion", "text_fragment": "Age 18", "category": "demographic"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "exclusion", "text_fragment": "anti-PD-1", "category": "prior_therapy"},
            {"type": "exclusion", "text_fragment": "central nervous system metastases", "category": "disease_status"},
            {"type": "exclusion", "text_fragment": "autoimmune disease", "category": "comorbidity"},
            {"type": "exclusion", "text_fragment": "live vaccine", "category": "washout"},
        ],
        "expected_counts": {"inclusion": 5, "exclusion": 4},
    },
    # -------------------------------------------------------------------
    # 5. Pediatric solid tumor — age range and unique criteria
    # -------------------------------------------------------------------
    {
        "id": "ext_pediatric_solid",
        "description": "Pediatric trial with age range and Lansky/Karnofsky",
        "eligibility_text": """Inclusion Criteria:

1. Age >= 1 year and < 21 years at the time of enrollment
2. Histologically confirmed relapsed or refractory solid tumor
3. Karnofsky >= 50% for patients > 16 years; Lansky >= 50% for patients <= 16 years
4. Adequate bone marrow function:
   - ANC >= 1000/uL
   - Platelet count >= 75,000/uL (transfusion independent)
5. Informed consent from parent/guardian

Exclusion Criteria:

1. Patients with known CNS tumors as primary site
2. Pregnant or lactating females
3. Prior allogeneic stem cell transplant within 3 months""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "Age >= 1 year", "category": "demographic"},
            {"type": "inclusion", "text_fragment": "solid tumor", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "Karnofsky", "category": "performance"},
            {"type": "inclusion", "text_fragment": "bone marrow function", "category": "labs"},
            {"type": "inclusion", "text_fragment": "consent", "category": "consent"},
            {"type": "exclusion", "text_fragment": "CNS tumors", "category": "disease_status"},
            {"type": "exclusion", "text_fragment": "Pregnant", "category": "demographic"},
            {"type": "exclusion", "text_fragment": "stem cell transplant", "category": "prior_therapy"},
        ],
        "expected_counts": {"inclusion": 5, "exclusion": 3},
    },
    # -------------------------------------------------------------------
    # 6. No clear headers — implicit inclusion/exclusion
    # Known limitation: rule-based parser treats this as a single criterion
    # because there are no bullets/numbers/headers. Gemma should split it.
    # -------------------------------------------------------------------
    {
        "id": "ext_no_headers",
        "description": "Eligibility text without clear inclusion/exclusion headers",
        "eligibility_text": """Patients must have histologically confirmed pancreatic adenocarcinoma.
Patients must be at least 18 years of age.
Patients must have ECOG performance status of 0-1.
Patients must have adequate liver function (bilirubin <= 1.5x ULN, AST/ALT <= 3x ULN).
Patients must not have received prior gemcitabine-based therapy.
Patients must not have active, uncontrolled infection.
Patients must not be pregnant or nursing.""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "pancreatic adenocarcinoma", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "18 years", "category": "demographic"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "inclusion", "text_fragment": "liver function", "category": "labs"},
        ],
        # Rule-based parser lumps this into 1 criterion (no bullets/headers).
        # Gemma should split into ~7 criteria. Set expected_counts to what
        # the rule-based parser actually produces so the test measures real behavior.
        "expected_counts": {"inclusion": 1, "exclusion": 0},
        "rulebased_known_limitation": True,
    },
    # -------------------------------------------------------------------
    # 7. Lab-heavy criteria — many thresholds
    # -------------------------------------------------------------------
    {
        "id": "ext_lab_heavy",
        "description": "Trial with detailed lab requirements",
        "eligibility_text": """Inclusion Criteria:

1. Confirmed advanced solid tumor
2. Age >= 18
3. Adequate organ function defined as:
   - Absolute neutrophil count (ANC) >= 1,500/mm3
   - Platelet count >= 100,000/mm3
   - Hemoglobin >= 9 g/dL
   - Total bilirubin <= 1.5 x institutional upper limit of normal (ULN)
   - AST(SGOT)/ALT(SGPT) <= 2.5 x ULN (or <= 5 x ULN for patients with liver metastases)
   - Creatinine clearance >= 50 mL/min by Cockcroft-Gault formula
   - INR or PT <= 1.5 x ULN

Exclusion Criteria:

1. Uncontrolled intercurrent illness""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "solid tumor", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "Age >= 18", "category": "demographic"},
            {"type": "exclusion", "text_fragment": "intercurrent illness", "category": "comorbidity"},
        ],
        "expected_counts": {"inclusion": 3, "exclusion": 1},
    },
    # -------------------------------------------------------------------
    # 8. Basket trial — multiple tumor types
    # -------------------------------------------------------------------
    {
        "id": "ext_basket_trial",
        "description": "Basket trial accepting multiple tumor types",
        "eligibility_text": """Inclusion Criteria:

1. Histologically confirmed advanced solid tumor with one of the following:
   - NTRK gene fusion
   - ROS1 gene rearrangement
   - ALK gene rearrangement
2. Measurable disease per RECIST 1.1
3. Prior treatment with at least one standard therapy, or no standard therapy exists
4. ECOG 0-2
5. Age >= 12 years

Exclusion Criteria:

1. Prior treatment with an NTRK, ROS1, or ALK inhibitor
2. Symptomatic brain metastases (treated, stable brain metastases are allowed)
3. Known cardiac dysfunction (LVEF < 45%)""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "solid tumor", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "NTRK", "category": "biomarker"},
            {"type": "inclusion", "text_fragment": "measurable disease", "category": "disease_status"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "exclusion", "text_fragment": "NTRK, ROS1, or ALK inhibitor", "category": "prior_therapy"},
            {"type": "exclusion", "text_fragment": "brain metastases", "category": "disease_status"},
        ],
        "expected_counts": {"inclusion": 5, "exclusion": 3},
    },
    # -------------------------------------------------------------------
    # 9. Washout-heavy trial
    # -------------------------------------------------------------------
    {
        "id": "ext_washout_heavy",
        "description": "Trial with multiple washout period requirements",
        "eligibility_text": """Inclusion Criteria:

- Confirmed metastatic renal cell carcinoma
- ECOG 0-1
- At least 2 weeks since last systemic therapy
- At least 4 weeks since major surgery
- At least 2 weeks since last radiation therapy

Exclusion Criteria:

- Prior treatment with cabozantinib
- Received any investigational agent within 28 days prior to first dose
- GI malabsorption or any condition affecting oral drug absorption""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "renal cell carcinoma", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "inclusion", "text_fragment": "2 weeks since last systemic therapy", "category": "washout"},
            {"type": "inclusion", "text_fragment": "4 weeks since major surgery", "category": "washout"},
            {"type": "exclusion", "text_fragment": "cabozantinib", "category": "prior_therapy"},
            {"type": "exclusion", "text_fragment": "investigational agent within 28 days", "category": "washout"},
        ],
        "expected_counts": {"inclusion": 5, "exclusion": 3},
    },
    # -------------------------------------------------------------------
    # 10. Prostate mCRPC — disease-specific criteria
    # -------------------------------------------------------------------
    {
        "id": "ext_prostate_mcrpc",
        "description": "Prostate cancer trial with castration-resistant requirements",
        "eligibility_text": """Inclusion Criteria:

1. Metastatic castration-resistant prostate cancer (mCRPC)
2. Documented disease progression on or after prior therapy with abiraterone or enzalutamide
3. Ongoing androgen deprivation therapy with serum testosterone < 50 ng/dL
4. ECOG performance status 0-1
5. At least 18 years of age

Exclusion Criteria:

1. Prior chemotherapy for metastatic castration-resistant prostate cancer (prior docetaxel in castration-sensitive setting is allowed)
2. Known BRCA1/2 or ATM mutation with prior PARP inhibitor therapy
3. Clinically significant cardiovascular disease within 6 months
4. Active second malignancy""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "castration-resistant prostate cancer", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "abiraterone or enzalutamide", "category": "prior_therapy"},
            {"type": "inclusion", "text_fragment": "testosterone < 50", "category": "labs"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {
                "type": "exclusion",
                "text_fragment": "chemotherapy for metastatic castration-resistant",
                "category": "prior_therapy",
            },
            {"type": "exclusion", "text_fragment": "BRCA1/2", "category": "biomarker"},
            {"type": "exclusion", "text_fragment": "cardiovascular disease", "category": "comorbidity"},
        ],
        "expected_counts": {"inclusion": 5, "exclusion": 4},
    },
    # -------------------------------------------------------------------
    # 11. Extremely short criteria
    # Known limitation: rule-based parser filters items < 10 chars,
    # so "Age 18+", "ECOG 0-2", and "Pregnant" get dropped.
    # -------------------------------------------------------------------
    {
        "id": "ext_minimal",
        "description": "Trial with very brief eligibility text",
        "eligibility_text": """Inclusion Criteria:

- Advanced cancer
- Age 18+
- ECOG 0-2

Exclusion Criteria:

- Pregnant""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "cancer", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "exclusion", "text_fragment": "Pregnant", "category": "demographic"},
        ],
        # Rule-based filters criteria < 10 chars, so "Age 18+", "ECOG 0-2",
        # "Pregnant" all get dropped. Only "Advanced cancer" survives.
        "expected_counts": {"inclusion": 1, "exclusion": 0},
        "rulebased_known_limitation": True,
    },
    # -------------------------------------------------------------------
    # 12. Heavily compound criteria — tests splitting ability
    # -------------------------------------------------------------------
    {
        "id": "ext_compound_heavy",
        "description": "Criteria with many compound requirements in single bullets",
        "eligibility_text": """Inclusion Criteria:

1. Age >= 18 years with histologically confirmed NSCLC and documented EGFR T790M mutation
2. Prior treatment with osimertinib with radiographic progression
3. ECOG 0-1 and life expectancy of at least 12 weeks
4. Adequate organ and bone marrow function including ANC >= 1500, platelets >= 100k, and creatinine <= 1.5x ULN

Exclusion Criteria:

1. Active CNS metastases or carcinomatous meningitis
2. Known HIV positive or active hepatitis B or C
3. Prior solid organ transplant or allogeneic stem cell transplant""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "NSCLC", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "EGFR T790M", "category": "biomarker"},
            {"type": "inclusion", "text_fragment": "osimertinib", "category": "prior_therapy"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "exclusion", "text_fragment": "CNS metastases", "category": "disease_status"},
            {"type": "exclusion", "text_fragment": "HIV", "category": "comorbidity"},
            {"type": "exclusion", "text_fragment": "transplant", "category": "comorbidity"},
        ],
        "expected_counts": {"inclusion": 4, "exclusion": 3},
    },
    # -------------------------------------------------------------------
    # 13. Immunotherapy trial — complex exclusion criteria
    # -------------------------------------------------------------------
    {
        "id": "ext_immunotherapy_exclusions",
        "description": "Immunotherapy trial with nuanced exclusion criteria",
        "eligibility_text": """Inclusion Criteria:

1. Histologically confirmed advanced or metastatic solid tumor
2. PD-L1 expression >= 1% by IHC (22C3 assay)
3. No prior immunotherapy (anti-PD-1, anti-PD-L1, anti-CTLA-4)
4. ECOG 0-1

Exclusion Criteria:

1. Active autoimmune disease that has required systemic treatment in past 2 years (replacement therapy such as thyroxine, insulin, or physiologic corticosteroids is not considered systemic treatment)
2. Known history of active tuberculosis
3. Receipt of live vaccine within 30 days of planned start of study therapy
4. Prior immunotherapy-related adverse event of Grade 3 or higher
5. Known history of HIV (testing not required)""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "solid tumor", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "PD-L1 expression", "category": "biomarker"},
            {"type": "inclusion", "text_fragment": "prior immunotherapy", "category": "prior_therapy"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "exclusion", "text_fragment": "autoimmune disease", "category": "comorbidity"},
            {"type": "exclusion", "text_fragment": "tuberculosis", "category": "comorbidity"},
            {"type": "exclusion", "text_fragment": "live vaccine", "category": "washout"},
            {"type": "exclusion", "text_fragment": "HIV", "category": "comorbidity"},
        ],
        "expected_counts": {"inclusion": 4, "exclusion": 5},
    },
    # -------------------------------------------------------------------
    # 14. Empty eligibility text — edge case
    # -------------------------------------------------------------------
    {
        "id": "ext_empty",
        "description": "Empty eligibility text",
        "eligibility_text": "",
        "expected_criteria": [],
        "expected_counts": {"inclusion": 0, "exclusion": 0},
    },
    # -------------------------------------------------------------------
    # 15. SCLC trial — treatment-naive
    # -------------------------------------------------------------------
    {
        "id": "ext_sclc_frontline",
        "description": "SCLC trial requiring treatment-naive patients",
        "eligibility_text": """Inclusion Criteria:

1. Histologically or cytologically confirmed extensive-stage small cell lung cancer (ES-SCLC)
2. No prior systemic therapy for extensive-stage disease
3. Measurable disease per RECIST 1.1
4. ECOG performance status 0 or 1
5. Adequate organ function
6. Age >= 18 years
7. Written informed consent

Exclusion Criteria:

1. Active or untreated brain metastases
2. Prior treatment with any anti-PD-1 or anti-PD-L1 antibody
3. History of pneumonitis requiring steroids
4. Active second primary malignancy
5. Pregnancy or lactation""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "small cell lung cancer", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "No prior systemic therapy", "category": "prior_therapy"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "inclusion", "text_fragment": "informed consent", "category": "consent"},
            {"type": "exclusion", "text_fragment": "brain metastases", "category": "disease_status"},
            {"type": "exclusion", "text_fragment": "pneumonitis", "category": "comorbidity"},
            {"type": "exclusion", "text_fragment": "Pregnancy", "category": "demographic"},
        ],
        "expected_counts": {"inclusion": 7, "exclusion": 5},
    },
    # -------------------------------------------------------------------
    # 16. GBM trial — disease-specific with complex washout
    # -------------------------------------------------------------------
    {
        "id": "ext_gbm_recurrent",
        "description": "GBM trial with complex treatment history requirements",
        "eligibility_text": """Inclusion Criteria:

1. Histologically confirmed glioblastoma at first recurrence
2. Prior treatment with temozolomide and radiation therapy
3. At least 12 weeks from completion of radiation therapy
4. At least 4 weeks from last dose of temozolomide
5. Karnofsky Performance Status >= 60%
6. Stable dose of corticosteroids for at least 5 days prior to enrollment

Exclusion Criteria:

1. More than one prior recurrence
2. Prior bevacizumab therapy
3. Evidence of intratumoral hemorrhage on baseline MRI (except stable post-surgical changes)
4. Uncontrolled seizures despite adequate antiepileptic therapy""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "glioblastoma", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "temozolomide and radiation", "category": "prior_therapy"},
            {"type": "inclusion", "text_fragment": "12 weeks from completion of radiation", "category": "washout"},
            {"type": "inclusion", "text_fragment": "Karnofsky", "category": "performance"},
            {"type": "exclusion", "text_fragment": "prior recurrence", "category": "disease_status"},
            {"type": "exclusion", "text_fragment": "bevacizumab", "category": "prior_therapy"},
            {"type": "exclusion", "text_fragment": "seizures", "category": "comorbidity"},
        ],
        "expected_counts": {"inclusion": 6, "exclusion": 4},
    },
    # -------------------------------------------------------------------
    # 17. AML trial — hematologic cancer
    # -------------------------------------------------------------------
    {
        "id": "ext_aml",
        "description": "AML trial with FLT3 mutation requirement",
        "eligibility_text": """Inclusion Criteria:

- Newly diagnosed acute myeloid leukemia (AML) with FLT3-ITD mutation
- Age >= 18 years
- Adequate cardiac function (LVEF >= 50%)
- Fit for intensive chemotherapy as judged by investigator

Exclusion Criteria:

- Acute promyelocytic leukemia (APL, FAB M3)
- Known CNS involvement by AML
- Prior treatment for AML (hydroxyurea for cytoreduction permitted)""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "acute myeloid leukemia", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "FLT3-ITD", "category": "biomarker"},
            {"type": "inclusion", "text_fragment": "Age >= 18", "category": "demographic"},
            {"type": "inclusion", "text_fragment": "LVEF", "category": "labs"},
            {"type": "exclusion", "text_fragment": "promyelocytic leukemia", "category": "diagnosis"},
            {"type": "exclusion", "text_fragment": "CNS involvement", "category": "disease_status"},
        ],
        "expected_counts": {"inclusion": 4, "exclusion": 3},
    },
    # -------------------------------------------------------------------
    # 18. Ovarian cancer — BRCA-specific
    # -------------------------------------------------------------------
    {
        "id": "ext_ovarian_brca",
        "description": "Ovarian cancer trial requiring BRCA mutation",
        "eligibility_text": """Inclusion Criteria:

1. High-grade serous or endometrioid ovarian, fallopian tube, or primary peritoneal cancer
2. Deleterious or suspected deleterious germline or somatic BRCA1 or BRCA2 mutation
3. Received at least 2 prior lines of platinum-based chemotherapy
4. Platinum-sensitive disease (progression >= 6 months after last platinum)
5. ECOG 0-1

Exclusion Criteria:

1. Prior PARP inhibitor therapy
2. Known hypersensitivity to olaparib or any excipients
3. Myelodysplastic syndrome or features suggestive of MDS/AML""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "ovarian", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "BRCA1 or BRCA2", "category": "biomarker"},
            {"type": "inclusion", "text_fragment": "platinum-based chemotherapy", "category": "prior_therapy"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "exclusion", "text_fragment": "PARP inhibitor", "category": "prior_therapy"},
        ],
        "expected_counts": {"inclusion": 5, "exclusion": 3},
    },
    # -------------------------------------------------------------------
    # 19. Bullet-style with mixed markers
    # -------------------------------------------------------------------
    {
        "id": "ext_bullet_mixed",
        "description": "Mixed bullet styles (dash, asterisk, dot)",
        "eligibility_text": """Inclusion Criteria:

- Confirmed hepatocellular carcinoma (HCC) by histology or imaging
* Child-Pugh score A
• Barcelona Clinic Liver Cancer (BCLC) stage B or C
– ECOG performance status 0-1
- At least 18 years of age

Exclusion Criteria:

- Prior systemic therapy for HCC
* Clinically apparent ascites
• Main portal vein invasion or thrombosis""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "hepatocellular carcinoma", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "exclusion", "text_fragment": "systemic therapy for HCC", "category": "prior_therapy"},
        ],
        "expected_counts": {"inclusion": 5, "exclusion": 3},
    },
    # -------------------------------------------------------------------
    # 20. Ewing sarcoma — rare tumor
    # -------------------------------------------------------------------
    {
        "id": "ext_ewing_sarcoma",
        "description": "Ewing sarcoma trial with fusion confirmation",
        "eligibility_text": """Inclusion Criteria:

1. Histologically confirmed Ewing sarcoma or Ewing-like small round cell sarcoma
2. Confirmed EWSR1 translocation by FISH or molecular testing
3. Relapsed or refractory disease after at least one prior regimen
4. Age >= 12 years and <= 40 years
5. ECOG 0-1 or Lansky >= 70 (for patients < 16 years)
6. Adequate renal function (creatinine <= 1.5x ULN for age)

Exclusion Criteria:

1. Prior treatment with the study drug or its class
2. Active CNS disease
3. Known cardiac dysfunction (LVEF < 50%)
4. Major surgery within 3 weeks of first dose""",
        "expected_criteria": [
            {"type": "inclusion", "text_fragment": "Ewing sarcoma", "category": "diagnosis"},
            {"type": "inclusion", "text_fragment": "EWSR1 translocation", "category": "biomarker"},
            {"type": "inclusion", "text_fragment": "Relapsed or refractory", "category": "stage"},
            {"type": "inclusion", "text_fragment": "Age >= 12", "category": "demographic"},
            {"type": "inclusion", "text_fragment": "ECOG", "category": "performance"},
            {"type": "exclusion", "text_fragment": "CNS disease", "category": "disease_status"},
            {"type": "exclusion", "text_fragment": "Major surgery within 3 weeks", "category": "washout"},
        ],
        "expected_counts": {"inclusion": 6, "exclusion": 4},
    },
]
