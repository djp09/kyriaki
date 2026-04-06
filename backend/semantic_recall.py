"""Stage 3 — Semantic recall (local Gemma embeddings).

Embeds patient clinical summaries and trial descriptions, then cosine-ranks
candidate trials from the Stage 2 pre-filter. Runs entirely local via Gemma
embeddings through Ollama (dev) or Vertex (prod).

This stage narrows ~200 pre-filtered candidates to the top 30 most
semantically relevant trials before expensive per-criterion Claude analysis.
"""

from __future__ import annotations

import hashlib
import math

from gemma_client import get_gemma_client


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def text_hash(text: str) -> str:
    """SHA-256 hash for change detection on eligibility text."""
    return hashlib.sha256(text.encode()).hexdigest()


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using the configured Gemma embedding model.

    Args:
        texts: List of strings to embed.

    Returns:
        List of embedding vectors (768-dim for nomic-embed-text).
    """
    if not texts:
        return []
    client = get_gemma_client()
    return await client.embed(texts)


def build_patient_summary(patient: dict) -> str:
    """Build a de-identified clinical summary string for embedding.

    This summary is what gets embedded for cosine-similarity matching
    against trial embeddings. It intentionally omits direct identifiers
    (name, DOB, ZIP) — only clinical details relevant to trial matching.

    Args:
        patient: Dict with PatientProfile fields.

    Returns:
        Clinical summary string suitable for embedding.
    """
    parts = []
    if patient.get("cancer_type"):
        parts.append(patient["cancer_type"])
    if patient.get("cancer_stage"):
        parts.append(patient["cancer_stage"])
    if patient.get("biomarkers"):
        parts.append("Biomarkers: " + ", ".join(patient["biomarkers"]))
    if patient.get("prior_treatments"):
        lines = patient.get("lines_of_therapy", len(patient["prior_treatments"]))
        parts.append(f"Prior treatments ({lines} lines): " + ", ".join(patient["prior_treatments"]))
    if patient.get("ecog_score") is not None:
        parts.append(f"ECOG {patient['ecog_score']}")
    if patient.get("additional_conditions"):
        parts.append("Comorbidities: " + ", ".join(patient["additional_conditions"]))
    return ". ".join(parts) + "." if parts else ""


def build_trial_summary(trial: dict) -> str:
    """Build a summary string for a trial, suitable for embedding.

    Args:
        trial: Dict with trial fields (brief_title, conditions, phase, eligibility text).

    Returns:
        Trial summary string.
    """
    parts = []
    if trial.get("brief_title"):
        parts.append(trial["brief_title"])
    if trial.get("conditions"):
        conds = trial["conditions"] if isinstance(trial["conditions"], list) else [trial["conditions"]]
        parts.append("Conditions: " + ", ".join(conds))
    if trial.get("phase"):
        phase = trial["phase"] if isinstance(trial["phase"], str) else "/".join(trial["phase"])
        parts.append(f"Phase: {phase}")
    # Include a snippet of eligibility for semantic relevance
    elig = trial.get("eligibility_criteria") or trial.get("eligibility_text") or ""
    if elig:
        # First ~500 chars of eligibility text captures the key inclusion criteria
        parts.append("Eligibility: " + elig[:500])
    return ". ".join(parts) + "." if parts else ""


async def rank_trials_by_similarity(
    patient: dict,
    trials: list[dict],
    top_n: int = 30,
) -> list[tuple[dict, float]]:
    """Embed patient summary + trial summaries, return top N by cosine similarity.

    Args:
        patient: PatientProfile dict.
        trials: List of trial dicts from Stage 2 pre-filter.
        top_n: Number of top trials to return.

    Returns:
        List of (trial_dict, similarity_score) tuples, sorted descending.
    """
    if not trials:
        return []

    patient_summary = build_patient_summary(patient)
    trial_summaries = [build_trial_summary(t) for t in trials]

    # Embed patient + all trials in one batch for efficiency
    all_texts = [patient_summary] + trial_summaries
    embeddings = await embed_texts(all_texts)

    if len(embeddings) < 1 + len(trials):
        # Embedding failed for some texts — return trials unranked
        return [(t, 0.0) for t in trials[:top_n]]

    patient_embedding = embeddings[0]
    trial_embeddings = embeddings[1:]

    # Score and rank
    scored = []
    for trial, trial_emb in zip(trials, trial_embeddings):
        sim = _cosine_similarity(patient_embedding, trial_emb)
        scored.append((trial, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]
