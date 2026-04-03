"""RxNorm API client — drug name normalization.

Resolves brand names, generic names, and investigational codes to canonical
RxNorm identifiers (RXCUIs). Essential for matching because patients report
"Keytruda" while trials list "pembrolizumab" or "MK-3475".

API docs: https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html
No API key required. Rate limit is generous.
"""

from __future__ import annotations

import time

import httpx

from logging_config import get_logger

logger = get_logger("kyriaki.rxnorm")

BASE_URL = "https://rxnav.nlm.nih.gov/REST"

# In-memory cache: drug_name_lower -> (timestamp, NormalizedDrug)
_norm_cache: dict[str, tuple[float, NormalizedDrug | None]] = {}
_CACHE_TTL = 86400  # 24 hours — drug names don't change often

# Pre-seeded mappings for common oncology drugs to avoid API calls for the
# most frequent lookups. Maps lowercase name → canonical generic name.
_ONCOLOGY_SHORTCUTS: dict[str, str] = {
    # Immunotherapy
    "keytruda": "pembrolizumab",
    "mk-3475": "pembrolizumab",
    "opdivo": "nivolumab",
    "bms-936558": "nivolumab",
    "tecentriq": "atezolizumab",
    "mpdl3280a": "atezolizumab",
    "imfinzi": "durvalumab",
    "medi4736": "durvalumab",
    "libtayo": "cemiplimab",
    "yervoy": "ipilimumab",
    "mdx-010": "ipilimumab",
    "jemperli": "dostarlimab",
    # Targeted therapy — EGFR
    "tarceva": "erlotinib",
    "iressa": "gefitinib",
    "tagrisso": "osimertinib",
    "azd9291": "osimertinib",
    "gilotrif": "afatinib",
    "vizimpro": "dacomitinib",
    "rybrevant": "amivantamab",
    # Targeted therapy — ALK
    "xalkori": "crizotinib",
    "zykadia": "ceritinib",
    "alecensa": "alectinib",
    "alunbrig": "brigatinib",
    "lorbrena": "lorlatinib",
    # Targeted therapy — HER2
    "herceptin": "trastuzumab",
    "perjeta": "pertuzumab",
    "kadcyla": "ado-trastuzumab emtansine",
    "t-dm1": "ado-trastuzumab emtansine",
    "enhertu": "trastuzumab deruxtecan",
    "t-dxd": "trastuzumab deruxtecan",
    "ds-8201": "trastuzumab deruxtecan",
    # Targeted therapy — BRCA/PARP
    "lynparza": "olaparib",
    "rubraca": "rucaparib",
    "zejula": "niraparib",
    "talzenna": "talazoparib",
    # Targeted therapy — VEGF/angiogenesis
    "avastin": "bevacizumab",
    "cyramza": "ramucirumab",
    "zaltrap": "ziv-aflibercept",
    # Targeted therapy — other
    "ibrance": "palbociclib",
    "kisqali": "ribociclib",
    "verzenio": "abemaciclib",
    "nexavar": "sorafenib",
    "sutent": "sunitinib",
    "stivarga": "regorafenib",
    "cabometyx": "cabozantinib",
    "cometriq": "cabozantinib",
    "lenvima": "lenvatinib",
    "tafinlar": "dabrafenib",
    "mekinist": "trametinib",
    "zelboraf": "vemurafenib",
    "cotellic": "cobimetinib",
    "braftovi": "encorafenib",
    "mektovi": "binimetinib",
    "lumakras": "sotorasib",
    "krazati": "adagrasib",
    # Chemotherapy
    "taxol": "paclitaxel",
    "abraxane": "nab-paclitaxel",
    "taxotere": "docetaxel",
    "platinol": "cisplatin",
    "paraplatin": "carboplatin",
    "eloxatin": "oxaliplatin",
    "alimta": "pemetrexed",
    "gemzar": "gemcitabine",
    "adriamycin": "doxorubicin",
    "cytoxan": "cyclophosphamide",
    "oncovin": "vincristine",
    "navelbine": "vinorelbine",
    "camptosar": "irinotecan",
    "hycamtin": "topotecan",
    "xeloda": "capecitabine",
    "5-fu": "fluorouracil",
    "5fu": "fluorouracil",
    "etoposide": "etoposide",
    "vp-16": "etoposide",
}


class NormalizedDrug:
    """Result of normalizing a drug name."""

    __slots__ = ("original", "canonical", "rxcui", "synonyms")

    def __init__(
        self,
        original: str,
        canonical: str,
        rxcui: str | None = None,
        synonyms: list[str] | None = None,
    ):
        self.original = original
        self.canonical = canonical
        self.rxcui = rxcui
        self.synonyms = synonyms or []

    def matches(self, other_name: str) -> bool:
        """Check if another drug name refers to the same drug."""
        other_lower = other_name.lower().strip()
        if other_lower == self.canonical.lower():
            return True
        return any(s.lower() == other_lower for s in self.synonyms)

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "canonical": self.canonical,
            "rxcui": self.rxcui,
            "synonyms": self.synonyms,
        }


def _get_cached(name: str) -> NormalizedDrug | None:
    key = name.lower().strip()
    if key in _norm_cache:
        ts, result = _norm_cache[key]
        if time.time() - ts < _CACHE_TTL:
            return result
        del _norm_cache[key]
    return None


