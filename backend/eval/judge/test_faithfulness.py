"""Tier 3 LLM-judge tests — faithfulness of Stage 6 explanations.

CI tests use frozen fixtures (no API calls).
Live tests (@pytest.mark.live_claude) call the running backend + Opus judge.

Gate: unsupported_claim_rate < 2%.

Usage:
    pytest eval/judge/test_faithfulness.py -v              # CI only (frozen)
    pytest -m live_claude eval/judge/test_faithfulness.py -s  # live judge
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from eval.judge.faithfulness import judge_explanation

# ---------------------------------------------------------------------------
# Frozen fixtures for CI
# ---------------------------------------------------------------------------

FROZEN_MATCH = {
    "nct_id": "NCT00000001",
    "match_score": 72,
    "match_explanation": (
        "You appear to be a strong candidate for this trial. Your EGFR mutation "
        "status meets the biomarker requirement, and your diagnosis of Stage IV "
        "NSCLC aligns with the study's target population. Your ECOG performance "
        "status of 1 is within the acceptable range. We recommend discussing this "
        "trial with your oncologist."
    ),
    "evaluations": [
        {
            "criterion_id": "I1",
            "type": "inclusion",
            "category": "diagnosis",
            "status": "MET",
            "confidence": "HIGH",
            "criterion_text": "Histologically confirmed Stage IIIB/IV NSCLC",
            "reasoning": "Patient has Stage IV NSCLC.",
        },
        {
            "criterion_id": "I2",
            "type": "inclusion",
            "category": "biomarker",
            "status": "MET",
            "confidence": "HIGH",
            "criterion_text": "EGFR activating mutation (exon 19 del or L858R)",
            "reasoning": "Patient is EGFR+.",
        },
        {
            "criterion_id": "I3",
            "type": "inclusion",
            "category": "performance",
            "status": "MET",
            "confidence": "HIGH",
            "criterion_text": "ECOG performance status 0-1",
            "reasoning": "Patient ECOG is 1.",
        },
        {
            "criterion_id": "E1",
            "type": "exclusion",
            "category": "comorbidity",
            "status": "NOT_TRIGGERED",
            "confidence": "MEDIUM",
            "criterion_text": "Active brain metastases",
            "reasoning": "No mention of brain metastases in patient profile.",
        },
    ],
}

FROZEN_UNFAITHFUL_MATCH = {
    "nct_id": "NCT00000002",
    "match_score": 65,
    "match_explanation": (
        "Your PD-L1 expression of 80% meets the trial's biomarker threshold, "
        "and your prior immunotherapy response suggests you could benefit from "
        "this combination therapy approach."
    ),
    "evaluations": [
        {
            "criterion_id": "I1",
            "type": "inclusion",
            "category": "diagnosis",
            "status": "MET",
            "confidence": "HIGH",
            "criterion_text": "Advanced NSCLC",
            "reasoning": "Patient has Stage IV NSCLC.",
        },
        {
            "criterion_id": "I2",
            "type": "inclusion",
            "category": "biomarker",
            "status": "INSUFFICIENT_INFO",
            "confidence": "LOW",
            "criterion_text": "PD-L1 TPS >= 50%",
            "reasoning": "Patient reports PD-L1 80% but lab confirmation not available.",
        },
    ],
}


# ---------------------------------------------------------------------------
# CI tests (frozen — no API calls)
# ---------------------------------------------------------------------------


class TestFrozenFixtures:
    """Validate fixture integrity without calling any LLM."""

    def test_faithful_fixture_has_supporting_evals(self):
        """The faithful fixture's explanation should reference criteria that exist."""
        evals = FROZEN_MATCH["evaluations"]
        categories = {e["category"] for e in evals}
        explanation = FROZEN_MATCH["match_explanation"].lower()
        assert "egfr" in explanation
        assert "biomarker" in categories
        assert "diagnosis" in categories

    def test_unfaithful_fixture_has_claim_gap(self):
        """The unfaithful fixture claims PD-L1 'meets' but eval is INSUFFICIENT_INFO."""
        evals = FROZEN_UNFAITHFUL_MATCH["evaluations"]
        pdl1_eval = next(e for e in evals if "PD-L1" in e["criterion_text"])
        assert pdl1_eval["status"] == "INSUFFICIENT_INFO"
        assert "meets" in FROZEN_UNFAITHFUL_MATCH["match_explanation"].lower()

    def test_format_evaluations_coverage(self):
        from eval.judge.faithfulness import _format_evaluations

        text = _format_evaluations(FROZEN_MATCH["evaluations"])
        assert "I1" in text
        assert "NSCLC" in text
        assert "MET" in text


# ---------------------------------------------------------------------------
# Live tests — require API key + running backend
# ---------------------------------------------------------------------------

BACKEND_URL = "http://localhost:8000/api"

# Synthetic NSCLC patient for live matching
LIVE_PATIENT = {
    "cancer_type": "Non-Small Cell Lung Cancer",
    "cancer_stage": "Stage IV",
    "biomarkers": ["EGFR+", "PD-L1 80%"],
    "prior_treatments": ["Carboplatin/Pemetrexed"],
    "lines_of_therapy": 1,
    "age": 58,
    "sex": "female",
    "ecog_score": 1,
    "key_labs": {"wbc": 5.2, "platelets": 180, "hemoglobin": 12.0, "creatinine": 0.9},
    "location_zip": "10001",
    "willing_to_travel_miles": 100,
    "additional_conditions": [],
    "additional_notes": None,
}


