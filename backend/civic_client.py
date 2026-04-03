"""CIViC API client — biomarker actionability lookups.

CIViC (Clinical Interpretation of Variants in Cancer) provides structured,
peer-reviewed evidence linking cancer variants to therapeutic implications.

This bridges the gap between free-text biomarker reports from patients
(e.g., "EGFR+", "PD-L1 80%") and the structured evidence needed for
intelligent trial matching.

API docs: https://civicdb.org/api
GraphQL endpoint: https://civicdb.org/api/graphql
No API key required. Open-source database.
"""

from __future__ import annotations

import time

import httpx

from logging_config import get_logger

logger = get_logger("kyriaki.civic")

GRAPHQL_URL = "https://civicdb.org/api/graphql"

# In-memory cache: query_key -> (timestamp, data)
_civic_cache: dict[str, tuple[float, list[VariantEvidence]]] = {}
_CACHE_TTL = 3600  # 1 hour — CIViC updates infrequently

# Common biomarker aliases → CIViC gene names
_BIOMARKER_GENES: dict[str, str] = {
    "egfr": "EGFR",
    "egfr+": "EGFR",
    "egfr-": "EGFR",
    "egfr positive": "EGFR",
    "egfr negative": "EGFR",
    "egfr l858r": "EGFR",
    "egfr t790m": "EGFR",
    "egfr exon 19 deletion": "EGFR",
    "egfr exon 20 insertion": "EGFR",
    "alk": "ALK",
    "alk+": "ALK",
    "alk-": "ALK",
    "alk positive": "ALK",
    "alk negative": "ALK",
    "alk rearrangement": "ALK",
    "alk fusion": "ALK",
    "ros1": "ROS1",
    "ros1+": "ROS1",
    "ros1 fusion": "ROS1",
    "ros1 rearrangement": "ROS1",
    "her2": "ERBB2",
    "her2+": "ERBB2",
    "her2-": "ERBB2",
    "her2 positive": "ERBB2",
    "her2 negative": "ERBB2",
    "erbb2": "ERBB2",
    "pd-l1": "CD274",
    "pdl1": "CD274",
    "pd-l1 positive": "CD274",
    "braf": "BRAF",
    "braf v600e": "BRAF",
    "braf v600k": "BRAF",
    "braf+": "BRAF",
    "kras": "KRAS",
    "kras g12c": "KRAS",
    "kras+": "KRAS",
    "kras-": "KRAS",
    "brca1": "BRCA1",
    "brca2": "BRCA2",
    "brca1/2": "BRCA1",
    "brca": "BRCA1",
    "ntrk": "NTRK1",
    "ntrk fusion": "NTRK1",
    "ntrk1": "NTRK1",
    "ntrk2": "NTRK2",
    "ntrk3": "NTRK3",
    "met": "MET",
    "met amplification": "MET",
    "met exon 14": "MET",
    "ret": "RET",
    "ret fusion": "RET",
    "ret rearrangement": "RET",
    "pik3ca": "PIK3CA",
    "tp53": "TP53",
    "p53": "TP53",
    "msi-h": "MSH2",
    "msi high": "MSH2",
    "microsatellite instability": "MSH2",
    "tmb-h": "TMB",
    "tmb high": "TMB",
    "fgfr": "FGFR2",
    "fgfr2": "FGFR2",
    "fgfr3": "FGFR3",
    "idh1": "IDH1",
    "idh2": "IDH2",
}


class VariantEvidence:
    """Structured evidence for a cancer variant from CIViC."""

    __slots__ = (
        "gene",
        "variant",
        "disease",
        "evidence_type",
        "evidence_level",
        "evidence_direction",
        "drugs",
        "significance",
        "description",
        "source_url",
    )

    def __init__(
        self,
        gene: str,
        variant: str,
        disease: str,
        evidence_type: str,
        evidence_level: str,
        evidence_direction: str,
        drugs: list[str],
        significance: str,
        description: str,
        source_url: str = "",
    ):
        self.gene = gene
        self.variant = variant
        self.disease = disease
        self.evidence_type = evidence_type
        self.evidence_level = evidence_level
        self.evidence_direction = evidence_direction
        self.drugs = drugs
        self.significance = significance
        self.description = description
        self.source_url = source_url

    def to_dict(self) -> dict:
        return {
            "gene": self.gene,
            "variant": self.variant,
            "disease": self.disease,
            "evidence_type": self.evidence_type,
            "evidence_level": self.evidence_level,
            "evidence_direction": self.evidence_direction,
            "drugs": self.drugs,
            "significance": self.significance,
            "description": self.description,
            "source_url": self.source_url,
        }

    @property
    def is_therapeutic(self) -> bool:
        return self.evidence_type.lower() in ("predictive", "therapeutic")

    @property
    def is_high_evidence(self) -> bool:
        """Evidence levels A and B are considered high-quality."""
        return self.evidence_level.upper() in ("A", "B")


