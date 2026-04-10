"""Tests for tools/trial_classifier.py — deterministic biomarker-therapy alignment."""

from __future__ import annotations

from tools.trial_classifier import (
    cancer_type_matches,
    canonical_search_term,
    classify_interventions,
    is_biomarker_aligned,
    is_radiation_or_observational_only,
    patient_actionable_genes,
)

# ---------------------------------------------------------------------------
# classify_interventions
# ---------------------------------------------------------------------------


class TestClassifyInterventions:
    def test_radiation_only(self):
        trial = {"interventions": ["RADIATION: SBRT", "RADIATION: External Beam"]}
        assert classify_interventions(trial) == {"radiation"}

    def test_targeted_drug_egfr(self):
        trial = {"interventions": ["DRUG: osimertinib"]}
        assert classify_interventions(trial) == {"targeted"}

    def test_targeted_plus_radiation_combo(self):
        trial = {"interventions": ["DRUG: osimertinib", "RADIATION: SBRT"]}
        types = classify_interventions(trial)
        assert "targeted" in types
        assert "radiation" in types

    def test_chemo_carboplatin_pemetrexed(self):
        trial = {"interventions": ["DRUG: carboplatin", "DRUG: pemetrexed"]}
        assert classify_interventions(trial) == {"chemo"}

    def test_immunotherapy_pembrolizumab(self):
        trial = {"interventions": ["DRUG: pembrolizumab"]}
        assert classify_interventions(trial) == {"immunotherapy"}

    def test_biological_atezolizumab(self):
        trial = {"interventions": ["BIOLOGICAL: atezolizumab"]}
        assert classify_interventions(trial) == {"immunotherapy"}

    def test_observational_diagnostic_test(self):
        trial = {"interventions": ["DIAGNOSTIC_TEST: blood draw"]}
        assert classify_interventions(trial) == {"observational"}

    def test_empty_interventions_defensive_other(self):
        trial = {"interventions": []}
        assert classify_interventions(trial) == {"other"}

    def test_missing_interventions_key(self):
        trial = {}
        assert classify_interventions(trial) == {"other"}

    def test_unknown_drug_defaults_targeted(self):
        # Conservative — better to let LLM evaluate than wrongly filter
        trial = {"interventions": ["DRUG: investigational-compound-xyz"]}
        assert classify_interventions(trial) == {"targeted"}

    def test_combination_chemo_io(self):
        trial = {"interventions": ["DRUG: pembrolizumab", "DRUG: carboplatin", "DRUG: pemetrexed"]}
        types = classify_interventions(trial)
        assert "immunotherapy" in types
        assert "chemo" in types

    def test_hormonal_tamoxifen(self):
        trial = {"interventions": ["DRUG: tamoxifen"]}
        assert classify_interventions(trial) == {"hormonal"}


# ---------------------------------------------------------------------------
# patient_actionable_genes
# ---------------------------------------------------------------------------


class TestPatientActionableGenes:
    def test_egfr_positive(self):
        assert patient_actionable_genes(["EGFR+"]) == {"EGFR"}

    def test_egfr_negative_excluded(self):
        assert patient_actionable_genes(["EGFR-"]) == set()

    def test_egfr_with_variant(self):
        assert patient_actionable_genes(["EGFR L858R"]) == {"EGFR"}

    def test_multiple_actionable(self):
        result = patient_actionable_genes(["EGFR+", "ALK-", "PD-L1 80%"])
        # PD-L1 maps to CD274 which is NOT in _GENE_TO_DRUGS
        assert result == {"EGFR"}

    def test_her2_normalizes_to_erbb2(self):
        assert patient_actionable_genes(["HER2+"]) == {"ERBB2"}

    def test_braf_v600e(self):
        assert patient_actionable_genes(["BRAF V600E"]) == {"BRAF"}

    def test_negative_word(self):
        assert patient_actionable_genes(["EGFR negative"]) == set()

    def test_empty_input(self):
        assert patient_actionable_genes([]) == set()

    def test_unknown_biomarker(self):
        assert patient_actionable_genes(["XYZ123"]) == set()


# ---------------------------------------------------------------------------
# is_biomarker_aligned
# ---------------------------------------------------------------------------


class TestIsBiomarkerAligned:
    def test_no_actionable_genes_passes(self):
        trial = {"interventions": ["RADIATION: SBRT"]}
        aligned, _ = is_biomarker_aligned(trial, set())
        assert aligned is True

    def test_egfr_drug_match(self):
        trial = {"interventions": ["DRUG: osimertinib"]}
        aligned, reason = is_biomarker_aligned(trial, {"EGFR"})
        assert aligned is True
        assert "osimertinib" in reason.lower()

    def test_alk_drug_match(self):
        trial = {"interventions": ["DRUG: alectinib"]}
        aligned, _ = is_biomarker_aligned(trial, {"ALK"})
        assert aligned is True

    def test_egfr_patient_alk_drug_not_aligned(self):
        # ALK drug doesn't help EGFR patient
        trial = {"interventions": ["DRUG: alectinib"]}
        aligned, _ = is_biomarker_aligned(trial, {"EGFR"})
        assert aligned is False

    def test_radiation_only_not_aligned(self):
        trial = {"interventions": ["RADIATION: SBRT"]}
        aligned, _ = is_biomarker_aligned(trial, {"EGFR"})
        assert aligned is False

    def test_eligibility_text_mention(self):
        trial = {
            "interventions": ["RADIATION: SBRT"],
            "eligibility_criteria": "Patients with EGFR mutation positive NSCLC",
        }
        aligned, _ = is_biomarker_aligned(trial, {"EGFR"})
        assert aligned is True

    def test_combo_trial_egfr_radiation(self):
        # osimertinib + radiation combo IS aligned for EGFR patient
        trial = {"interventions": ["DRUG: osimertinib", "RADIATION: SBRT"]}
        aligned, _ = is_biomarker_aligned(trial, {"EGFR"})
        assert aligned is True


