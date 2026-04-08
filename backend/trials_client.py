from __future__ import annotations

import asyncio
import math
import re
import time

import httpx

from config import get_settings
from geocoding import get_coordinates
from logging_config import get_logger

logger = get_logger("kyriaki.trials")

BASE_URL = "https://clinicaltrials.gov/api/v2"

# Positive biomarker gene → targeted drug names for ClinicalTrials.gov search.
# These are standard-of-care or commonly trialed agents; the goal is to pull in
# trials testing therapies for the patient's specific molecular profile.
_GENE_TO_DRUGS: dict[str, list[str]] = {
    "EGFR": ["osimertinib", "erlotinib", "gefitinib", "afatinib", "amivantamab"],
    "ALK": ["alectinib", "lorlatinib", "crizotinib", "brigatinib", "ceritinib"],
    "ROS1": ["crizotinib", "entrectinib", "lorlatinib"],
    "ERBB2": ["trastuzumab", "pertuzumab", "T-DXd", "tucatinib", "neratinib"],
    "BRAF": ["dabrafenib", "trametinib", "encorafenib", "vemurafenib"],
    "KRAS": ["sotorasib", "adagrasib"],
    "BRCA1": ["olaparib", "rucaparib", "niraparib", "talazoparib"],
    "BRCA2": ["olaparib", "rucaparib", "niraparib", "talazoparib"],
    "NTRK1": ["larotrectinib", "entrectinib"],
    "NTRK2": ["larotrectinib", "entrectinib"],
    "NTRK3": ["larotrectinib", "entrectinib"],
    "MET": ["capmatinib", "tepotinib", "crizotinib"],
    "RET": ["selpercatinib", "pralsetinib"],
    "FGFR2": ["erdafitinib", "futibatinib", "pemigatinib"],
    "FGFR3": ["erdafitinib"],
    "MSH2": ["pembrolizumab", "nivolumab", "dostarlimab"],
    "PIK3CA": ["alpelisib"],
    "IDH1": ["ivosidenib"],
    "IDH2": ["enasidenib"],
}

# Biomarkers where negative status is not actionable for targeted therapy search
_NEGATIVE_SUFFIXES = ("-", "negative", "absent", "not detected", "wild type", "wt")


def biomarker_search_terms(biomarkers: list[str]) -> tuple[str | None, str | None]:
    """Derive (query_intr, query_term) from patient biomarkers for trial search.

    Returns the first actionable positive biomarker's drug as query_intr and
    the gene name as query_term. Returns (None, None) if no actionable
    biomarkers are found.
    """
    from civic_client import _parse_biomarker_to_gene

    for biomarker in biomarkers:
        clean = biomarker.strip().lower()

        # Skip negative biomarkers — they don't drive targeted therapy search
        if any(clean.endswith(s) for s in _NEGATIVE_SUFFIXES):
            continue
        if "negative" in clean or "absent" in clean or "not detected" in clean:
            continue

        gene = _parse_biomarker_to_gene(biomarker)
        if not gene:
            continue

        drugs = _GENE_TO_DRUGS.get(gene)
        if not drugs:
            continue

        # Use the first (most common) drug as intervention filter
        query_intr = drugs[0]
        # Also add gene name as a general term to catch gene-named trials
        query_term = gene
        logger.info(
            "trials.biomarker_search_terms",
            biomarker=biomarker,
            gene=gene,
            query_intr=query_intr,
            query_term=query_term,
        )
        return query_intr, query_term

    return None, None


# Module-level shared HTTP client — reuses connections across requests
_shared_client: httpx.AsyncClient | None = None
_client_lock: asyncio.Lock | None = None


def _get_client_lock() -> asyncio.Lock:
    """Lazily create the lock (Python 3.9 compat — no event loop at import time)."""
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


async def get_http_client() -> httpx.AsyncClient:
    """Get or create the shared HTTP client with connection pooling."""
    global _shared_client
    async with _get_client_lock():
        if _shared_client is None or _shared_client.is_closed:
            _shared_client = httpx.AsyncClient(
                timeout=30,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                headers={"User-Agent": "Kyriaki/1.0 (clinical-trial-matching)"},
            )
        return _shared_client


async def close_http_client() -> None:
    """Close the shared HTTP client. Call on app shutdown."""
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None


FIELDS = ",".join(
    [
        "NCTId",
        "BriefTitle",
        "OfficialTitle",
        "Condition",
        "Phase",
        "EligibilityModule",
        "ContactsLocationsModule",
        "DescriptionModule",
        "StatusModule",
        "ArmsInterventionsModule",
    ]
)

