"""Evaluation harness — measures matching quality across synthetic patients.

Runs each synthetic patient through the matching pipeline and measures:
1. Score distribution (are scores spread out, not clustered?)
2. Criterion-level accuracy (do MET/NOT_MET/INSUFFICIENT_INFO make sense?)
3. Tier distribution (do we get a mix of tiers?)
4. Category accuracy (are diagnosis/biomarker/demographic criteria correct?)
5. Per-patient cost, wall-clock, cache hit ratio (via metrics layer).

Usage:
    python3 -m eval.run_eval                    # all patients
    python3 -m eval.run_eval eval_nsclc_egfr    # single patient
    python3 -m eval.run_eval --quick            # first 3 patients only
    python3 -m eval.run_eval --quick --snapshot # also write to eval/baselines/
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import metrics as metrics_mod
from eval.synthetic_patients import SYNTHETIC_PATIENTS
from models import PatientProfile
from tools.criteria_parser import parse_eligibility_criteria
from tools.scoring import calculate_match_score
from trials_client import biomarker_search_terms, merge_and_deduplicate, search_trials


async def evaluate_patient(patient_data: dict, settings=None) -> dict:
    """Run a single patient through search + parse + evaluate + score.

    Returns evaluation metrics for this patient.
    """
    from prompts import ELIGIBILITY_USER_PROMPT
    from tools.claude_api import get_claude_client, paced_claude_call, parse_json_response

    if settings is None:
        from config import get_settings

        settings = get_settings()

    profile = PatientProfile(**patient_data["profile"])
    label = patient_data["label"]

    # Bracket this patient in its own metrics run so cost/cache/latency
    # land in the /api/metrics/recent stream with a tagged agent name.
    metrics_run = metrics_mod.start_run(agent=f"eval_{patient_data['id']}")
    print(f"\n{'=' * 60}")
    print(f"Patient: {label}")
    print(f"  Cancer: {profile.cancer_type}, {profile.cancer_stage}")
    print(f"  Biomarkers: {', '.join(profile.biomarkers) or 'None'}")
    print(f"  Prior tx: {', '.join(profile.prior_treatments) or 'None'} ({profile.lines_of_therapy} lines)")
    print(f"  Age/Sex: {profile.age}/{profile.sex}, ECOG: {profile.ecog_score}")

    # Step 1: Search for trials (biomarker-targeted + broad, matching the real pipeline)
    print(f"\n  Searching ClinicalTrials.gov...")
    start = time.monotonic()
    query_intr, query_term = biomarker_search_terms(profile.biomarkers or [])
    if query_intr:
        print(f"  Biomarker search: query_intr={query_intr}, query_term={query_term}")
        targeted, broad = await asyncio.gather(
            search_trials(
                profile.cancer_type,
                profile.age,
                profile.sex,
                page_size=20,
                query_intr=query_intr,
                query_term=query_term,
            ),
            search_trials(profile.cancer_type, profile.age, profile.sex, page_size=20),
        )
        trials = merge_and_deduplicate([targeted, broad])
    else:
        trials = await search_trials(profile.cancer_type, profile.age, profile.sex, page_size=20)
    search_time = time.monotonic() - start
    print(f"  Found {len(trials)} trials in {search_time:.1f}s")

    if not trials:
        metrics_mod.end_run()
        return {"patient_id": patient_data["id"], "label": label, "error": "No trials found", "trials_found": 0}

    # Step 2-4: Parse + Evaluate + Score each trial using the same
    # two-tier cached system prompt as production (matching_engine).
    from matching_engine import _build_eligibility_system_blocks

    system_blocks = _build_eligibility_system_blocks(profile)
    results = []

    for trial in trials[:10]:  # Eval top 10
        nct_id = trial["nct_id"]
        eligibility = trial["eligibility_criteria"]
        if len(eligibility) > 6000:
            eligibility = eligibility[:6000]

        # Parse
        parse_result = parse_eligibility_criteria(eligibility)
        if not parse_result.success or parse_result.data["total_criteria"] == 0:
            results.append({"nct_id": nct_id, "error": "parse_failed", "score": None})
            continue

        parsed = parse_result.data
        criteria_lines = []
        for c in parsed["inclusion_criteria"]:
            criteria_lines.append(f"[{c['id']}] INCLUSION ({c['category']}): {c['text']}")
        for c in parsed["exclusion_criteria"]:
            criteria_lines.append(f"[{c['id']}] EXCLUSION ({c['category']}): {c['text']}")

        user_msg = ELIGIBILITY_USER_PROMPT.format(
            nct_id=nct_id,
            brief_title=trial["brief_title"],
            phase=trial["phase"],
            brief_summary=trial["brief_summary"],
            parsed_criteria="\n".join(criteria_lines),
        )

        try:
            response = await paced_claude_call(
                get_claude_client(),
                model=settings.claude_model,
                max_tokens=min(1800, max(1000, len(criteria_lines) * 80)),
                messages=[{"role": "user", "content": user_msg}],
                system=system_blocks,
                temperature=0.0,
            )
            text = response.content[0].text.strip()
            eval_result = parse_json_response(text)
        except Exception as e:
            results.append({"nct_id": nct_id, "error": f"api_error: {e}", "score": None})
            continue

        compact_evals = (eval_result or {}).get("evals") or (eval_result or {}).get("criterion_evaluations") or []
        if not compact_evals:
            results.append({"nct_id": nct_id, "error": "no_evaluations", "score": None})
            continue

        # Hydrate compact eval response with parser metadata so scoring +
        # downstream metrics work the same as before the schema compaction.
        parsed_by_id = {}
        for c in parsed["inclusion_criteria"]:
            parsed_by_id[c["id"]] = {**c, "type": "inclusion"}
        for c in parsed["exclusion_criteria"]:
            parsed_by_id[c["id"]] = {**c, "type": "exclusion"}

        evals = []
        for ev in compact_evals:
            cid = ev.get("id") or ev.get("criterion_id") or ""
            parsed_c = parsed_by_id.get(cid)
            if parsed_c is None:
                continue
            evals.append(
                {
                    "criterion_id": cid,
                    "criterion_text": parsed_c.get("text", ""),
                    "type": parsed_c.get("type", "inclusion"),
                    "category": parsed_c.get("category", "other"),
                    "status": ev.get("status", "INSUFFICIENT_INFO"),
                    "confidence": ev.get("confidence", "MEDIUM"),
                    "reasoning": ev.get("reason") or ev.get("reasoning") or "",
                }
            )
        if not evals:
            results.append({"nct_id": nct_id, "error": "no_valid_evals", "score": None})
            continue

        flags = eval_result.get("flags") or eval_result.get("flags_for_oncologist") or []

        # Score
        score_result = calculate_match_score(evals, flags)

        trial_result = {
            "nct_id": nct_id,
            "brief_title": trial["brief_title"][:60],
            "score": score_result["score"],
            "tier": score_result["tier"],
            "criteria_met": score_result["criteria_met"],
            "criteria_not_met": score_result["criteria_not_met"],
            "criteria_unknown": score_result["criteria_unknown"],
            "criteria_total": score_result["criteria_total"],
            "parsed_inclusion": len(parsed["inclusion_criteria"]),
            "parsed_exclusion": len(parsed["exclusion_criteria"]),
            "evaluations": evals,
        }
        results.append(trial_result)

        status_icon = {
            "STRONG_MATCH": "+",
            "POTENTIAL_MATCH": "~",
            "PARTIAL_MATCH": "?",
            "UNLIKELY_MATCH": "-",
            "EXCLUDED": "X",
        }.get(score_result["tier"], "?")

        print(
            f"  [{status_icon}] {nct_id} score={score_result['score']:5.1f} "
            f"tier={score_result['tier']:15s} "
            f"met={score_result['criteria_met']}/{score_result['criteria_total']} "
            f"| {trial['brief_title'][:50]}"
        )

    metrics_mod.end_run()
    return _compute_patient_metrics(patient_data, results, metrics_run)


def _compute_patient_metrics(patient_data: dict, results: list[dict], run=None) -> dict:
    """Compute metrics for a single patient's evaluation run."""
    scores = [r["score"] for r in results if r.get("score") is not None]
    tiers = [r["tier"] for r in results if r.get("tier")]
    errors = [r for r in results if r.get("error")]

    metrics = {
        "patient_id": patient_data["id"],
        "label": patient_data["label"],
        "trials_evaluated": len(results),
        "eval_errors": len(errors),
        "scores": scores,
    }

    if run is not None:
        metrics["cost_usd"] = round(run.total_cost_usd, 4)
        metrics["wall_ms"] = round(run.wall_ms, 1)
        metrics["claude_calls"] = len(run.calls)
        metrics["total_input_tokens"] = run.total_input_tokens
        metrics["total_output_tokens"] = run.total_output_tokens
        metrics["cache_hit_ratio"] = round(run.cache_hit_ratio, 3)

    if scores:
        metrics["score_min"] = min(scores)
        metrics["score_max"] = max(scores)
        metrics["score_mean"] = round(statistics.mean(scores), 1)
        metrics["score_stdev"] = round(statistics.stdev(scores), 1) if len(scores) > 1 else 0
        metrics["score_spread"] = round(max(scores) - min(scores), 1)
    else:
        metrics["score_min"] = metrics["score_max"] = metrics["score_mean"] = 0
        metrics["score_stdev"] = metrics["score_spread"] = 0

    # Tier distribution
    tier_counts = {}
    for t in tiers:
        tier_counts[t] = tier_counts.get(t, 0) + 1
    metrics["tier_distribution"] = tier_counts

    # Criterion-level stats across all trials
    all_statuses = []
    for r in results:
        for e in r.get("evaluations", []):
            all_statuses.append(e.get("status", ""))
    status_counts = {}
    for s in all_statuses:
        status_counts[s] = status_counts.get(s, 0) + 1
    metrics["criterion_status_distribution"] = status_counts

    # Check expected criteria accuracy
    expected = patient_data.get("expected_good_criteria", {})
    if expected:
        correct = 0
        checked = 0
        for r in results:
            for e in r.get("evaluations", []):
                cat = e.get("category", "")
                if cat in expected:
                    checked += 1
                    if e.get("status") == expected[cat]:
                        correct += 1
        metrics["expected_criteria_checked"] = checked
        metrics["expected_criteria_correct"] = correct
        metrics["expected_criteria_accuracy"] = round(correct / checked, 3) if checked > 0 else None

    return metrics