# ---------------------------------------------------------------------------
# is_radiation_or_observational_only
# ---------------------------------------------------------------------------


class TestIsRadiationOrObservationalOnly:
    def test_pure_radiation(self):
        assert is_radiation_or_observational_only({"radiation"}) is True

    def test_radiation_with_targeted(self):
        # Combo trial — NOT radiation-only
        assert is_radiation_or_observational_only({"radiation", "targeted"}) is False

    def test_radiation_with_chemo(self):
        assert is_radiation_or_observational_only({"radiation", "chemo"}) is False

    def test_observational(self):
        assert is_radiation_or_observational_only({"observational"}) is True

    def test_radiation_plus_surgery(self):
        assert is_radiation_or_observational_only({"radiation", "surgery"}) is True

    def test_pure_targeted_not_filtered(self):
        assert is_radiation_or_observational_only({"targeted"}) is False

    def test_other_only_defensive(self):
        # {"other"} alone should NOT be filtered (we couldn't classify)
        assert is_radiation_or_observational_only({"other"}) is False

    def test_empty(self):
        assert is_radiation_or_observational_only(set()) is False


# ---------------------------------------------------------------------------
# cancer_type_matches
# ---------------------------------------------------------------------------


class TestCancerTypeMatches:
    def test_nsclc_canonical(self):
        ok, _ = cancer_type_matches(
            "Non-Small Cell Lung Cancer",
            ["Non-Small Cell Lung Cancer"],
            "Study of osimertinib in NSCLC",
        )
        assert ok is True

    def test_nsclc_adenocarcinoma_subtype(self):
        ok, _ = cancer_type_matches(
            "Non-Small Cell Lung Cancer - Adenocarcinoma",
            ["Lung Adenocarcinoma"],
            "Lung Adenocarcinoma Study",
        )
        assert ok is True

    def test_breast_cancer_does_not_match_lung(self):
        ok, _ = cancer_type_matches(
            "Non-Small Cell Lung Cancer",
            ["Breast Cancer"],
            "Breast Cancer Study",
        )
        assert ok is False

    def test_basket_trial_bypass(self):
        ok, reason = cancer_type_matches(
            "Non-Small Cell Lung Cancer",
            ["Solid Tumors"],
            "NCI-MATCH: Tumor agnostic basket study",
        )
        assert ok is True
        assert "basket" in reason.lower() or "bypass" in reason.lower()

    def test_solid_tumor_generic_passes(self):
        ok, _ = cancer_type_matches(
            "Non-Small Cell Lung Cancer",
            ["Advanced Solid Tumors"],
            "Phase 1 dose escalation in advanced solid tumors",
        )
        assert ok is True

    def test_unknown_patient_cancer_passes_defensively(self):
        ok, _ = cancer_type_matches(
            "Some Rare Sarcoma Subtype",
            ["Sarcoma"],
            "Sarcoma study",
        )
        assert ok is True

    def test_breast_to_breast(self):
        ok, _ = cancer_type_matches(
            "Triple Negative Breast Cancer",
            ["Breast Cancer"],
            "TNBC trial",
        )
        assert ok is True

    def test_empty_conditions(self):
        ok, _ = cancer_type_matches("NSCLC", [], "")
        # With no trial info, allow through (defensive)
        assert ok is True


# ---------------------------------------------------------------------------
# canonical_search_term
# ---------------------------------------------------------------------------


class TestCanonicalSearchTerm:
    def test_nsclc_subtype_stripped(self):
        assert canonical_search_term("Non-Small Cell Lung Cancer - Adenocarcinoma") == "Non-Small Cell Lung Cancer"

    def test_nsclc_already_canonical(self):
        assert canonical_search_term("Non-Small Cell Lung Cancer") == "Non-Small Cell Lung Cancer"

    def test_lung_adenocarcinoma_maps_to_nsclc(self):
        assert canonical_search_term("Lung Adenocarcinoma") == "Non-Small Cell Lung Cancer"

    def test_nsclc_acronym(self):
        assert canonical_search_term("NSCLC") == "Non-Small Cell Lung Cancer"

    def test_sclc(self):
        assert canonical_search_term("Small Cell Lung Cancer") == "Small Cell Lung Cancer"

    def test_tnbc(self):
        assert canonical_search_term("Triple Negative Breast Cancer") == "Triple Negative Breast Cancer"

    def test_breast_subtype(self):
        assert canonical_search_term("Breast Cancer - HER2 Positive") == "Breast Cancer"

    def test_unknown_pass_through(self):
        # Unknown cancer type should be returned as-is
        assert canonical_search_term("Some Rare Sarcoma") == "Some Rare Sarcoma"

    def test_em_dash_separator(self):
        assert canonical_search_term("Non-Small Cell Lung Cancer — Squamous") == "Non-Small Cell Lung Cancer"

    def test_empty(self):
        assert canonical_search_term("") == ""
