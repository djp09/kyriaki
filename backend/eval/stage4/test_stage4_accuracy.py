"""Stage 4 — Criterion extraction accuracy tests.

Compares rule-based parser (tools/criteria_parser.py) against expected labels.
Gemma extraction tests are in the @pytest.mark.ollama section.
"""

from __future__ import annotations

import pytest

from criterion_extraction import ExtractedCriteria, extract_criteria
from eval.stage4.fixtures import EXTRACTION_FIXTURES
from tools.criteria_parser import parse_eligibility_criteria

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {
    "diagnosis",
    "stage",
    "biomarker",
    "prior_therapy",
    "demographic",
    "performance",
    "labs",
    "comorbidity",
    "washout",
    "disease_status",
    "consent",
    "other",
}


def _check_expected_criteria(
    criteria: list[dict],
    expected: list[dict],
    fixture_id: str,
) -> dict:
    """Check how many expected criteria are found in the extracted criteria.

    Returns metrics dict with found/total counts.
    """
    found = 0
    missing = []

    for exp in expected:
        # Find a matching criterion by text fragment and type
        matched = False
        for c in criteria:
            text = c.get("text", "")
            ctype = c.get("type", "")
            if exp["text_fragment"].lower() in text.lower() and ctype == exp["type"]:
                matched = True
                break
        if matched:
            found += 1
        else:
            missing.append(exp)

    return {
        "fixture_id": fixture_id,
        "expected": len(expected),
        "found": found,
        "missing": missing,
        "recall": found / len(expected) if expected else 1.0,
    }


def _check_category_accuracy(
    criteria: list[dict],
    expected: list[dict],
) -> dict:
    """Check category assignment accuracy for matched criteria."""
    correct = 0
    checked = 0

    for exp in expected:
        for c in criteria:
            text = c.get("text", "")
            if exp["text_fragment"].lower() in text.lower() and c.get("type") == exp["type"]:
                checked += 1
                if c.get("category") == exp["category"]:
                    correct += 1
                break

    return {
        "checked": checked,
        "correct": correct,
        "accuracy": correct / checked if checked else 1.0,
    }


# ---------------------------------------------------------------------------
# Rule-based parser tests (CI-safe, no LLM)
# ---------------------------------------------------------------------------


class TestRuleBasedParser:
    """Test parse_eligibility_criteria against labeled fixtures."""

    @pytest.fixture(
        params=[f for f in EXTRACTION_FIXTURES if f["eligibility_text"]],
        ids=lambda f: f["id"],
    )
    def fixture(self, request):
        return request.param

    def test_parses_without_error(self, fixture):
        result = parse_eligibility_criteria(fixture["eligibility_text"])
        assert result.success

    def test_criterion_count_reasonable(self, fixture):
        result = parse_eligibility_criteria(fixture["eligibility_text"])
        expected_total = fixture["expected_counts"]["inclusion"] + fixture["expected_counts"]["exclusion"]
        actual_total = result.data["total_criteria"]
        # Allow some tolerance (rule-based may split differently)
        assert actual_total >= expected_total * 0.5, (
            f"{fixture['id']}: expected ~{expected_total} criteria, got {actual_total}"
        )

    def test_type_assignment(self, fixture):
        result = parse_eligibility_criteria(fixture["eligibility_text"])
        inclusion = result.data["inclusion_criteria"]
        exclusion = result.data["exclusion_criteria"]

        exp_inc = fixture["expected_counts"]["inclusion"]
        exp_exc = fixture["expected_counts"]["exclusion"]

        # Inclusion count should be close
        if exp_inc > 0:
            assert len(inclusion) >= exp_inc * 0.5, (
                f"{fixture['id']}: expected ~{exp_inc} inclusion, got {len(inclusion)}"
            )

        # Exclusion count should be close (or zero if no headers/known limitation)
        if exp_exc > 0 and "Exclusion" in fixture["eligibility_text"] and not fixture.get("rulebased_known_limitation"):
            assert len(exclusion) >= exp_exc * 0.5, (
                f"{fixture['id']}: expected ~{exp_exc} exclusion, got {len(exclusion)}"
            )

    def test_expected_criteria_found(self, fixture):
        result = parse_eligibility_criteria(fixture["eligibility_text"])
        all_criteria = result.data["inclusion_criteria"] + result.data["exclusion_criteria"]

        metrics = _check_expected_criteria(
            all_criteria,
            fixture["expected_criteria"],
            fixture["id"],
        )
        # Fixtures with known rule-based limitations get a lower bar
        if fixture.get("rulebased_known_limitation"):
            # Just log — these are the cases where Gemma should outperform
            pass
        else:
            assert metrics["recall"] >= 0.5, (
                f"{fixture['id']}: recall {metrics['recall']:.0%}, "
                f"missing: {[m['text_fragment'] for m in metrics['missing']]}"
            )

    def test_categories_valid(self, fixture):
        result = parse_eligibility_criteria(fixture["eligibility_text"])
        all_criteria = result.data["inclusion_criteria"] + result.data["exclusion_criteria"]
        for c in all_criteria:
            assert c["category"] in VALID_CATEGORIES, f"Invalid category '{c['category']}' in {fixture['id']}"


