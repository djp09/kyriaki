"""Tool: Deterministic trial ranking using BM25 + rule-based features.

Replaces reliance on httpx race ordering for which trials enter the LLM
prescreen. Output is fully deterministic given the same inputs.

Score components per trial:
    +30  cancer_type match (binary)
    +25  biomarker–therapy alignment (binary)
    +15  BM25 over patient profile vs eligibility criteria (normalized 0–15)
    +10  phase weight (Phase 2/3=10, Phase 1/2=7, Phase 1=3)
     +5  prior-treatment line alignment

Trials failing cancer-type match are dropped (unless basket/umbrella).
Tiebreaker is always (-score, nct_id) for stable ordering.

Industry inspiration: TrialGPT (Google Research 2024) two-stage retrieval,
Anthropic Contextual Retrieval (Sept 2024) hybrid BM25 + rerank.
"""

from __future__ import annotations

import re

from logging_config import get_logger
from models import PatientProfile
from tools.trial_classifier import (
    cancer_type_matches,
    is_biomarker_aligned,
)

logger = get_logger("kyriaki.tools.deterministic_rank")


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer that preserves clinical terms.

    Uses ``\\w+`` to capture alphanumerics. Does NOT remove stopwords —
    "positive"/"negative" are clinically meaningful.
    """
    if not text:
        return []
    return re.findall(r"\w+", text.lower())


def _patient_query_terms(patient: PatientProfile) -> list[str]:
    """Build a query token list from the patient profile for BM25."""
    parts = [
        patient.cancer_type or "",
        patient.cancer_stage or "",
        " ".join(patient.biomarkers or []),
        " ".join(patient.prior_treatments or []),
        f"line {patient.lines_of_therapy}",
    ]
    return _tokenize(" ".join(parts))


def _phase_score(phase: str) -> float:
    """Map phase string to a small numeric weight."""
    phase_lower = (phase or "").lower()
    if "phase 3" in phase_lower or "phase iii" in phase_lower:
        return 10.0
    if "phase 2" in phase_lower or "phase ii" in phase_lower:
        return 9.0
    if "phase 1/2" in phase_lower or "phase i/ii" in phase_lower:
        return 7.0
    if "phase 1" in phase_lower or "phase i" in phase_lower:
        return 3.0
    return 5.0  # unknown phase


def _prior_treatment_alignment(patient: PatientProfile, trial: dict) -> float:
    """+5 if patient has 2+ prior lines AND trial mentions later-line eligibility."""
    if patient.lines_of_therapy < 2:
        return 0.0
    text = (
        (trial.get("brief_title") or "")
        + " "
        + (trial.get("brief_summary") or "")
        + " "
        + (trial.get("eligibility_criteria") or "")
    ).lower()
    if re.search(r"\b(refractory|relapsed|second[- ]line|2l|third[- ]line|3l|prior\s+therap|prior\s+treat)\b", text):
        return 5.0
    return 0.0


def rank_candidates(
    patient: PatientProfile,
    trials: list[dict],
    actionable_genes: set[str] | None = None,
) -> list[tuple[dict, float, dict]]:
    """Score and sort trials deterministically. Returns list of (trial, score, why).

    Trials failing cancer-type match are dropped. Output is sorted by
    (-score, nct_id) for stable ordering across runs.
    """
    if not trials:
        return []

    if actionable_genes is None:
        from tools.trial_classifier import patient_actionable_genes

        actionable_genes = patient_actionable_genes(patient.biomarkers or [])

    # Build BM25 corpus from eligibility criteria texts
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        BM25Okapi = None  # type: ignore[assignment]

    docs = [_tokenize(t.get("eligibility_criteria") or "") for t in trials]
    bm25_scores: list[float] = [0.0] * len(trials)
    if BM25Okapi is not None and any(docs):
        try:
            bm25 = BM25Okapi(docs)
            query = _patient_query_terms(patient)
            raw = bm25.get_scores(query)
            # Normalize to 0–15
            mx = max(raw) if len(raw) and max(raw) > 0 else 1.0
            bm25_scores = [(s / mx) * 15.0 for s in raw]
        except Exception as e:
            logger.warning("rank.bm25_failed", error=str(e))

    scored: list[tuple[dict, float, dict]] = []
    for i, trial in enumerate(trials):
        # Cancer type filter — drop if not matched
        ct_ok, ct_reason = cancer_type_matches(
            patient.cancer_type,
            trial.get("conditions") or [],
            trial.get("brief_title") or "",
        )
        if not ct_ok:
            logger.debug("rank.dropped_cancer_type", nct_id=trial.get("nct_id"), reason=ct_reason)
            continue

        ct_score = 30.0 if ct_ok else 0.0

        # Biomarker alignment
        bio_ok, bio_reason = is_biomarker_aligned(trial, actionable_genes)
        bio_score = 25.0 if bio_ok else 0.0

        # Targeted drug boost: +20 when trial's interventions explicitly
        # contain a drug from the patient's actionable gene's drug list.
        # This is strictly stronger than is_biomarker_aligned (which can
        # pass on text mentions alone), so the highest-quality matches
        # — actual targeted therapy trials — float to the top.
        targeted_boost = 0.0
        if actionable_genes:
            from trials_client import _GENE_TO_DRUGS

            interventions_text = " ".join(str(i) for i in (trial.get("interventions") or [])).lower()
            for gene in actionable_genes:
                for drug in _GENE_TO_DRUGS.get(gene, []):
                    if drug.lower() in interventions_text:
                        targeted_boost = 20.0
                        break
                if targeted_boost:
                    break

        # BM25
        bm25_component = bm25_scores[i] if i < len(bm25_scores) else 0.0

        # Phase
        phase_component = _phase_score(trial.get("phase", ""))

        # Prior therapy alignment
        prior_component = _prior_treatment_alignment(patient, trial)

        total = ct_score + bio_score + targeted_boost + bm25_component + phase_component + prior_component

        why = {
            "cancer_type": ct_score,
            "biomarker": bio_score,
            "targeted_boost": targeted_boost,
            "bm25": round(bm25_component, 2),
            "phase": phase_component,
            "prior_line": prior_component,
            "biomarker_reason": bio_reason,
        }
        scored.append((trial, total, why))

    # Stable sort: highest score first, ties broken by nct_id ascending
    scored.sort(key=lambda x: (-x[1], x[0].get("nct_id", "")))
    return scored
