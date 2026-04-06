"""Head-to-head Gemma vs Claude on Stage 5 — criterion reasoning accuracy.

CI tests validate fixture integrity and per-category coverage.
Live tests run both models on the same criterion fixtures and compare accuracy.

Decision framework:
  - If Gemma accuracy is within 5% of Claude: recommend full migration
  - If gap is 5-10%: keep hybrid, consider fine-tuning Gemma
  - If gap is >10%: keep hybrid, document which criterion types Gemma fails on
"""

from __future__ import annotations

import json
import time

import pytest

from eval.head2head.fixtures import CRITERION_FIXTURES, FIXTURES_BY_CATEGORY

# ---------------------------------------------------------------------------
# Shared prompt for single-criterion evaluation
# ---------------------------------------------------------------------------

SINGLE_CRITERION_PROMPT = """\
You are an expert oncology clinical trial eligibility analyst. Evaluate whether \
the patient meets (or triggers) the following single eligibility criterion.

## Patient Data
{patient_json}

## Criterion
Type: {criterion_type}
Text: {criterion_text}

## Rules
- For INCLUSION criteria, respond with: MET, NOT_MET, or INSUFFICIENT_INFO
- For EXCLUSION criteria, respond with: TRIGGERED, NOT_TRIGGERED, or INSUFFICIENT_INFO
- MET = patient data explicitly satisfies this criterion
- NOT_MET = patient data explicitly contradicts this criterion
- TRIGGERED = patient has the excluding condition
- NOT_TRIGGERED = patient does NOT have the excluding condition
- INSUFFICIENT_INFO = not enough data to determine (do NOT guess)
- Drug name equivalence: Keytruda=Pembrolizumab, Tagrisso=Osimertinib, \
Lynparza=Olaparib, Opdivo=Nivolumab, etc.
- "FOLFOX" contains oxaliplatin (a platinum agent)
- Osimertinib is a 3rd-generation EGFR TKI
- Sotorasib is a KRAS G12C inhibitor
- Crizotinib is an ALK inhibitor
- Autologous stem cell transplant ≠ allogeneic stem cell transplant

## Output
Respond with ONLY a JSON object:
{{"status": "MET|NOT_MET|INSUFFICIENT_INFO|TRIGGERED|NOT_TRIGGERED", \
"confidence": "HIGH|MEDIUM|LOW", \
"reasoning": "<1-2 sentences>"}}
"""


def _parse_status_from_response(text: str) -> str | None:
    """Extract the status field from a JSON response."""
    text = text.strip()
    # Try JSON parse
    try:
        # Find JSON object in response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            return data.get("status")
    except (json.JSONDecodeError, KeyError):
        pass
    # Fallback: look for status keywords
    for status in ["MET", "NOT_MET", "INSUFFICIENT_INFO", "TRIGGERED", "NOT_TRIGGERED"]:
        if status in text:
            return status
    return None


def _build_prompt(fixture: dict) -> str:
    """Build the evaluation prompt for a fixture."""
    return SINGLE_CRITERION_PROMPT.format(
        patient_json=json.dumps(fixture["patient_snippet"], indent=2),
        criterion_type=fixture["criterion_type"],
        criterion_text=fixture["criterion_text"],
    )


# ---------------------------------------------------------------------------
# CI tests — fixture integrity and coverage
# ---------------------------------------------------------------------------


class TestFixtureIntegrity:
    """Validate fixture structure and diversity."""

    def test_minimum_count(self):
        assert len(CRITERION_FIXTURES) >= 50, f"Need >= 50 criterion fixtures, have {len(CRITERION_FIXTURES)}"

    def test_ids_unique(self):
        ids = [f["id"] for f in CRITERION_FIXTURES]
        assert len(ids) == len(set(ids))

    def test_all_have_required_fields(self):
        required = ["id", "category", "criterion_text", "criterion_type", "patient_snippet", "expected_status"]
        for f in CRITERION_FIXTURES:
            for field in required:
                assert field in f, f"Fixture {f['id']} missing field '{field}'"

    def test_valid_statuses(self):
        valid_inclusion = {"MET", "NOT_MET", "INSUFFICIENT_INFO"}
        valid_exclusion = {"TRIGGERED", "NOT_TRIGGERED", "INSUFFICIENT_INFO"}
        for f in CRITERION_FIXTURES:
            if f["criterion_type"] == "inclusion":
                assert f["expected_status"] in valid_inclusion, (
                    f"{f['id']}: inclusion status '{f['expected_status']}' not valid"
                )
            else:
                assert f["expected_status"] in valid_exclusion, (
                    f"{f['id']}: exclusion status '{f['expected_status']}' not valid"
                )

    def test_valid_categories(self):
        valid = {"simple", "multi_step", "drug_knowledge", "temporal", "negation"}
        for f in CRITERION_FIXTURES:
            assert f["category"] in valid, f"{f['id']}: category '{f['category']}' not valid"

    def test_category_coverage(self):
        """Each category should have at least 5 fixtures."""
        for cat, fixtures in FIXTURES_BY_CATEGORY.items():
            assert len(fixtures) >= 5, f"Category '{cat}' has {len(fixtures)} fixtures, need >= 5"

    def test_status_diversity(self):
        statuses = {f["expected_status"] for f in CRITERION_FIXTURES}
        assert "MET" in statuses or "TRIGGERED" in statuses
        assert "NOT_MET" in statuses or "NOT_TRIGGERED" in statuses
        assert "INSUFFICIENT_INFO" in statuses

    def test_inclusion_and_exclusion_types(self):
        types = {f["criterion_type"] for f in CRITERION_FIXTURES}
        assert "inclusion" in types
        assert "exclusion" in types