def _parse_biomarker_to_gene(biomarker: str) -> str | None:
    """Extract the gene name from a patient-reported biomarker string."""
    clean = biomarker.strip().lower()

    # Direct lookup
    gene = _BIOMARKER_GENES.get(clean)
    if gene:
        return gene

    # Try without percentage (e.g., "PD-L1 80%" → "pd-l1")
    for key, val in _BIOMARKER_GENES.items():
        if clean.startswith(key):
            return val

    # Try uppercase as gene name directly
    upper = biomarker.strip().upper()
    if upper.isalpha() and len(upper) <= 10:
        return upper

    return None


def _parse_variant_from_biomarker(biomarker: str) -> str | None:
    """Extract a specific variant from a biomarker string if present."""
    clean = biomarker.strip()
    # Look for common variant patterns like L858R, V600E, G12C, exon 19
    import re

    # Protein change (e.g., L858R, V600E)
    match = re.search(r"\b([A-Z]\d{2,4}[A-Z])\b", clean, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    # Exon patterns
    match = re.search(r"exon\s*(\d+)\s*(deletion|insertion|skip\w*)?", clean, re.IGNORECASE)
    if match:
        return match.group(0).strip()

    # Fusion/rearrangement
    if "fusion" in clean.lower() or "rearrangement" in clean.lower():
        return "FUSION"

    # Amplification
    if "amplification" in clean.lower() or "amp" in clean.lower():
        return "AMPLIFICATION"

    return None


_GENE_QUERY = """
query($geneSymbol: String!) {
  gene(entrezSymbol: $geneSymbol) {
    name
    variants(first: 100) {
      nodes {
        name
        singleVariantMolecularProfile {
          evidenceItems(first: 20) {
            nodes {
              evidenceType
              evidenceLevel
              evidenceDirection
              significance
              description
              disease {
                name
              }
              therapies {
                name
              }
            }
          }
        }
      }
    }
  }
}
"""


async def lookup_gene(gene_name: str, timeout: float = 15) -> list[VariantEvidence]:
    """Look up all variant evidence for a gene from CIViC.

    Returns therapeutic evidence items sorted by evidence level (A first).
    """
    cache_key = f"gene:{gene_name.upper()}"
    cached = _civic_cache.get(cache_key)
    if cached:
        ts, data = cached
        if time.time() - ts < _CACHE_TTL:
            return data

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                GRAPHQL_URL,
                json={"query": _GENE_QUERY, "variables": {"geneSymbol": gene_name}},
            )
            resp.raise_for_status()
            data = resp.json()

        evidence_list: list[VariantEvidence] = []
        gene_data = data.get("data", {}).get("gene")
        if not gene_data:
            _civic_cache[cache_key] = (time.time(), [])
            logger.info("civic.gene_not_found", gene=gene_name)
            return []

        g_name = gene_data.get("name", gene_name)
        for variant in gene_data.get("variants", {}).get("nodes", []):
            v_name = variant.get("name", "")
            mp = variant.get("singleVariantMolecularProfile") or {}
            for item in mp.get("evidenceItems", {}).get("nodes", []):
                    ev_type = item.get("evidenceType", "")
                    # Only keep therapeutic/predictive evidence for matching
                    if ev_type.upper() not in ("PREDICTIVE", "THERAPEUTIC", "DIAGNOSTIC", "PROGNOSTIC"):
                        continue

                    drugs = [t.get("name", "") for t in item.get("therapies", []) if t.get("name")]
                    disease = item.get("disease", {}).get("name", "") if item.get("disease") else ""

                    evidence_list.append(
                        VariantEvidence(
                            gene=g_name,
                            variant=v_name,
                            disease=disease,
                            evidence_type=ev_type,
                            evidence_level=item.get("evidenceLevel", ""),
                            evidence_direction=item.get("evidenceDirection", ""),
                            drugs=drugs,
                            significance=item.get("significance", ""),
                            description=(item.get("description", "") or "")[:500],
                        )
                    )

        # Sort: therapeutic/predictive first, then by evidence level (A > B > C > D > E)
        level_order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        evidence_list.sort(
            key=lambda e: (
                0 if e.is_therapeutic else 1,
                level_order.get(e.evidence_level.upper(), 5),
            )
        )

        _civic_cache[cache_key] = (time.time(), evidence_list)
        logger.info("civic.gene_lookup", gene=gene_name, evidence_count=len(evidence_list))
        return evidence_list

    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.warning("civic.api_error", gene=gene_name, error=f"{type(e).__name__}: {e}")
        return []