def print_summary(all_metrics: list[dict]):
    """Print aggregate evaluation summary."""
    print(f"\n{'=' * 60}")
    print("EVALUATION SUMMARY")
    print(f"{'=' * 60}")
    print(f"Patients evaluated: {len(all_metrics)}")

    all_scores = []
    all_spreads = []
    total_criteria_checked = 0
    total_criteria_correct = 0

    for m in all_metrics:
        all_scores.extend(m.get("scores", []))
        if m.get("score_spread"):
            all_spreads.append(m["score_spread"])
        total_criteria_checked += m.get("expected_criteria_checked", 0)
        total_criteria_correct += m.get("expected_criteria_correct", 0)

        print(
            f"\n  {m['label']}:"
            f"\n    Scores: min={m['score_min']}, max={m['score_max']}, "
            f"mean={m['score_mean']}, stdev={m['score_stdev']}, spread={m['score_spread']}"
            f"\n    Tiers: {m.get('tier_distribution', {})}"
            f"\n    Criterion statuses: {m.get('criterion_status_distribution', {})}"
        )
        if m.get("expected_criteria_accuracy") is not None:
            print(
                f"    Expected criteria accuracy: {m['expected_criteria_accuracy']:.1%} ({m['expected_criteria_correct']}/{m['expected_criteria_checked']})"
            )

    print(f"\n{'=' * 60}")
    print("AGGREGATE METRICS")
    print(f"{'=' * 60}")

    if all_scores:
        print(f"  Total trials scored: {len(all_scores)}")
        print(f"  Score range: {min(all_scores):.1f} — {max(all_scores):.1f}")
        print(f"  Score mean: {statistics.mean(all_scores):.1f}")
        print(f"  Score stdev: {statistics.stdev(all_scores):.1f}" if len(all_scores) > 1 else "")
        print(f"  Score median: {statistics.median(all_scores):.1f}")

        # Score distribution buckets
        buckets = {"0-19": 0, "20-39": 0, "40-59": 0, "60-79": 0, "80-100": 0}
        for s in all_scores:
            if s < 20:
                buckets["0-19"] += 1
            elif s < 40:
                buckets["20-39"] += 1
            elif s < 60:
                buckets["40-59"] += 1
            elif s < 80:
                buckets["60-79"] += 1
            else:
                buckets["80-100"] += 1
        print(f"  Score distribution: {buckets}")

    if all_spreads:
        print(f"  Mean per-patient score spread: {statistics.mean(all_spreads):.1f}")

    if total_criteria_checked > 0:
        accuracy = total_criteria_correct / total_criteria_checked
        print(f"\n  Expected criteria accuracy: {accuracy:.1%} ({total_criteria_correct}/{total_criteria_checked})")
        if accuracy >= 0.85:
            print("  *** PASSES Phase 1 gate (>85% criterion accuracy) ***")
        else:
            print(f"  *** Below Phase 1 gate (need {0.85:.0%}, got {accuracy:.0%}) ***")

    # Check differentiation
    if all_spreads:
        avg_spread = statistics.mean(all_spreads)
        if avg_spread >= 30:
            print("  *** GOOD differentiation (avg spread >= 30) ***")
        else:
            print(f"  *** POOR differentiation (avg spread = {avg_spread:.1f}, need >= 30) ***")


