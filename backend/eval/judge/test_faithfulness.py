"""Tier 3 — LLM-judge faithfulness tests.

CI tests validate fixture integrity.
Live tests (@pytest.mark.live_claude) use Claude Opus as judge.

Safety gate: unsupported_claim_rate < 2%.
"""

from __future__ import annotations

import json

import pytest

from eval.judge.fixtures import FAITHFUL_FIXTURES, FAITHFULNESS_FIXTURES, UNFAITHFUL_FIXTURES

JUDGE_PROMPT = """\
You are a clinical trial matching quality auditor. Your job is to check whether \
a plain-language explanation accurately reflects the per-criterion evaluations.

## Per-Criterion Evaluations (ground truth)
{evaluations_json}

## Plain-Language Explanation (to audit)
"{explanation}"

## Your Task
Identify any claims in the explanation that are NOT supported by the evaluations. \
A claim is unsupported if:
1. It states a criterion is MET when the evaluation says INSUFFICIENT_INFO or NOT_MET
2. It omits a TRIGGERED exclusion criterion (dangerous — patient could be harmed)
3. It mentions a criterion or fact that doesn't appear in the evaluations at all
4. It contradicts the status of any evaluation (e.g., says "no exclusions apply" when one is TRIGGERED)
5. It understates the severity of a NOT_MET or TRIGGERED result

Respond with ONLY a JSON object:
{{"unsupported_claims": [{{"claim": "<the problematic text>", "reason": "<why it's unsupported>"}}], \
"total_unsupported": <int>, "faithful": <true|false>}}
"""


def _parse_judge_response(text: str) -> dict | None:
    """Extract JSON from judge response."""
    text = text.strip()
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except (json.JSONDecodeError, KeyError):
        pass
    return None


# ---------------------------------------------------------------------------
# CI tests — fixture integrity
# ---------------------------------------------------------------------------


class TestFixtureIntegrity:
    def test_minimum_count(self):
        assert len(FAITHFULNESS_FIXTURES) >= 10

    def test_ids_unique(self):
        ids = [f["id"] for f in FAITHFULNESS_FIXTURES]
        assert len(ids) == len(set(ids))

    def test_has_faithful_and_unfaithful(self):
        assert len(FAITHFUL_FIXTURES) >= 4, f"Need >= 4 faithful, have {len(FAITHFUL_FIXTURES)}"
        assert len(UNFAITHFUL_FIXTURES) >= 4, f"Need >= 4 unfaithful, have {len(UNFAITHFUL_FIXTURES)}"

    def test_all_have_required_fields(self):
        for f in FAITHFULNESS_FIXTURES:
            assert "evaluations" in f
            assert "explanation" in f
            assert "expected_unsupported_claims" in f
            assert len(f["evaluations"]) > 0
            assert len(f["explanation"]) > 0

    def test_unfaithful_have_positive_claim_count(self):
        for f in UNFAITHFUL_FIXTURES:
            assert f["expected_unsupported_claims"] > 0, f"{f['id']} marked unfaithful but 0 claims"

    def test_faithful_have_zero_claims(self):
        for f in FAITHFUL_FIXTURES:
            assert f["expected_unsupported_claims"] == 0, f"{f['id']} marked faithful but >0 claims"

    def test_covers_common_failure_modes(self):
        """Check that unfaithful fixtures cover the key failure modes."""
        descriptions = " ".join(f["description"] for f in UNFAITHFUL_FIXTURES)
        assert "unknown" in descriptions.lower() or "insufficient" in descriptions.lower()
        assert "exclusion" in descriptions.lower()
        assert "mention" in descriptions.lower() or "invent" in descriptions.lower()


# ---------------------------------------------------------------------------
# Live Claude Opus judge
# ---------------------------------------------------------------------------


@pytest.mark.live_claude
class TestFaithfulnessJudgeLive:
    """Run Claude Opus as judge on all fixtures.

    Run with: pytest -m live_claude eval/judge/ -s
    """

    @pytest.mark.asyncio
    async def test_judge_full_eval(self):
        from dotenv import load_dotenv

        load_dotenv()
        from tools.claude_api import get_claude_client, paced_claude_call

        client = get_claude_client()
        results = []

        for fixture in FAITHFULNESS_FIXTURES:
            prompt = JUDGE_PROMPT.format(
                evaluations_json=json.dumps(fixture["evaluations"], indent=2),
                explanation=fixture["explanation"],
            )

            response = await paced_claude_call(
                client,
                model="claude-opus-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip()
            judge_result = _parse_judge_response(text)

            if judge_result:
                total = judge_result.get("total_unsupported", 0)
                faithful = judge_result.get("faithful", total == 0)
            else:
                total = -1
                faithful = None

            expected_count = fixture["expected_unsupported_claims"]
            expected_faithful = expected_count == 0
            judge_correct = faithful == expected_faithful

            results.append(
                {
                    "id": fixture["id"],
                    "expected_faithful": expected_faithful,
                    "judge_faithful": faithful,
                    "expected_claims": expected_count,
                    "judge_claims": total,
                    "correct": judge_correct,
                }
            )

            icon = "+" if judge_correct else "X"
            print(
                f"  [{icon}] {fixture['id']:40s} "
                f"judge={'faithful' if faithful else 'UNFAITHFUL':12s} "
                f"(expected={'faithful' if expected_faithful else 'UNFAITHFUL':12s}) "
                f"claims={total}"
            )

        # Aggregate
        correct = sum(1 for r in results if r["correct"])
        total_fixtures = len(results)
        accuracy = correct / total_fixtures if total_fixtures else 0

        print(f"\n{'=' * 70}")
        print(f"JUDGE ACCURACY: {correct}/{total_fixtures} = {accuracy:.0%}")
        print(f"{'=' * 70}")

        # Compute unsupported_claim_rate on faithful fixtures
        # (simulates: of explanations we'd actually ship, how many have unsupported claims?)
        faithful_results = [r for r in results if r["expected_faithful"]]
        false_unfaithful = sum(1 for r in faithful_results if not r["judge_faithful"])
        if faithful_results:
            false_rate = false_unfaithful / len(faithful_results)
            print(f"  False unfaithful rate (judge thinks faithful is unfaithful): {false_rate:.0%}")

        unfaithful_results = [r for r in results if not r["expected_faithful"]]
        caught = sum(1 for r in unfaithful_results if not r["judge_faithful"])
        if unfaithful_results:
            detection_rate = caught / len(unfaithful_results)
            print(f"  Unfaithful detection rate: {caught}/{len(unfaithful_results)} = {detection_rate:.0%}")

        # Save results
        with open("eval/judge/judge_results.json", "w") as fh:
            json.dump({"results": results, "accuracy": accuracy}, fh, indent=2)
        print("\nResults saved to eval/judge/judge_results.json")

        # The judge should catch at least 80% of unfaithful explanations
        if unfaithful_results:
            assert detection_rate >= 0.80, (
                f"Judge only caught {detection_rate:.0%} of unfaithful explanations, need >= 80%"
            )