_VARIANT_BROWSE_QUERY = """
query($geneName: String!, $variantName: String!) {
  browseVariants(featureName: $geneName, variantName: $variantName, first: 5) {
    nodes {
      id
      name
    }
  }
}
"""

_VARIANT_EVIDENCE_QUERY = """
query($variantId: Int!) {
  variant(id: $variantId) {
    name
    singleVariantMolecularProfile {
      evidenceItems(first: 20) {
        nodes {
          evidenceType
          evidenceLevel
          evidenceDirection
          significance
          description
          disease {
            name
          }
          therapies {
            name
          }
        }
      }
    }
  }
}
"""


async def lookup_variant(gene_name: str, variant_name: str, timeout: float = 15) -> list[VariantEvidence]:
    """Look up evidence for a specific gene variant from CIViC.

    Two-step: browse to find variant ID, then fetch evidence by ID.
    More targeted than lookup_gene — directly fetches evidence for a known variant.
    """
    cache_key = f"variant:{gene_name.upper()}:{variant_name.upper()}"
    cached = _civic_cache.get(cache_key)
    if cached:
        ts, data = cached
        if time.time() - ts < _CACHE_TTL:
            return data

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Step 1: Find variant ID by browsing
            browse_resp = await client.post(
                GRAPHQL_URL,
                json={
                    "query": _VARIANT_BROWSE_QUERY,
                    "variables": {"geneName": gene_name, "variantName": variant_name},
                },
            )
            browse_resp.raise_for_status()
            browse_data = browse_resp.json()

            nodes = browse_data.get("data", {}).get("browseVariants", {}).get("nodes", [])
            # Find exact match by name
            variant_id = None
            for node in nodes:
                if node.get("name", "").upper() == variant_name.upper():
                    variant_id = node["id"]
                    break

            if variant_id is None:
                _civic_cache[cache_key] = (time.time(), [])
                return []

            # Step 2: Fetch evidence by variant ID
            ev_resp = await client.post(
                GRAPHQL_URL,
                json={
                    "query": _VARIANT_EVIDENCE_QUERY,
                    "variables": {"variantId": variant_id},
                },
            )
            ev_resp.raise_for_status()
            ev_data = ev_resp.json()

        evidence_list: list[VariantEvidence] = []
        variant_data = ev_data.get("data", {}).get("variant")
        if not variant_data:
            _civic_cache[cache_key] = (time.time(), [])
            return []

        v_name = variant_data.get("name", variant_name)
        mp = variant_data.get("singleVariantMolecularProfile") or {}
        for item in mp.get("evidenceItems", {}).get("nodes", []):
            ev_type = item.get("evidenceType", "")
            if ev_type.upper() not in ("PREDICTIVE", "THERAPEUTIC", "DIAGNOSTIC", "PROGNOSTIC"):
                continue
            drugs = [t.get("name", "") for t in item.get("therapies", []) if t.get("name")]
            disease = item.get("disease", {}).get("name", "") if item.get("disease") else ""
            evidence_list.append(
                VariantEvidence(
                    gene=gene_name,
                    variant=v_name,
                    disease=disease,
                    evidence_type=ev_type,
                    evidence_level=item.get("evidenceLevel", ""),
                    evidence_direction=item.get("evidenceDirection", ""),
                    drugs=drugs,
                    significance=item.get("significance", ""),
                    description=(item.get("description", "") or "")[:500],
                )
            )

        level_order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        evidence_list.sort(
            key=lambda e: (
                0 if e.is_therapeutic else 1,
                level_order.get(e.evidence_level.upper(), 5),
            )
        )

        _civic_cache[cache_key] = (time.time(), evidence_list)
        logger.info("civic.variant_lookup", gene=gene_name, variant=variant_name, evidence_count=len(evidence_list))
        return evidence_list

    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.warning("civic.variant_api_error", gene=gene_name, variant=variant_name, error=f"{type(e).__name__}: {e}")
        return []