# Simple in-memory cache: key -> (timestamp, data)
_search_cache: dict[str, tuple[float, list[dict]]] = {}


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3959  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def find_nearest_site(locations: list[dict], patient_zip: str) -> tuple[dict | None, float | None]:
    """Find the nearest trial site to the patient's ZIP code."""
    patient_coords = get_coordinates(patient_zip)
    if not patient_coords or not locations:
        return None, None

    best_site = None
    best_distance = float("inf")

    for loc in locations:
        geo = loc.get("geoPoint")
        if not geo:
            continue
        lat = geo.get("lat")
        lon = geo.get("lon")
        if lat is None or lon is None:
            continue
        dist = _haversine_miles(patient_coords[0], patient_coords[1], lat, lon)
        if dist < best_distance:
            best_distance = dist
            best_site = {
                "facility": loc.get("facility", "Unknown facility"),
                "city": loc.get("city", ""),
                "state": loc.get("state", ""),
                "country": loc.get("country", ""),
                "status": loc.get("status", ""),
            }

    if best_site is None:
        return None, None
    return best_site, round(best_distance, 1)


def _extract_study(study: dict) -> dict:
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    elig = ps.get("eligibilityModule", {})
    cond = ps.get("conditionsModule", {})
    desc = ps.get("descriptionModule", {})
    contacts = ps.get("contactsLocationsModule", {})
    arms = ps.get("armsInterventionsModule", {})

    phases = status.get("phases", [])
    phase_str = ", ".join(p.replace("PHASE", "Phase ") for p in phases) if phases else "N/A"

    interventions = []
    for arm in arms.get("interventions", []):
        name = arm.get("name", "")
        itype = arm.get("type", "")
        if name:
            interventions.append(f"{itype}: {name}" if itype else name)

    return {
        "nct_id": ident.get("nctId", ""),
        "brief_title": ident.get("briefTitle", ""),
        "overall_status": status.get("overallStatus", ""),
        "phase": phase_str,
        "conditions": cond.get("conditions", []),
        "eligibility_criteria": elig.get("eligibilityCriteria", ""),
        "sex": elig.get("sex", "ALL"),
        "minimum_age": elig.get("minimumAge", ""),
        "maximum_age": elig.get("maximumAge", ""),
        "brief_summary": desc.get("briefSummary", ""),
        "locations": contacts.get("locations", []),
        "interventions": interventions,
    }


# Keywords indicating a non-treatment study (biobanks, tissue collection, surveys, etc.)
# These studies can't score well because they lack therapeutic eligibility criteria.
_NON_TREATMENT_PATTERN = re.compile(
    r"\b(biobank|biospecimen|tissue\s+collect\w*|sample\s+collect\w*|"
    r"registry\s+stud\w*|natural\s+history|survey\s+stud\w*|"
    r"specimen\s+bank|tumor\s+bank|blood\s+collect\w*)\b",
    re.IGNORECASE,
)


def is_non_treatment_study(study: dict) -> bool:
    """Return True if the study is observational/biobank, not a treatment trial."""
    title = study.get("brief_title", "")
    summary = study.get("brief_summary", "")
    text = f"{title} {summary}"
    if _NON_TREATMENT_PATTERN.search(text):
        return True
    # No interventions at all is a strong signal of non-treatment
    return not study.get("interventions")


def _parse_age_years(age_str: str) -> int | None:
    if not age_str:
        return None
    parts = age_str.split()
    try:
        return int(parts[0])
    except (ValueError, IndexError):
        return None


def _cache_key(
    cancer_type: str,
    age: int | None,
    sex: str | None,
    page_size: int,
    query_intr: str | None = None,
    query_term: str | None = None,
) -> str:
    return f"{cancer_type}|{age}|{sex}|{page_size}|{query_intr}|{query_term}"


def _get_cached(key: str) -> list[dict] | None:
    settings = get_settings()
    if key in _search_cache:
        ts, data = _search_cache[key]
        if time.time() - ts < settings.cache_ttl:
            logger.debug("trials.cache_hit", key=key)
            return data
        del _search_cache[key]
    return None


def _set_cache(key: str, data: list[dict]) -> None:
    _search_cache[key] = (time.time(), data)


async def _http_get_with_retry(
    url: str,
    params: dict,
    max_retries: int = 3,
) -> httpx.Response:
    client = await get_http_client()
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
            last_exc = e
            wait = 2**attempt
            logger.warning("trials.network_error", error_type=type(e).__name__, attempt=attempt + 1, wait_s=wait)
            await asyncio.sleep(wait)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504):
                last_exc = e
                wait = 2**attempt
                logger.warning("trials.http_error", status=e.response.status_code, attempt=attempt + 1, wait_s=wait)
                await asyncio.sleep(wait)
            else:
                raise
    raise last_exc  # type: ignore[misc]