class TestCategoryDistribution:
    @pytest.fixture(params=list(FIXTURES_BY_CATEGORY.keys()))
    def category(self, request):
        return request.param

    def test_has_positive_and_negative_cases(self, category):
        fixtures = FIXTURES_BY_CATEGORY[category]
        positive = [f for f in fixtures if f["expected_status"] in ("MET", "NOT_TRIGGERED")]
        negative = [f for f in fixtures if f["expected_status"] in ("NOT_MET", "TRIGGERED")]
        assert len(positive) >= 1, f"Category '{category}' has no positive cases"
        assert len(negative) >= 1, f"Category '{category}' has no negative cases"


# ---------------------------------------------------------------------------
# Live Gemma test
# ---------------------------------------------------------------------------


@pytest.mark.ollama
class TestGemmaReasoningLive:
    """Test Gemma 4's criterion reasoning accuracy.

    Run with: pytest -m ollama eval/head2head/ -s
    """

    @pytest.fixture(params=CRITERION_FIXTURES, ids=lambda f: f["id"])
    def fixture(self, request):
        return request.param

    @pytest.mark.asyncio
    async def test_gemma_criterion_evaluation(self, fixture):
        from gemma_client import get_gemma_client

        client = get_gemma_client()
        prompt = _build_prompt(fixture)

        start = time.monotonic()
        response = await client.generate(prompt, max_tokens=512, temperature=0.1)
        elapsed = time.monotonic() - start

        status = _parse_status_from_response(response) or "PARSE_ERROR"
        expected = fixture["expected_status"]
        correct = status == expected

        print(
            f"\n  [{fixture['category']}] {fixture['id']}: "
            f"{'PASS' if correct else 'FAIL'} "
            f"(got={status}, expected={expected}, {elapsed:.1f}s)"
        )

        # Don't fail individual tests — we report aggregate accuracy
        # But DO record the result for the aggregate test
        fixture["_gemma_result"] = status
        fixture["_gemma_correct"] = correct
        fixture["_gemma_time"] = elapsed


@pytest.mark.ollama
class TestGemmaAggregateAccuracy:
    """Run ALL fixtures through Gemma and report aggregate accuracy.

    This is the authoritative Gemma accuracy measurement.
    Run with: pytest -m ollama eval/head2head/ -s -k TestGemmaAggregateAccuracy
    """

    @pytest.mark.asyncio
    async def test_gemma_full_eval(self):
        from gemma_client import get_gemma_client

        client = get_gemma_client()
        results = {"correct": 0, "total": 0, "by_category": {}, "failures": []}

        for fixture in CRITERION_FIXTURES:
            prompt = _build_prompt(fixture)
            start = time.monotonic()
            response = await client.generate(prompt, max_tokens=512, temperature=0.1)
            elapsed = time.monotonic() - start

            status = _parse_status_from_response(response) or "PARSE_ERROR"
            expected = fixture["expected_status"]
            correct = status == expected

            results["total"] += 1
            if correct:
                results["correct"] += 1
            else:
                results["failures"].append(
                    {"id": fixture["id"], "category": fixture["category"], "expected": expected, "got": status}
                )

            cat = fixture["category"]
            if cat not in results["by_category"]:
                results["by_category"][cat] = {"correct": 0, "total": 0}
            results["by_category"][cat]["total"] += 1
            if correct:
                results["by_category"][cat]["correct"] += 1

            icon = "+" if correct else "X"
            print(f"  [{icon}] {fixture['id']:40s} {status:20s} (expected {expected:20s}) {elapsed:.1f}s")

        # Print summary
        overall = results["correct"] / results["total"] if results["total"] else 0
        print(f"\n{'=' * 70}")
        print(f"GEMMA 4 ACCURACY: {results['correct']}/{results['total']} = {overall:.0%}")
        print(f"{'=' * 70}")
        for cat, data in sorted(results["by_category"].items()):
            acc = data["correct"] / data["total"] if data["total"] else 0
            print(f"  {cat:20s}: {data['correct']}/{data['total']} = {acc:.0%}")

        if results["failures"]:
            print(f"\nFAILURES ({len(results['failures'])}):")
            for f in results["failures"]:
                print(f"  [{f['category']}] {f['id']}: expected {f['expected']}, got {f['got']}")

        # Store for comparison
        results["_overall_accuracy"] = overall
        # Save to file for comparison
        with open("eval/head2head/gemma_results.json", "w") as fh:
            json.dump(results, fh, indent=2)
        print("\nResults saved to eval/head2head/gemma_results.json")


