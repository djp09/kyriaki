"""Prototype: run Stage 4 criterion extraction on real trial eligibility text.

Run from repo root:
    python -m backend.scripts.prototype_criterion
"""

from __future__ import annotations

import asyncio
import time

from backend.criterion_extraction import extract_criteria
from backend.gemma_client import GemmaSchemaError

# Real eligibility text samples from ClinicalTrials.gov
SAMPLE_CRITERIA: list[tuple[str, str]] = [
    (
        "NSCLC EGFR trial",
        """\
Inclusion Criteria:

1. Histologically or cytologically confirmed diagnosis of locally advanced or metastatic non-small cell lung cancer (Stage IIIB/IV)
2. Documented EGFR mutation (exon 19 deletion or L858R mutation)
3. Age >= 18 years
4. ECOG performance status 0-1
5. Adequate organ function defined as:
   - ANC >= 1500/uL
   - Platelets >= 100,000/uL
   - Hemoglobin >= 9.0 g/dL
   - Creatinine <= 1.5x ULN
   - AST/ALT <= 2.5x ULN (<=5x if liver metastases)
   - Total bilirubin <= 1.5x ULN
6. At least one measurable lesion per RECIST 1.1
7. Life expectancy >= 12 weeks
8. Written informed consent

Exclusion Criteria:

1. Prior treatment with a third-generation EGFR TKI (e.g., osimertinib)
2. Known ALK rearrangement or ROS1 fusion
3. Symptomatic CNS metastases; patients with stable, treated brain metastases are eligible
4. Active autoimmune disease requiring systemic treatment within the past 2 years
5. History of interstitial lung disease or pneumonitis requiring steroids
6. Active infection requiring IV antibiotics
7. Pregnant or breastfeeding
8. Prior solid organ transplant
""",
    ),
    (
        "TNBC immunotherapy",
        """\
Key Inclusion Criteria:
- Triple-negative breast cancer (ER-/PR-/HER2-) confirmed by local pathology
- Metastatic or locally advanced disease not amenable to curative surgery
- PD-L1 CPS >= 10 by approved assay
- No more than 2 prior lines of chemotherapy for metastatic disease
- ECOG 0-1
- Willing to undergo fresh tumor biopsy at screening

Key Exclusion Criteria:
- Prior treatment with anti-PD-1, anti-PD-L1, or anti-CTLA-4 antibodies
- Active hepatitis B or C
- Known HIV infection with detectable viral load
- Autoimmune disease requiring systemic immunosuppression
- Uncontrolled hypertension (systolic >160 mmHg)
- History of Grade 3 or higher immune-related adverse event from prior immunotherapy
""",
    ),
    (
        "no clear headers",
        """\
Patients must be >= 18 years of age with a confirmed diagnosis of advanced \
hepatocellular carcinoma (BCLC stage B or C). Prior sorafenib treatment \
is required. Patients must have Child-Pugh A liver function and ECOG 0-1. \
Patients with known fibrolamellar HCC, sarcomatoid HCC, or mixed \
hepatocholangiocarcinoma are not eligible. Active variceal bleeding within \
4 weeks is exclusionary.
""",
    ),
]


async def main() -> None:
    print("=" * 70)
    print("Stage 4 — Criterion Extraction prototype (Gemma local)")
    print("=" * 70)

    successes = 0
    failures = 0
    latencies: list[float] = []

    for label, text in SAMPLE_CRITERIA:
        print(f"\n[{label}]")
        t0 = time.monotonic()
        try:
            result = await extract_criteria(text)
            elapsed = time.monotonic() - t0
            latencies.append(elapsed)
            successes += 1
            inc = [c for c in result.criteria if c.type == "inclusion"]
            exc = [c for c in result.criteria if c.type == "exclusion"]
            print(f"  OK ({elapsed:.1f}s) — {len(inc)} inclusion, {len(exc)} exclusion")
            for c in result.criteria:
                print(f"    [{c.type[:3]}] ({c.category}) {c.text[:80]}")
            if result.extraction_notes:
                print(f"  notes: {result.extraction_notes}")
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