class TestRuleBasedParserAggregateMetrics:
    """Compute aggregate accuracy metrics across all fixtures."""

    def test_aggregate_recall(self):
        """Rule-based parser should find >= 60% of expected criteria overall."""
        total_expected = 0
        total_found = 0

        for fixture in EXTRACTION_FIXTURES:
            if not fixture["eligibility_text"]:
                continue
            result = parse_eligibility_criteria(fixture["eligibility_text"])
            all_criteria = result.data["inclusion_criteria"] + result.data["exclusion_criteria"]
            metrics = _check_expected_criteria(
                all_criteria,
                fixture["expected_criteria"],
                fixture["id"],
            )
            total_expected += metrics["expected"]
            total_found += metrics["found"]

        recall = total_found / total_expected if total_expected else 1.0
        assert recall >= 0.60, f"Aggregate recall {recall:.0%} is below 60% threshold ({total_found}/{total_expected})"

    def test_aggregate_category_accuracy(self):
        """Category classification should be >= 50% accurate on matched criteria."""
        total_checked = 0
        total_correct = 0

        for fixture in EXTRACTION_FIXTURES:
            if not fixture["eligibility_text"]:
                continue
            result = parse_eligibility_criteria(fixture["eligibility_text"])
            all_criteria = result.data["inclusion_criteria"] + result.data["exclusion_criteria"]
            cat_metrics = _check_category_accuracy(all_criteria, fixture["expected_criteria"])
            total_checked += cat_metrics["checked"]
            total_correct += cat_metrics["correct"]

        accuracy = total_correct / total_checked if total_checked else 1.0
        assert accuracy >= 0.50, (
            f"Category accuracy {accuracy:.0%} is below 50% threshold ({total_correct}/{total_checked})"
        )


class TestEmptyInput:
    """Edge case: empty eligibility text."""

    def test_rule_based_empty(self):
        result = parse_eligibility_criteria("")
        assert not result.success

    @pytest.mark.asyncio
    async def test_gemma_empty(self):
        result = await extract_criteria("")
        assert isinstance(result, ExtractedCriteria)
        assert len(result.criteria) == 0


