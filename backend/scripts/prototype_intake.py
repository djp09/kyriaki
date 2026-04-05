"""Prototype: run Stage 1 intake normalization on sample inputs, report latency + reliability.

Per ADR-002 briefing: confirm Gemma latency + JSON output reliability BEFORE porting the rest.

Run from repo root:
    python -m backend.scripts.prototype_intake
"""

from __future__ import annotations

import asyncio
import time

from backend.gemma_client import GemmaSchemaError
from backend.intake import normalize_intake

SAMPLE_INPUTS: list[tuple[str, str, dict]] = [
    (
        "messy NSCLC w/ targeted therapy history",
        (
            "I'm 62, have stage 4 lung cancer (non small cell). "
            "They found I'm EGFR positive and PD-L1 is around 80%. "
            "I've been on Tagrisso for about a year, before that did carbo/pemetrexed. "
            "ECOG is 1. No other major health issues besides mild hypertension."
        ),
        {"sex": "female", "age": 62},
    ),
    (
        "TNBC with BRCA",
        (
            "54F, triple neg breast cancer stage IIIB, BRCA1+. "
            "Finished AC-T last year, now progressing. Performance status still good."
        ),
        {"sex": "female"},
    ),
    (
        "terse notes",
        "pt 48M, mCRC KRAS G12C, 2 prior lines (FOLFOX, then FOLFIRI+bev)",
        {"sex": "male", "age": 48},
    ),
    (
        "brand-name heavy",
        ("My dad has lung cancer — they said it's ALK-positive. He's taken Xalkori then Alecensa. He's 70."),
        {"sex": "male", "age": 70},
    ),
    (
        "ambiguous ECOG",
        (
            "45 year old with ovarian cancer, recurrent, BRCA2 mutation. "
            "Had Lynparza for 6 months. Mostly up and about but gets tired easily."
        ),
        {"sex": "female", "age": 45},
    ),
]


async def main() -> None:
    print("=" * 70)
    print("Stage 1 — Intake Normalization prototype (Gemma local)")
    print("=" * 70)

    successes = 0
    failures = 0
    latencies: list[float] = []

    for label, text, hints in SAMPLE_INPUTS:
        print(f"\n[{label}]")
        print(f"  input: {text[:100]}{'...' if len(text) > 100 else ''}")
        t0 = time.monotonic()
        try:
            result = await normalize_intake(text, form_hints=hints)
            elapsed = time.monotonic() - t0
            latencies.append(elapsed)
            successes += 1
            print(f"  OK ({elapsed:.1f}s)")
            print(f"    cancer_type: {result.cancer_type}")
            print(f"    cancer_stage: {result.cancer_stage}")
            print(f"    biomarkers: {result.biomarkers}")
            print(f"    prior_treatments: {result.prior_treatments}")
            print(f"    lines_of_therapy: {result.lines_of_therapy}")
            print(f"    ECOG: {result.ecog_score}")
            if result.normalization_notes:
                print(f"    notes: {result.normalization_notes}")
        except GemmaSchemaError as e:
            elapsed = time.monotonic() - t0
            latencies.append(elapsed)
            failures += 1
            print(f"  SCHEMA FAIL after {elapsed:.1f}s: {e}")
        except Exception as e:
            elapsed = time.monotonic() - t0
            failures += 1
            print(f"  ERROR after {elapsed:.1f}s: {type(e).__name__}: {e}")

    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    total = successes + failures
    print(f"  success rate:  {successes}/{total} ({100 * successes / total:.0f}%)")
    if latencies:
        print(
            f"  latency: min={min(latencies):.1f}s  "
            f"mean={sum(latencies) / len(latencies):.1f}s  max={max(latencies):.1f}s"
        )


if __name__ == "__main__":
    asyncio.run(main())
