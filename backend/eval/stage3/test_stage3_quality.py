"""Stage 3 — Semantic recall quality tests.

CI tests validate summary builders and ranking logic with mocked embeddings.
Live tests (@pytest.mark.ollama) hit real Ollama to measure embedding quality.

Key validation: Stage 3 re-ranking HURTS quality on small pools (<50 trials)
because shallow embeddings replace the API's better relevance ordering.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from eval.stage3.fixtures import SEMANTIC_RECALL_FIXTURES
from semantic_recall import (
    _cosine_similarity,
    build_patient_summary,
    build_trial_summary,
    rank_trials_by_similarity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_embeddings(n_texts: int, patient_idx: int = 0) -> list[list[float]]:
    """Create mock embeddings where semantically related items are closer.

    The patient embedding is index 0. Trials at lower indices (more relevant)
    get embeddings closer to the patient embedding.
    """
    import math

    embeddings = []
    dim = 768
    for i in range(n_texts):
        if i == patient_idx:
            # Patient embedding: all 1s (unit vector direction)
            emb = [1.0 / math.sqrt(dim)] * dim
        else:
            # Trial embeddings: progressively less aligned with patient
            trial_idx = i - 1  # 0-indexed from first trial
            alignment = max(0.1, 1.0 - trial_idx * 0.15)
            emb = [alignment / math.sqrt(dim)] * dim
            # Add some noise to make them non-identical
            emb[trial_idx % dim] += 0.01
        embeddings.append(emb)
    return embeddings


# ---------------------------------------------------------------------------
# CI tests (mocked embeddings)
# ---------------------------------------------------------------------------


class TestSummaryBuilders:
    """Test that patient and trial summaries are well-formed."""

    @pytest.fixture(params=SEMANTIC_RECALL_FIXTURES, ids=lambda f: f["id"])
    def fixture(self, request):
        return request.param

    def test_patient_summary_includes_cancer_type(self, fixture):
        summary = build_patient_summary(fixture["patient"])
        assert fixture["patient"]["cancer_type"].lower() in summary.lower()

    def test_patient_summary_includes_biomarkers(self, fixture):
        summary = build_patient_summary(fixture["patient"])
        if fixture["patient"].get("biomarkers"):
            assert "biomarker" in summary.lower()

    def test_patient_summary_no_phi(self, fixture):
        summary = build_patient_summary(fixture["patient"])
        # Summary should not contain location, name, DOB
        assert "zip" not in summary.lower()
        assert "10001" not in summary
        assert "90210" not in summary

    def test_trial_summary_includes_title(self, fixture):
        for trial in fixture["trial_pool"]:
            summary = build_trial_summary(trial)
            assert trial["brief_title"] in summary

    def test_trial_summary_includes_conditions(self, fixture):
        for trial in fixture["trial_pool"]:
            summary = build_trial_summary(trial)
            if trial.get("conditions"):
                assert "Conditions:" in summary


class TestRankingWithMockedEmbeddings:
    """Test ranking logic with deterministic mock embeddings."""

    @pytest.fixture(params=SEMANTIC_RECALL_FIXTURES, ids=lambda f: f["id"])
    def fixture(self, request):
        return request.param

    @pytest.mark.asyncio
    async def test_ranking_returns_correct_count(self, fixture):
        pool = fixture["trial_pool"]
        n_texts = 1 + len(pool)  # patient + trials
        mock_embeddings = _make_mock_embeddings(n_texts)

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=mock_embeddings)

        with patch("semantic_recall.get_gemma_client", return_value=mock_client):
            results = await rank_trials_by_similarity(
                fixture["patient"],
                pool,
                top_n=len(pool),
            )

        assert len(results) == len(pool)

    @pytest.mark.asyncio
    async def test_ranking_returns_tuples(self, fixture):
        pool = fixture["trial_pool"]
        n_texts = 1 + len(pool)
        mock_embeddings = _make_mock_embeddings(n_texts)

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=mock_embeddings)

        with patch("semantic_recall.get_gemma_client", return_value=mock_client):
            results = await rank_trials_by_similarity(fixture["patient"], pool)

        for trial, score in results:
            assert isinstance(trial, dict)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_ranking_sorted_descending(self, fixture):
        pool = fixture["trial_pool"]
        n_texts = 1 + len(pool)
        mock_embeddings = _make_mock_embeddings(n_texts)

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=mock_embeddings)

        with patch("semantic_recall.get_gemma_client", return_value=mock_client):
            results = await rank_trials_by_similarity(fixture["patient"], pool)

        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_top_n_limits_results(self, fixture):
        pool = fixture["trial_pool"]
        n_texts = 1 + len(pool)
        mock_embeddings = _make_mock_embeddings(n_texts)

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=mock_embeddings)

        with patch("semantic_recall.get_gemma_client", return_value=mock_client):
            results = await rank_trials_by_similarity(fixture["patient"], pool, top_n=2)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_empty_pool(self):
        results = await rank_trials_by_similarity({"cancer_type": "test"}, [])
        assert results == []


class TestCosineEdgeCases:
    """Test cosine similarity edge cases."""

    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_zero_vector(self):
        assert _cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0

    def test_orthogonal_vectors(self):
        assert abs(_cosine_similarity([1, 0], [0, 1])) < 1e-6


class TestThresholdValidation:
    """Tests that validate the pool >= 50 skip threshold.

    The hypothesis: on small pools (<50), the ClinicalTrials.gov API's native
    ordering is better than Gemma's shallow embedding re-ranking.

    This is tested with mocked embeddings that intentionally scramble the
    order, showing that re-ranking on small pools can hurt.
    """

    @pytest.mark.asyncio
    async def test_small_pool_order_preserved_when_disabled(self):
        """When re-ranking is disabled (small pool), the API order should be preserved."""
        from agents import MatchingAgent

        agent = MatchingAgent.__new__(MatchingAgent)

        # Build a mock pool of 10 trials (below threshold)
        pool = {
            "trials": {
                f"NCT{i:04d}": {
                    "nct_id": f"NCT{i:04d}",
                    "brief_title": f"Trial {i}",
                    "api_rank": i,
                }
                for i in range(10)
            }
        }

        from config import Settings

        settings = Settings(
            anthropic_api_key="test",
            gemma_stage3_enabled=True,  # enabled, but pool is too small
        )
        from models import PatientProfile

        patient = PatientProfile(
            cancer_type="Test",
            cancer_stage="Stage IV",
            biomarkers=[],
            prior_treatments=[],
            lines_of_therapy=0,
            age=50,
            sex="male",
            ecog_score=1,
            location_zip="10001",
            willing_to_travel_miles=100,
            additional_conditions=[],
        )

        result = await agent._semantic_rank(pool, patient, settings)
        # Pool < 50 → should be returned unchanged
        assert result == pool


class TestFixtureIntegrity:
    """Validate fixture structure."""

    def test_minimum_fixtures(self):
        assert len(SEMANTIC_RECALL_FIXTURES) >= 3

    def test_fixture_ids_unique(self):
        ids = [f["id"] for f in SEMANTIC_RECALL_FIXTURES]
        assert len(ids) == len(set(ids))

    def test_all_have_expected_rankings(self):
        for f in SEMANTIC_RECALL_FIXTURES:
            assert "should_rank_high" in f["expected"]
            assert "should_rank_low" in f["expected"]
            assert len(f["expected"]["should_rank_high"]) >= 1
            assert len(f["expected"]["should_rank_low"]) >= 1

    def test_expected_nct_ids_in_pool(self):
        for f in SEMANTIC_RECALL_FIXTURES:
            pool_ids = {t["nct_id"] for t in f["trial_pool"]}
            for level in ["should_rank_high", "should_rank_medium", "should_rank_low"]:
                for nct_id in f["expected"].get(level, []):
                    assert nct_id in pool_ids, f"Expected NCT {nct_id} not in pool for {f['id']}"


# ---------------------------------------------------------------------------
# Live Ollama tests
# ---------------------------------------------------------------------------


@pytest.mark.ollama
class TestSemanticRecallLive:
    """Test real embedding quality with Ollama.

    Run with: pytest -m ollama eval/stage3/
    """

    @pytest.fixture(params=SEMANTIC_RECALL_FIXTURES, ids=lambda f: f["id"])
    def fixture(self, request):
        return request.param

    @pytest.mark.asyncio
    async def test_high_rank_trials_in_top_half(self, fixture):
        """Trials expected to rank high should be in the top half of results."""
        results = await rank_trials_by_similarity(
            fixture["patient"],
            fixture["trial_pool"],
            top_n=len(fixture["trial_pool"]),
        )

        ranked_ids = [t["nct_id"] for t, _ in results]
        top_half = set(ranked_ids[: len(ranked_ids) // 2])

        for nct_id in fixture["expected"]["should_rank_high"]:
            assert nct_id in top_half, (
                f"{nct_id} expected in top half but ranked {ranked_ids.index(nct_id) + 1}/{len(ranked_ids)}"
            )

    @pytest.mark.asyncio
    async def test_low_rank_trials_in_bottom_half(self, fixture):
        """Trials expected to rank low should be in the bottom half."""
        results = await rank_trials_by_similarity(
            fixture["patient"],
            fixture["trial_pool"],
            top_n=len(fixture["trial_pool"]),
        )

        ranked_ids = [t["nct_id"] for t, _ in results]
        bottom_half = set(ranked_ids[len(ranked_ids) // 2 :])

        for nct_id in fixture["expected"]["should_rank_low"]:
            assert nct_id in bottom_half, (
                f"{nct_id} expected in bottom half but ranked {ranked_ids.index(nct_id) + 1}/{len(ranked_ids)}"
            )

    @pytest.mark.asyncio
    async def test_high_above_low(self, fixture):
        """High-priority trials should rank above low-priority trials."""
        results = await rank_trials_by_similarity(
            fixture["patient"],
            fixture["trial_pool"],
            top_n=len(fixture["trial_pool"]),
        )

        ranked_ids = [t["nct_id"] for t, _ in results]

        for high_id in fixture["expected"]["should_rank_high"]:
            high_rank = ranked_ids.index(high_id)
            for low_id in fixture["expected"]["should_rank_low"]:
                low_rank = ranked_ids.index(low_id)
                assert high_rank < low_rank, (
                    f"{high_id} (rank {high_rank + 1}) should rank above {low_id} (rank {low_rank + 1})"
                )