class TestFixtureIntegrity:
    """Validate fixtures are well-formed."""

    def test_minimum_count(self):
        assert len(EXTRACTION_FIXTURES) >= 20

    def test_fixture_ids_unique(self):
        ids = [f["id"] for f in EXTRACTION_FIXTURES]
        assert len(ids) == len(set(ids))

    def test_expected_criteria_valid(self):
        for f in EXTRACTION_FIXTURES:
            for exp in f["expected_criteria"]:
                assert exp["type"] in ("inclusion", "exclusion"), f"Invalid type in {f['id']}: {exp['type']}"
                assert exp["category"] in VALID_CATEGORIES, f"Invalid category in {f['id']}: {exp['category']}"
                assert exp["text_fragment"], f"Empty text_fragment in {f['id']}"

    def test_covers_all_categories(self):
        categories_seen = set()
        for f in EXTRACTION_FIXTURES:
            for exp in f["expected_criteria"]:
                categories_seen.add(exp["category"])
        # Should cover the core categories
        core = {"diagnosis", "biomarker", "prior_therapy", "performance", "demographic", "comorbidity"}
        missing = core - categories_seen
        assert not missing, f"Fixtures missing coverage for categories: {missing}"


# ---------------------------------------------------------------------------
# Live Gemma extraction tests (skip in CI)
# ---------------------------------------------------------------------------


@pytest.mark.ollama
class TestGemmaExtractionLive:
    """Compare Gemma extraction quality against rule-based parser.

    Run with: pytest -m ollama eval/stage4/
    """

    @pytest.fixture(
        params=[f for f in EXTRACTION_FIXTURES if f["eligibility_text"]],
        ids=lambda f: f["id"],
    )
    def fixture(self, request):
        return request.param

    @pytest.mark.asyncio
    async def test_gemma_extracts_criteria(self, fixture):
        result = await extract_criteria(fixture["eligibility_text"])
        assert isinstance(result, ExtractedCriteria)
        assert len(result.criteria) > 0

    @pytest.mark.asyncio
    async def test_gemma_finds_expected_criteria(self, fixture):
        result = await extract_criteria(fixture["eligibility_text"])
        criteria_dicts = [{"type": c.type, "text": c.text, "category": c.category} for c in result.criteria]
        metrics = _check_expected_criteria(
            criteria_dicts,
            fixture["expected_criteria"],
            fixture["id"],
        )
        # Gemma should find >= 70% (higher bar than rule-based)
        assert metrics["recall"] >= 0.70, (
            f"{fixture['id']}: Gemma recall {metrics['recall']:.0%}, "
            f"missing: {[m['text_fragment'] for m in metrics['missing']]}"
        )

    @pytest.mark.asyncio
    async def test_gemma_category_accuracy(self, fixture):
        result = await extract_criteria(fixture["eligibility_text"])
        criteria_dicts = [{"type": c.type, "text": c.text, "category": c.category} for c in result.criteria]
        cat_metrics = _check_category_accuracy(criteria_dicts, fixture["expected_criteria"])
        # Gemma category accuracy should be >= 60%
        if cat_metrics["checked"] > 0:
            assert cat_metrics["accuracy"] >= 0.60, (
                f"{fixture['id']}: Gemma category accuracy {cat_metrics['accuracy']:.0%}"
            )

    @pytest.mark.asyncio
    async def test_gemma_vs_rulebased_comparison(self, fixture):
        """Compare Gemma vs rule-based on the same input. Log results."""
        # Gemma
        gemma_result = await extract_criteria(fixture["eligibility_text"])
        gemma_criteria = [{"type": c.type, "text": c.text, "category": c.category} for c in gemma_result.criteria]
        gemma_metrics = _check_expected_criteria(gemma_criteria, fixture["expected_criteria"], fixture["id"])

        # Rule-based
        rb_result = parse_eligibility_criteria(fixture["eligibility_text"])
        rb_criteria = rb_result.data["inclusion_criteria"] + rb_result.data["exclusion_criteria"]
        rb_metrics = _check_expected_criteria(rb_criteria, fixture["expected_criteria"], fixture["id"])

        # Log comparison (always passes — this is observational)
        print(
            f"\n  {fixture['id']}: "
            f"Gemma recall={gemma_metrics['recall']:.0%} ({gemma_metrics['found']}/{gemma_metrics['expected']}), "
            f"Rule-based recall={rb_metrics['recall']:.0%} ({rb_metrics['found']}/{rb_metrics['expected']})"
        )
