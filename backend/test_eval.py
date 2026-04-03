"""Tests for the evaluation harness — metrics computation, not live API."""

from __future__ import annotations

from eval.run_eval import _compute_patient_metrics
from eval.synthetic_patients import SYNTHETIC_PATIENTS


class TestSyntheticPatients:
    def test_patients_not_empty(self):
        assert len(SYNTHETIC_PATIENTS) >= 10

    def test_all_patients_have_required_fields(self):
        for p in SYNTHETIC_PATIENTS:
            assert "id" in p
            assert "label" in p
            assert "profile" in p
            profile = p["profile"]
            assert "cancer_type" in profile
            assert "cancer_stage" in profile
            assert "age" in profile
            assert "sex" in profile
            assert "location_zip" in profile

    def test_patient_ids_unique(self):
        ids = [p["id"] for p in SYNTHETIC_PATIENTS]
        assert len(ids) == len(set(ids))

    def test_diverse_cancer_types(self):
        types = {p["profile"]["cancer_type"] for p in SYNTHETIC_PATIENTS}
        assert len(types) >= 7  # at least 7 different cancer types

    def test_age_range(self):
        ages = [p["profile"]["age"] for p in SYNTHETIC_PATIENTS]
        assert min(ages) < 18  # at least one pediatric
        assert max(ages) >= 65  # at least one elderly


class TestMetricsComputation:
    def test_basic_metrics(self):
        patient = {"id": "test", "label": "Test", "expected_good_criteria": {}}
        results = [
            {"nct_id": "NCT001", "score": 80.0, "tier": "STRONG_MATCH", "evaluations": []},
            {"nct_id": "NCT002", "score": 45.0, "tier": "PARTIAL_MATCH", "evaluations": []},
            {"nct_id": "NCT003", "score": 10.0, "tier": "UNLIKELY_MATCH", "evaluations": []},
        ]
        metrics = _compute_patient_metrics(patient, results)

        assert metrics["trials_evaluated"] == 3
        assert metrics["score_min"] == 10.0
        assert metrics["score_max"] == 80.0
        assert metrics["score_spread"] == 70.0
        assert len(metrics["scores"]) == 3

    def test_tier_distribution(self):
        patient = {"id": "test", "label": "Test", "expected_good_criteria": {}}
        results = [
            {"nct_id": "NCT001", "score": 85.0, "tier": "STRONG_MATCH", "evaluations": []},
            {"nct_id": "NCT002", "score": 60.0, "tier": "POTENTIAL_MATCH", "evaluations": []},
            {"nct_id": "NCT003", "score": 0.0, "tier": "EXCLUDED", "evaluations": []},
        ]
        metrics = _compute_patient_metrics(patient, results)
        assert metrics["tier_distribution"]["STRONG_MATCH"] == 1
        assert metrics["tier_distribution"]["EXCLUDED"] == 1

    def test_expected_criteria_accuracy(self):
        patient = {
            "id": "test",
            "label": "Test",
            "expected_good_criteria": {"diagnosis": "MET", "biomarker": "MET"},
        }
        results = [
            {
                "nct_id": "NCT001",
                "score": 70.0,
                "tier": "POTENTIAL_MATCH",
                "evaluations": [
                    {"status": "MET", "category": "diagnosis"},
                    {"status": "MET", "category": "biomarker"},
                    {"status": "INSUFFICIENT_INFO", "category": "labs"},
                ],
            },
        ]
        metrics = _compute_patient_metrics(patient, results)
        assert metrics["expected_criteria_accuracy"] == 1.0
        assert metrics["expected_criteria_correct"] == 2

    def test_handles_errors(self):
        patient = {"id": "test", "label": "Test", "expected_good_criteria": {}}
        results = [
            {"nct_id": "NCT001", "error": "parse_failed", "score": None},
            {"nct_id": "NCT002", "score": 50.0, "tier": "POTENTIAL_MATCH", "evaluations": []},
        ]
        metrics = _compute_patient_metrics(patient, results)
        assert metrics["eval_errors"] == 1
        assert len(metrics["scores"]) == 1

    def test_empty_results(self):
        patient = {"id": "test", "label": "Test", "expected_good_criteria": {}}
        metrics = _compute_patient_metrics(patient, [])
        assert metrics["trials_evaluated"] == 0
        assert metrics["scores"] == []
        assert metrics["score_spread"] == 0

    def test_criterion_status_distribution(self):
        patient = {"id": "test", "label": "Test", "expected_good_criteria": {}}
        results = [
            {
                "nct_id": "NCT001",
                "score": 60.0,
                "tier": "POTENTIAL_MATCH",
                "evaluations": [
                    {"status": "MET"},
                    {"status": "MET"},
                    {"status": "INSUFFICIENT_INFO"},
                    {"status": "NOT_MET"},
                ],
            },
        ]
        metrics = _compute_patient_metrics(patient, results)
        assert metrics["criterion_status_distribution"]["MET"] == 2
        assert metrics["criterion_status_distribution"]["INSUFFICIENT_INFO"] == 1
        assert metrics["criterion_status_distribution"]["NOT_MET"] == 1
