"""Stage 1 — Intake normalization accuracy tests.

CI tests mock GemmaClient to replay expected outputs.
Live tests (@pytest.mark.ollama) hit real Ollama and check critical fields.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from eval.stage1.fixtures import (
    ALL_STAGE1_FIXTURES,
    BIOMARKER_POLARITY_FIXTURES,
    CANCER_TYPE_FIXTURES,
    DRUG_NORMALIZATION_FIXTURES,
    LINES_OF_THERAPY_FIXTURES,
    REGIMEN_FIXTURES,
)
from intake import NormalizedIntake, normalize_intake

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_critical_fields(result: NormalizedIntake, critical_check: dict):
    """Assert that safety-critical fields match exactly."""
    for field, expected_value in critical_check.items():
        actual = getattr(result, field)
        if isinstance(expected_value, list):
            # For lists, check all expected items are present (order-independent)
            for item in expected_value:
                assert item in actual, f"Expected '{item}' in {field}, got {actual}"
        else:
            assert actual == expected_value, f"Expected {field}='{expected_value}', got '{actual}'"


# ---------------------------------------------------------------------------
# CI tests (mocked Gemma — no Ollama needed)
# ---------------------------------------------------------------------------


class TestStage1Mocked:
    """Test normalize_intake with mocked Gemma returning expected outputs."""

    @pytest.fixture(params=ALL_STAGE1_FIXTURES, ids=lambda f: f["id"])
    def fixture(self, request):
        return request.param

    @pytest.mark.asyncio
    async def test_normalize_returns_expected(self, fixture):
        """Mock Gemma to return expected output, verify normalize_intake passes it through."""
        expected = fixture["expected_output"]

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value=expected)

        with patch("intake.get_gemma_client", return_value=mock_client):
            result = await normalize_intake(fixture["input_text"])

        assert isinstance(result, NormalizedIntake)
        _check_critical_fields(result, fixture["critical_check"])

    @pytest.mark.asyncio
    async def test_with_form_hints(self):
        """Form hints should be passed to the prompt."""
        expected = NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
            biomarkers=["EGFR+"],
        )
        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value=expected)

        with patch("intake.get_gemma_client", return_value=mock_client):
            result = await normalize_intake(
                "Patient has lung cancer with EGFR mutation",
                form_hints={"cancer_type": "NSCLC", "cancer_stage": "Stage IV"},
            )

        assert result.cancer_type == "Non-Small Cell Lung Carcinoma"
        # Verify the prompt was called with form hints
        call_args = mock_client.generate.call_args
        prompt = call_args[0][0]
        assert "cancer_type: NSCLC" in prompt


class TestBiomarkerPolaritySafety:
    """Dedicated tests for biomarker polarity — the safety-critical gate.

    These tests verify the fixture expectations are consistent and
    cover the full polarity matrix.
    """

    def test_minimum_fixture_count(self):
        assert len(BIOMARKER_POLARITY_FIXTURES) >= 10, (
            f"Need at least 10 biomarker polarity fixtures, have {len(BIOMARKER_POLARITY_FIXTURES)}"
        )

    def test_covers_positive_cases(self):
        positive_ids = [
            f["id"]
            for f in BIOMARKER_POLARITY_FIXTURES
            if any("+" in b for b in f["critical_check"].get("biomarkers", []))
        ]
        assert len(positive_ids) >= 3, f"Need >= 3 positive polarity cases, have {len(positive_ids)}"

    def test_covers_negative_cases(self):
        negative_ids = [
            f["id"]
            for f in BIOMARKER_POLARITY_FIXTURES
            if any(b.endswith("-") for b in f["critical_check"].get("biomarkers", []))
        ]
        assert len(negative_ids) >= 3, f"Need >= 3 negative polarity cases, have {len(negative_ids)}"

    def test_covers_specific_mutations(self):
        mutation_ids = [
            f["id"]
            for f in BIOMARKER_POLARITY_FIXTURES
            if any(
                any(code in b for code in ["V600", "G12", "L858"]) for b in f["critical_check"].get("biomarkers", [])
            )
        ]
        assert len(mutation_ids) >= 2, f"Need >= 2 specific mutation cases, have {len(mutation_ids)}"

    def test_covers_expression_levels(self):
        expr_ids = [
            f["id"]
            for f in BIOMARKER_POLARITY_FIXTURES
            if any("%" in b for b in f["critical_check"].get("biomarkers", []))
        ]
        assert len(expr_ids) >= 1, f"Need >= 1 expression level case, have {len(expr_ids)}"

    def test_no_alk_confusion(self):
        """The most dangerous mistake: ALK-positive parsed as ALK-."""
        alk_fixtures = [f for f in BIOMARKER_POLARITY_FIXTURES if "alk" in f["id"]]
        assert len(alk_fixtures) >= 2, "Need ALK+ and ALK- test cases"

        for f in alk_fixtures:
            biomarkers = f["critical_check"]["biomarkers"]
            for b in biomarkers:
                if b.startswith("ALK"):
                    if "positive" in f["input_text"].lower() or "rearrangement" in f["input_text"].lower():
                        assert b == "ALK+", f"ALK-positive should be ALK+, got {b} in {f['id']}"
                    elif "negative" in f["input_text"].lower():
                        assert b == "ALK-", f"ALK negative should be ALK-, got {b} in {f['id']}"


class TestFixtureCoverage:
    """Verify fixture diversity."""

    def test_total_fixture_count(self):
        assert len(ALL_STAGE1_FIXTURES) >= 25, f"Need >= 25 Stage 1 fixtures, have {len(ALL_STAGE1_FIXTURES)}"

    def test_fixture_ids_unique(self):
        ids = [f["id"] for f in ALL_STAGE1_FIXTURES]
        assert len(ids) == len(set(ids)), f"Duplicate fixture IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_category_coverage(self):
        assert len(BIOMARKER_POLARITY_FIXTURES) >= 10
        assert len(CANCER_TYPE_FIXTURES) >= 5
        assert len(DRUG_NORMALIZATION_FIXTURES) >= 5
        assert len(REGIMEN_FIXTURES) >= 3
        assert len(LINES_OF_THERAPY_FIXTURES) >= 3


# ---------------------------------------------------------------------------
# Live Ollama tests (skip in CI)
# ---------------------------------------------------------------------------


@pytest.mark.ollama
class TestStage1Live:
    """Run normalize_intake against real Ollama.

    These tests verify that Gemma actually produces correct outputs,
    not just that the pipeline passes through mocked responses.

    Run with: pytest -m ollama eval/stage1/
    """

    @pytest.fixture(params=BIOMARKER_POLARITY_FIXTURES, ids=lambda f: f["id"])
    def bp_fixture(self, request):
        return request.param

    @pytest.mark.asyncio
    async def test_biomarker_polarity_live(self, bp_fixture):
        """SAFETY GATE: biomarker polarity must be 100% correct on real Gemma."""
        result = await normalize_intake(bp_fixture["input_text"])
        _check_critical_fields(result, bp_fixture["critical_check"])

    @pytest.fixture(params=CANCER_TYPE_FIXTURES, ids=lambda f: f["id"])
    def ct_fixture(self, request):
        return request.param

    @pytest.mark.asyncio
    async def test_cancer_type_live(self, ct_fixture):
        result = await normalize_intake(ct_fixture["input_text"])
        _check_critical_fields(result, ct_fixture["critical_check"])

    @pytest.fixture(params=DRUG_NORMALIZATION_FIXTURES, ids=lambda f: f["id"])
    def drug_fixture(self, request):
        return request.param

    @pytest.mark.asyncio
    async def test_drug_normalization_live(self, drug_fixture):
        result = await normalize_intake(drug_fixture["input_text"])
        _check_critical_fields(result, drug_fixture["critical_check"])