async def _run_match_and_wait(patient: dict, timeout: float = 180) -> dict:
    """Submit a match request to the running backend and poll until done."""
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=30.0) as client:
        resp = await client.post("/agents/match", json={"patient": patient, "max_results": 10})
        resp.raise_for_status()
        task = resp.json()

        if task.get("status") == "completed":
            return task

        task_id = task["task_id"]
        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(3)
            elapsed += 3
            resp = await client.get(f"/agents/tasks/{task_id}")
            resp.raise_for_status()
            task = resp.json()
            if task["status"] in ("completed", "failed"):
                break

        assert task["status"] == "completed", f"Task ended with status: {task['status']}"
        return task


def _extract_judgeable_matches(task: dict) -> list[dict]:
    """Extract matches with both evaluations and explanations for judging."""
    output = task.get("output_data", {})
    matches = output.get("matches", [])
    judgeable = []
    for m in matches:
        explanation = m.get("match_explanation", "")
        inc_evals = m.get("inclusion_evaluations", [])
        exc_evals = m.get("exclusion_evaluations", [])
        all_evals = []
        for i, e in enumerate(inc_evals):
            all_evals.append({
                "criterion_id": f"I{i + 1}",
                "type": "inclusion",
                "category": e.get("category", "other"),
                "status": e.get("status", "INSUFFICIENT_INFO"),
                "confidence": e.get("confidence", "MEDIUM"),
                "criterion_text": e.get("criterion", ""),
                "reasoning": e.get("explanation", ""),
            })
        for i, e in enumerate(exc_evals):
            all_evals.append({
                "criterion_id": f"E{i + 1}",
                "type": "exclusion",
                "category": e.get("category", "other"),
                "status": e.get("status", "INSUFFICIENT_INFO"),
                "confidence": e.get("confidence", "MEDIUM"),
                "criterion_text": e.get("criterion", ""),
                "reasoning": e.get("explanation", ""),
            })
        if explanation and all_evals:
            judgeable.append({
                "nct_id": m.get("nct_id", "?"),
                "match_score": m.get("match_score", 0),
                "explanation": explanation,
                "evaluations": all_evals,
            })
    return judgeable


@pytest.mark.live_claude
class TestLiveFaithfulness:
    """Run the full pipeline: backend match → Opus judge → gate check."""

    @pytest.fixture(scope="class")
    def match_task(self):
        """Run one match against the live backend (shared across tests)."""
        return asyncio.get_event_loop().run_until_complete(
            _run_match_and_wait(LIVE_PATIENT)
        )

    @pytest.fixture(scope="class")
    def judgeable_matches(self, match_task):
        matches = _extract_judgeable_matches(match_task)
        assert len(matches) > 0, "No judgeable matches returned from backend"
        return matches

    @pytest.fixture(scope="class")
    def judge_results(self, judgeable_matches):
        """Run Opus judge on each match (expensive — cached at class scope)."""
        async def _judge_all():
            results = []
            for m in judgeable_matches:
                result = await judge_explanation(m["evaluations"], m["explanation"])
                result["nct_id"] = m["nct_id"]
                result["match_score"] = m["match_score"]
                results.append(result)
            return results

        return asyncio.get_event_loop().run_until_complete(_judge_all())

    def test_judge_returns_valid_results(self, judge_results):
        """Most judge results should parse successfully."""
        parse_errors = [r for r in judge_results if r.get("parse_error")]
        valid = [r for r in judge_results if not r.get("parse_error")]
        assert len(valid) > 0, "All judge calls failed to parse"
        # Allow up to 1 parse failure — LLM output is occasionally malformed
        assert len(parse_errors) <= 1, (
            f"{len(parse_errors)} parse errors: "
            f"{[r.get('nct_id') for r in parse_errors]}"
        )
        for r in valid:
            assert "claims" in r, f"Missing claims for {r.get('nct_id')}"
            assert "total_claims" in r
            assert "unsupported_count" in r

    def test_unsupported_claim_rate_below_gate(self, judge_results):
        """Gate: unsupported_claim_rate < 2%."""
        valid = [r for r in judge_results if not r.get("parse_error")]
        total_claims = sum(r["total_claims"] for r in valid)
        total_unsupported = sum(r["unsupported_count"] for r in valid)

        if total_claims == 0:
            pytest.skip("No claims to evaluate")
        if total_claims < 10:
            pytest.skip(
                f"Too few claims ({total_claims}) for reliable gate — "
                f"need at least 10. Try increasing max_results."
            )

        rate = total_unsupported / total_claims
        print(f"\n  Faithfulness results:")
        print(f"    Total matches judged: {len(judge_results)}")
        print(f"    Total claims: {total_claims}")
        print(f"    Unsupported claims: {total_unsupported}")
        print(f"    Unsupported claim rate: {rate:.1%}")
        print(f"    Gate threshold: < 2%")

        for r in judge_results:
            nct = r.get("nct_id", "?")
            score = r.get("match_score", "?")
            unsup = r["unsupported_count"]
            total = r["total_claims"]
            print(f"    {nct} (score={score}): {unsup}/{total} unsupported")
            if unsup > 0:
                for c in r.get("claims", []):
                    if c.get("verdict") == "UNSUPPORTED":
                        print(f"      - \"{c['claim_text']}\" → {c['reason']}")

        assert rate < 0.02, (
            f"Unsupported claim rate {rate:.1%} exceeds 2% gate "
            f"({total_unsupported}/{total_claims})"
        )

    def test_no_match_has_majority_unsupported(self, judge_results):
        """No single match should have > 50% unsupported claims."""
        for r in judge_results:
            total = r["total_claims"]
            unsupported = r["unsupported_count"]
            if total > 0:
                rate = unsupported / total
                assert rate <= 0.5, (
                    f"{r.get('nct_id')}: {rate:.0%} unsupported "
                    f"({unsupported}/{total})"
                )