async def lookup_biomarkers(
    biomarkers: list[str],
    cancer_type: str | None = None,
) -> list[dict]:
    """Look up CIViC evidence for a list of patient-reported biomarkers.

    Returns a list of enrichment dicts ready for injection into matching context.
    Each dict contains the biomarker, gene, and relevant therapeutic evidence.
    """
    import asyncio

    seen_genes: set[str] = set()

    async def _lookup_one(biomarker: str) -> dict | None:
        gene = _parse_biomarker_to_gene(biomarker)
        if not gene or gene in seen_genes:
            return None
        seen_genes.add(gene)

        variant_hint = _parse_variant_from_biomarker(biomarker)

        # Try variant-specific lookup first (more targeted, catches L858R etc.)
        evidence: list[VariantEvidence] = []
        if variant_hint and variant_hint not in ("FUSION", "AMPLIFICATION"):
            evidence = await lookup_variant(gene, variant_hint)

        # Fall back to gene-level lookup
        if not evidence:
            evidence = await lookup_gene(gene)

        if not evidence:
            return None

        # Filter for cancer-type relevance if provided
        if cancer_type:
            cancer_words = set(cancer_type.lower().split())
            # Remove common filler words for matching
            cancer_words -= {"of", "the", "and", "in", "non", "small", "cell", "cancer", "carcinoma"}
            # Keep specific clinical terms
            cancer_words |= {w for w in cancer_type.lower().split() if len(w) > 3}

            def _disease_matches(disease: str) -> bool:
                if not disease:
                    return True  # No disease restriction = relevant to all
                d_lower = disease.lower()
                # Check for keyword overlap between cancer type and disease
                d_words = set(d_lower.split())
                overlap = cancer_words & d_words
                return len(overlap) >= 2 or cancer_type.lower() in d_lower or d_lower in cancer_type.lower()

            relevant = [e for e in evidence if _disease_matches(e.disease)]
            # Fall back to all evidence if no cancer-specific matches
            if relevant:
                evidence = relevant

        # Filter for variant-specific evidence if we have a variant hint
        if variant_hint:
            variant_specific = [e for e in evidence if variant_hint.lower() in e.variant.lower()]
            if variant_specific:
                evidence = variant_specific

        # Take top evidence items (limit to avoid prompt bloat)
        top_evidence = evidence[:5]

        # Determine biomarker status from the original string
        # Check for trailing "-" (e.g., "ALK-", "HER2-") but NOT hyphens in names (e.g., "PD-L1")
        bio_lower = biomarker.lower().strip()
        is_negative = (
            bio_lower.endswith("-")
            or "negative" in bio_lower
            or "absent" in bio_lower
            or "not detected" in bio_lower
        )
        is_positive = not is_negative

        actionable_drugs = []
        for e in top_evidence:
            if e.is_therapeutic and e.drugs:
                for drug in e.drugs:
                    if drug not in actionable_drugs:
                        actionable_drugs.append(drug)

        return {
            "biomarker": biomarker,
            "gene": gene,
            "variant": variant_hint,
            "is_positive": is_positive,
            "actionable_drugs": actionable_drugs[:10],
            "evidence_summary": _summarize_evidence(top_evidence),
            "highest_evidence_level": top_evidence[0].evidence_level if top_evidence else None,
            "evidence_count": len(evidence),
        }

    lookups = await asyncio.gather(*[_lookup_one(b) for b in biomarkers])
    return [r for r in lookups if r is not None]


def _summarize_evidence(evidence: list[VariantEvidence]) -> str:
    """Create a concise summary of evidence for prompt injection."""
    if not evidence:
        return "No CIViC evidence available."

    lines = []
    for e in evidence[:3]:  # Top 3 items
        drug_str = ", ".join(e.drugs) if e.drugs else "N/A"
        direction = e.evidence_direction or "unknown"
        line = (
            f"{e.gene} {e.variant}: {e.evidence_type} (Level {e.evidence_level}) — "
            f"{e.significance} {direction} for {drug_str}"
        )
        if e.disease:
            line += f" in {e.disease}"
        lines.append(line)

    return "; ".join(lines)


def format_biomarker_context(enrichments: list[dict]) -> str:
    """Format CIViC enrichment data as a prompt context block.

    This is injected into the eligibility analysis prompt to give Claude
    structured biomarker evidence alongside the free-text criteria.
    """
    if not enrichments:
        return ""

    lines = ["## Biomarker Intelligence (from CIViC database)"]
    for e in enrichments:
        status = "POSITIVE" if e["is_positive"] else "NEGATIVE"
        lines.append(f"\n### {e['biomarker']} ({e['gene']}, {status})")
        if e.get("actionable_drugs"):
            lines.append(f"Actionable drugs: {', '.join(e['actionable_drugs'])}")
        if e.get("highest_evidence_level"):
            lines.append(f"Highest evidence level: {e['highest_evidence_level']}")
        if e.get("evidence_summary"):
            lines.append(f"Evidence: {e['evidence_summary']}")

    lines.append(
        "\nUse this structured biomarker data to validate or refine your assessment "
        "of biomarker-related eligibility criteria."
    )
    return "\n".join(lines)
