"""Tier 4 — CI regression tests.

Frozen (input, expected_output) fixtures that run on every PR.
Tests scoring determinism, tier assignment, and criteria counting.
No live API calls. Runs in < 60s.
"""

from __future__ import annotations

import pytest

from eval.regression.fixtures import REGRESSION_FIXTURES
from tools.scoring import calculate_match_score


@pytest.fixture(params=REGRESSION_FIXTURES, ids=lambda f: f["id"])
def fixture(request):
    return request.param


class TestScoringRegression:
    """Verify calculate_match_score is deterministic against frozen fixtures."""

    def test_score_matches(self, fixture):
        result = calculate_match_score(fixture["claude_evaluations"], fixture["flags_for_oncologist"])
        assert result["score"] == fixture["expected_score"], (
            f"Score drift on {fixture['id']}: expected {fixture['expected_score']}, got {result['score']}"
        )

    def test_tier_matches(self, fixture):
        result = calculate_match_score(fixture["claude_evaluations"], fixture["flags_for_oncologist"])
        assert result["tier"] == fixture["expected_tier"], (
            f"Tier drift on {fixture['id']}: expected {fixture['expected_tier']}, got {result['tier']}"
        )

    def test_criteria_counts(self, fixture):
        result = calculate_match_score(fixture["claude_evaluations"], fixture["flags_for_oncologist"])
        assert result["criteria_met"] == fixture["expected_criteria_met"], (
            f"criteria_met drift on {fixture['id']}: "
            f"expected {fixture['expected_criteria_met']}, got {result['criteria_met']}"
        )
        assert result["criteria_not_met"] == fixture["expected_criteria_not_met"], (
            f"criteria_not_met drift on {fixture['id']}: "
            f"expected {fixture['expected_criteria_not_met']}, got {result['criteria_not_met']}"
        )
        assert result["criteria_unknown"] == fixture["expected_criteria_unknown"], (
            f"criteria_unknown drift on {fixture['id']}: "
            f"expected {fixture['expected_criteria_unknown']}, got {result['criteria_unknown']}"
        )

    def test_explanation_not_empty(self, fixture):
        result = calculate_match_score(fixture["claude_evaluations"], fixture["flags_for_oncologist"])
        assert result["match_explanation"], f"Empty explanation on {fixture['id']}"

    def test_exclusion_counts_consistent(self, fixture):
        result = calculate_match_score(fixture["claude_evaluations"], fixture["flags_for_oncologist"])
        exclusions = [e for e in fixture["claude_evaluations"] if e.get("type") == "exclusion"]
        total_exc = result["exclusions_clear"] + result["exclusions_triggered"] + result["exclusions_unknown"]
        assert total_exc == len(exclusions), (
            f"Exclusion count mismatch on {fixture['id']}: {total_exc} accounted for vs {len(exclusions)} total"
        )


class TestFixtureIntegrity:
    """Validate that fixtures themselves are well-formed."""

    def test_all_fixtures_have_required_fields(self):
        required = [
            "id",
            "description",
            "patient",
            "trial",
            "claude_evaluations",
            "expected_score",
            "expected_tier",
        ]
        for f in REGRESSION_FIXTURES:
            for field in required:
                assert field in f, f"Fixture {f.get('id', '?')} missing field '{field}'"

    def test_fixture_ids_unique(self):
        ids = [f["id"] for f in REGRESSION_FIXTURES]
        assert len(ids) == len(set(ids))

    def test_minimum_fixture_count(self):
        assert len(REGRESSION_FIXTURES) >= 15, f"Need at least 15 regression fixtures, have {len(REGRESSION_FIXTURES)}"

    def test_tier_coverage(self):
        tiers = {f["expected_tier"] for f in REGRESSION_FIXTURES}
        expected_tiers = {"STRONG_MATCH", "EXCLUDED", "POTENTIAL_MATCH", "PARTIAL_MATCH"}
        missing = expected_tiers - tiers
        assert not missing, f"Missing tier coverage: {missing}"

    def test_evaluations_have_type(self):
        for f in REGRESSION_FIXTURES:
            for e in f["claude_evaluations"]:
                assert e.get("type") in ("inclusion", "exclusion"), f"Evaluation in {f['id']} missing valid type: {e}"

    def test_evaluations_have_status(self):
        valid_statuses = {"MET", "NOT_MET", "INSUFFICIENT_INFO", "TRIGGERED", "NOT_TRIGGERED"}
        for f in REGRESSION_FIXTURES:
            for e in f["claude_evaluations"]:
                assert e.get("status") in valid_statuses, f"Invalid status in {f['id']}: {e.get('status')}"