def _set_cache(name: str, result: NormalizedDrug | None) -> None:
    _norm_cache[name.lower().strip()] = (time.time(), result)


def _try_shortcut(name: str) -> NormalizedDrug | None:
    """Check pre-seeded oncology drug mappings."""
    key = name.lower().strip()
    canonical = _ONCOLOGY_SHORTCUTS.get(key)
    if canonical:
        # Also collect all synonyms that map to the same canonical
        synonyms = [k for k, v in _ONCOLOGY_SHORTCUTS.items() if v == canonical and k != key]
        synonyms.append(canonical)
        return NormalizedDrug(original=name, canonical=canonical, synonyms=synonyms)
    # Check if the name IS a canonical name in our shortcuts
    if key in _ONCOLOGY_SHORTCUTS.values():
        synonyms = [k for k, v in _ONCOLOGY_SHORTCUTS.items() if v == key]
        return NormalizedDrug(original=name, canonical=key, synonyms=synonyms)
    return None


async def normalize_drug(name: str, timeout: float = 10) -> NormalizedDrug | None:
    """Normalize a drug name to its canonical form.

    Tries local shortcuts first, then falls back to RxNorm API.
    Returns None if the name cannot be resolved.
    """
    if not name or not name.strip():
        return None

    clean = name.strip()

    # Check cache first
    cached = _get_cached(clean)
    if cached is not None:
        return cached

    # Try local shortcuts (no API call needed)
    shortcut = _try_shortcut(clean)
    if shortcut:
        _set_cache(clean, shortcut)
        return shortcut

    # Fall back to RxNorm API
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Try approximate match first (handles misspellings, partial names)
            resp = await client.get(
                f"{BASE_URL}/approximateTerm.json",
                params={"term": clean, "maxEntries": 3},
            )
            resp.raise_for_status()
            data = resp.json()

            candidates = data.get("approximateGroup", {}).get("candidate", [])
            if not candidates:
                logger.debug("rxnorm.no_match", drug=clean)
                _set_cache(clean, None)
                return None

            rxcui = candidates[0].get("rxcui")
            if not rxcui:
                _set_cache(clean, None)
                return None

            # Get the canonical name and synonyms
            props_resp = await client.get(f"{BASE_URL}/rxcui/{rxcui}/properties.json")
            props_resp.raise_for_status()
            props = props_resp.json().get("properties", {})
            canonical = props.get("name", clean)

            # Get synonyms for broader matching (best-effort, non-fatal)
            synonyms = []
            try:
                syn_resp = await client.get(
                    f"{BASE_URL}/rxcui/{rxcui}/allrelated.json",
                )
                syn_resp.raise_for_status()
                syn_data = syn_resp.json()
                for group in syn_data.get("allRelatedGroup", {}).get("conceptGroup", []):
                    tty = group.get("tty", "")
                    if tty in ("SY", "BN", "IN", "PIN"):
                        for concept in group.get("conceptProperties", []):
                            syn_name = concept.get("name", "")
                            if syn_name and syn_name.lower() != canonical.lower():
                                synonyms.append(syn_name)
            except Exception:
                pass  # Synonyms are nice-to-have, not critical

            result = NormalizedDrug(
                original=clean,
                canonical=canonical,
                rxcui=rxcui,
                synonyms=synonyms[:10],  # Cap synonyms to avoid bloat
            )
            _set_cache(clean, result)
            return result

    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.warning("rxnorm.api_error", drug=clean, error=f"{type(e).__name__}: {e}")
        # Still try shortcut as absolute fallback
        return None


async def normalize_drug_list(names: list[str], timeout: float = 10) -> dict[str, NormalizedDrug]:
    """Normalize a list of drug names concurrently.

    Handles combo regimens like "Carboplatin/Pemetrexed" by splitting on "/".
    Returns a dict mapping original name → NormalizedDrug for successful lookups.
    """
    import asyncio

    # Expand combo regimens into individual drugs
    expanded: list[str] = []
    for name in names:
        parts = [p.strip() for p in name.replace("/", ",").split(",") if p.strip()]
        expanded.extend(parts)

    # Deduplicate
    unique = list(dict.fromkeys(expanded))

    results: dict[str, NormalizedDrug] = {}

    async def _normalize_one(drug_name: str) -> None:
        result = await normalize_drug(drug_name, timeout=timeout)
        if result:
            results[drug_name] = result

    await asyncio.gather(*[_normalize_one(n) for n in unique])

    # Also map original combo names back for convenience
    for name in names:
        if "/" in name and name not in results:
            # Map combo to its first resolved component
            parts = [p.strip() for p in name.replace("/", ",").split(",") if p.strip()]
            for part in parts:
                if part in results:
                    results[name] = NormalizedDrug(
                        original=name,
                        canonical=name,  # Keep combo as-is
                        synonyms=[results[p].canonical for p in parts if p in results],
                    )
                    break

    return results


def drug_names_match(name1: str, name2: str) -> bool:
    """Quick local check if two drug names refer to the same drug (no API call).

    Uses the pre-seeded oncology shortcuts. For more thorough matching,
    use normalize_drug() on both names and compare RXCUIs.
    """
    a = name1.lower().strip()
    b = name2.lower().strip()

    if a == b:
        return True

    # Resolve both through shortcuts
    canon_a = _ONCOLOGY_SHORTCUTS.get(a, a)
    canon_b = _ONCOLOGY_SHORTCUTS.get(b, b)

    return canon_a == canon_b