def _aggregate_totals(all_metrics: list[dict]) -> dict:
    """Roll up per-patient metrics into a single baseline snapshot."""
    cost_total = sum(m.get("cost_usd", 0.0) or 0.0 for m in all_metrics)
    wall_total_ms = sum(m.get("wall_ms", 0.0) or 0.0 for m in all_metrics)
    claude_calls = sum(m.get("claude_calls", 0) or 0 for m in all_metrics)
    input_tokens = sum(m.get("total_input_tokens", 0) or 0 for m in all_metrics)
    output_tokens = sum(m.get("total_output_tokens", 0) or 0 for m in all_metrics)
    cache_hit_ratios = [m["cache_hit_ratio"] for m in all_metrics if "cache_hit_ratio" in m]
    all_scores = []
    for m in all_metrics:
        all_scores.extend(m.get("scores") or [])
    return {
        "patient_count": len(all_metrics),
        "total_cost_usd": round(cost_total, 4),
        "avg_cost_per_patient_usd": round(cost_total / len(all_metrics), 4) if all_metrics else 0.0,
        "total_wall_ms": round(wall_total_ms, 1),
        "avg_wall_ms_per_patient": round(wall_total_ms / len(all_metrics), 1) if all_metrics else 0.0,
        "total_claude_calls": claude_calls,
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "avg_cache_hit_ratio": round(sum(cache_hit_ratios) / len(cache_hit_ratios), 3) if cache_hit_ratios else 0.0,
        "score_count": len(all_scores),
        "score_mean": round(statistics.mean(all_scores), 1) if all_scores else 0.0,
        "score_stdev": round(statistics.stdev(all_scores), 1) if len(all_scores) > 1 else 0.0,
        "score_median": round(statistics.median(all_scores), 1) if all_scores else 0.0,
        "score_min": round(min(all_scores), 1) if all_scores else 0.0,
        "score_max": round(max(all_scores), 1) if all_scores else 0.0,
    }