# ---------------------------------------------------------------------------
# Live Claude test
# ---------------------------------------------------------------------------


@pytest.mark.live_claude
class TestClaudeAggregateAccuracy:
    """Run ALL fixtures through Claude Sonnet and report aggregate accuracy.

    Run with: pytest -m live_claude eval/head2head/ -s -k TestClaudeAggregateAccuracy
    """

    @pytest.mark.asyncio
    async def test_claude_full_eval(self):
        from tools.claude_api import get_claude_client, paced_claude_call

        client = get_claude_client()
        results = {"correct": 0, "total": 0, "by_category": {}, "failures": []}

        for fixture in CRITERION_FIXTURES:
            prompt = _build_prompt(fixture)
            start = time.monotonic()
            response = await paced_claude_call(
                client,
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            elapsed = time.monotonic() - start

            text = response.content[0].text.strip()
            status = _parse_status_from_response(text) or "PARSE_ERROR"
            expected = fixture["expected_status"]
            correct = status == expected

            results["total"] += 1
            if correct:
                results["correct"] += 1
            else:
                results["failures"].append(
                    {"id": fixture["id"], "category": fixture["category"], "expected": expected, "got": status}
                )

            cat = fixture["category"]
            if cat not in results["by_category"]:
                results["by_category"][cat] = {"correct": 0, "total": 0}
            results["by_category"][cat]["total"] += 1
            if correct:
                results["by_category"][cat]["correct"] += 1

            icon = "+" if correct else "X"
            print(f"  [{icon}] {fixture['id']:40s} {status:20s} (expected {expected:20s}) {elapsed:.1f}s")

        # Print summary
        overall = results["correct"] / results["total"] if results["total"] else 0
        print(f"\n{'=' * 70}")
        print(f"CLAUDE SONNET ACCURACY: {results['correct']}/{results['total']} = {overall:.0%}")
        print(f"{'=' * 70}")
        for cat, data in sorted(results["by_category"].items()):
            acc = data["correct"] / data["total"] if data["total"] else 0
            print(f"  {cat:20s}: {data['correct']}/{data['total']} = {acc:.0%}")

        if results["failures"]:
            print(f"\nFAILURES ({len(results['failures'])}):")
            for f in results["failures"]:
                print(f"  [{f['category']}] {f['id']}: expected {f['expected']}, got {f['got']}")

        # Save for comparison
        with open("eval/head2head/claude_results.json", "w") as fh:
            json.dump(results, fh, indent=2)
        print("\nResults saved to eval/head2head/claude_results.json")

        # Compare with Gemma if results exist
        try:
            with open("eval/head2head/gemma_results.json") as fh:
                gemma = json.load(fh)
            gemma_acc = gemma.get("_overall_accuracy", 0)
            gap = overall - gemma_acc
            print(f"\n{'=' * 70}")
            print("HEAD-TO-HEAD COMPARISON")
            print(f"{'=' * 70}")
            print(f"  Claude Sonnet: {overall:.0%}")
            print(f"  Gemma 4:       {gemma_acc:.0%}")
            print(f"  Gap:           {gap:+.0%}")
            if abs(gap) <= 0.05:
                print("  RECOMMENDATION: Gap <= 5% — Gemma can replace Claude on Stage 5")
            elif abs(gap) <= 0.10:
                print("  RECOMMENDATION: Gap 5-10% — keep hybrid, consider fine-tuning Gemma")
            else:
                print("  RECOMMENDATION: Gap > 10% — keep hybrid, Claude needed for complex reasoning")

            # Per-category comparison
            print("\n  Per-category breakdown:")
            all_cats = set(list(results["by_category"].keys()) + list(gemma.get("by_category", {}).keys()))
            for cat in sorted(all_cats):
                c_data = results["by_category"].get(cat, {"correct": 0, "total": 0})
                g_data = gemma.get("by_category", {}).get(cat, {"correct": 0, "total": 0})
                c_acc = c_data["correct"] / c_data["total"] if c_data["total"] else 0
                g_acc = g_data["correct"] / g_data["total"] if g_data["total"] else 0
                delta = c_acc - g_acc
                print(f"    {cat:20s}: Claude {c_acc:.0%} vs Gemma {g_acc:.0%} (gap {delta:+.0%})")
        except FileNotFoundError:
            print("\n  (Run Gemma eval first for comparison: pytest -m ollama -k TestGemmaAggregateAccuracy)")