async def search_trials(
    cancer_type: str,
    age: int | None = None,
    sex: str | None = None,
    page_size: int = 10,
    query_intr: str | None = None,
    query_term: str | None = None,
) -> list[dict]:
    cache_k = _cache_key(cancer_type, age, sex, page_size, query_intr, query_term)
    cached = _get_cached(cache_k)
    if cached is not None:
        return cached

    params = {
        "query.cond": cancer_type,
        "filter.overallStatus": "RECRUITING",
        "fields": FIELDS,
        "pageSize": min(page_size, 100),
    }
    if query_intr:
        params["query.intr"] = query_intr
    if query_term:
        params["query.term"] = query_term

    resp = await _http_get_with_retry(f"{BASE_URL}/studies", params)
    try:
        data = resp.json()
    except Exception as e:
        logger.error("trials.json_parse_failed", error=str(e))
        return []

    if not isinstance(data, dict) or "studies" not in data:
        logger.error(
            "trials.unexpected_response", keys=list(data.keys()) if isinstance(data, dict) else str(type(data))
        )
        return []

    studies = []
    for study_raw in data.get("studies", []):
        try:
            study = _extract_study(study_raw)
        except Exception as e:
            logger.warning("trials.extract_failed", error=str(e))
            continue

        if age is not None:
            min_age = _parse_age_years(study.get("minimum_age", ""))
            max_age = _parse_age_years(study.get("maximum_age", ""))
            if min_age and age < min_age:
                continue
            if max_age and age > max_age:
                continue

        if sex and study.get("sex") != "ALL" and study["sex"].upper() != sex.upper():
            continue

        # Filter out non-treatment studies (biobanks, registries, etc.)
        if is_non_treatment_study(study):
            logger.debug(
                "trials.filtered_non_treatment", nct_id=study.get("nct_id"), title=study.get("brief_title", "")[:60]
            )
            continue

        studies.append(study)

    _set_cache(cache_k, studies)
    return studies


async def search_nci_trials(
    cancer_type: str,
    age: int | None = None,
    sex: str | None = None,
    page_size: int = 10,
) -> list[dict]:
    """Search for NCI-sponsored oncology trials.

    NCI trials are a curated subset of ClinicalTrials.gov with higher
    signal-to-noise for cancer specifically. Queries ClinicalTrials.gov
    with NCI-specific filters (LEAD_ORG = National Cancer Institute).
    """
    cache_k = _cache_key(f"NCI:{cancer_type}", age, sex, page_size)
    cached = _get_cached(cache_k)
    if cached is not None:
        return cached

    params = {
        "query.cond": cancer_type,
        "query.term": "AREA[LeadSponsorName]National Cancer Institute",
        "filter.overallStatus": "RECRUITING",
        "fields": FIELDS,
        "pageSize": min(page_size, 100),
    }

    try:
        resp = await _http_get_with_retry(f"{BASE_URL}/studies", params)
    except Exception as e:
        logger.warning("trials.nci_search_failed", error=str(e))
        return []

    try:
        data = resp.json()
    except Exception as e:
        logger.error("trials.nci_json_parse_failed", error=str(e))
        return []

    if not isinstance(data, dict) or "studies" not in data:
        return []

    studies = []
    for study_raw in data.get("studies", []):
        try:
            study = _extract_study(study_raw)
        except Exception:
            continue

        if age is not None:
            min_age = _parse_age_years(study.get("minimum_age", ""))
            max_age = _parse_age_years(study.get("maximum_age", ""))
            if min_age and age < min_age:
                continue
            if max_age and age > max_age:
                continue

        if sex and study.get("sex") != "ALL" and study["sex"].upper() != sex.upper():
            continue

        if is_non_treatment_study(study):
            continue

        studies.append(study)

    _set_cache(cache_k, studies)
    logger.info("trials.nci_search_complete", cancer_type=cancer_type, results=len(studies))
    return studies


def merge_and_deduplicate(trial_lists: list[list[dict]]) -> list[dict]:
    """Merge multiple trial lists and deduplicate by NCT ID.

    Earlier lists take priority (their version of a trial is kept).
    """
    seen: dict[str, dict] = {}
    for trials in trial_lists:
        for trial in trials:
            nct_id = trial.get("nct_id", "")
            if nct_id and nct_id not in seen:
                seen[nct_id] = trial
    return list(seen.values())


async def get_trial(nct_id: str) -> dict | None:
    params = {"fields": FIELDS}
    try:
        resp = await _http_get_with_retry(f"{BASE_URL}/studies/{nct_id}", params)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (400, 403, 404):
            return None
        raise
    try:
        data = resp.json()
    except Exception as e:
        logger.error("trials.json_parse_failed", nct_id=nct_id, error=str(e))
        return None

    return _extract_study(data)