async def main():
    patients = SYNTHETIC_PATIENTS
    snapshot_mode = "--snapshot" in sys.argv
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]

    # Filter by patient ID if specified
    if positional:
        patient_id = positional[0]
        patients = [p for p in patients if p["id"] == patient_id]
        if not patients:
            print(f"Patient '{patient_id}' not found. Available:")
            for p in SYNTHETIC_PATIENTS:
                print(f"  {p['id']}: {p['label']}")
            sys.exit(1)

    if "--quick" in sys.argv:
        patients = patients[:3]

    print("Kyriaki Matching Evaluation")
    print(f"Patients: {len(patients)}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")

    all_metrics = []
    for patient in patients:
        try:
            patient_metrics = await evaluate_patient(patient)
            all_metrics.append(patient_metrics)
        except Exception as e:
            print(f"\n  ERROR evaluating {patient['id']}: {type(e).__name__}: {e}")
            all_metrics.append(
                {
                    "patient_id": patient["id"],
                    "label": patient["label"],
                    "error": str(e),
                    "scores": [],
                    "score_min": 0,
                    "score_max": 0,
                    "score_mean": 0,
                    "score_stdev": 0,
                    "score_spread": 0,
                }
            )

    print_summary(all_metrics)
    totals = _aggregate_totals(all_metrics)

    # Save latest run
    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "patients": len(patients),
        "totals": totals,
        "metrics": all_metrics,
    }
    with open("eval/last_run.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print("\nResults saved to eval/last_run.json")
    print(
        f"\nTotals: ${totals['total_cost_usd']} total / ${totals['avg_cost_per_patient_usd']}/patient, "
        f"{totals['total_claude_calls']} calls, cache hit {totals['avg_cache_hit_ratio']:.1%}"
    )

    if snapshot_mode:
        baselines_dir = Path("eval/baselines")
        baselines_dir.mkdir(parents=True, exist_ok=True)
        date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        suffix = "-quick" if "--quick" in sys.argv else ""
        baseline_path = baselines_dir / f"{date_tag}{suffix}.json"
        with baseline_path.open("w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"Baseline saved to {baseline_path}")


if __name__ == "__main__":
    asyncio.run(main())
