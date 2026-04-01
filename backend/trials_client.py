from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import asyncio
import math
import time

import httpx

from config import get_settings
from geocoding import get_coordinates
from logging_config import get_logger

logger = get_logger("kyriaki.trials")

BASE_URL = "https://clinicaltrials.gov/api/v2"

FIELDS = ",".join([
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
])

# Simple in-memory cache: key -> (timestamp, data)
_search_cache: Dict[str, Tuple[float, List[Dict]]] = {}


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3959  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def find_nearest_site(
    locations: List[Dict], patient_zip: str
) -> Tuple[Optional[Dict], Optional[float]]:
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


def _extract_study(study: Dict) -> Dict:
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


def _parse_age_years(age_str: str) -> Optional[int]:
    if not age_str:
        return None
    parts = age_str.split()
    try:
        return int(parts[0])
    except (ValueError, IndexError):
        return None


def _cache_key(cancer_type: str, age: Optional[int], sex: Optional[str], page_size: int) -> str:
    return f"{cancer_type}|{age}|{sex}|{page_size}"


def _get_cached(key: str) -> Optional[List[Dict]]:
    settings = get_settings()
    if key in _search_cache:
        ts, data = _search_cache[key]
        if time.time() - ts < settings.cache_ttl:
            logger.debug("trials.cache_hit", key=key)
            return data
        else:
            del _search_cache[key]
    return None


def _set_cache(key: str, data: List[Dict]) -> None:
    _search_cache[key] = (time.time(), data)


async def _http_get_with_retry(
    url: str,
    params: dict,
    max_retries: int = 3,
    timeout: float = 30,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning("trials.network_error", error_type=type(e).__name__, attempt=attempt + 1, wait_s=wait)
            await asyncio.sleep(wait)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504):
                last_exc = e
                wait = 2 ** attempt
                logger.warning("trials.http_error", status=e.response.status_code, attempt=attempt + 1, wait_s=wait)
                await asyncio.sleep(wait)
            else:
                raise
    raise last_exc  # type: ignore[misc]


async def search_trials(
    cancer_type: str,
    age: Optional[int] = None,
    sex: Optional[str] = None,
    page_size: int = 10,
) -> List[Dict]:
    cache_k = _cache_key(cancer_type, age, sex, page_size)
    cached = _get_cached(cache_k)
    if cached is not None:
        return cached

    params = {
        "query.cond": cancer_type,
        "filter.overallStatus": "RECRUITING",
        "fields": FIELDS,
        "pageSize": min(page_size, 100),
    }

    resp = await _http_get_with_retry(f"{BASE_URL}/studies", params)
    try:
        data = resp.json()
    except Exception as e:
        logger.error("trials.json_parse_failed", error=str(e))
        return []

    if not isinstance(data, dict) or "studies" not in data:
        logger.error("trials.unexpected_response", keys=list(data.keys()) if isinstance(data, dict) else str(type(data)))
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

        if sex and study.get("sex") != "ALL":
            if study["sex"].upper() != sex.upper():
                continue

        studies.append(study)

    _set_cache(cache_k, studies)
    return studies


async def get_trial(nct_id: str) -> Optional[Dict]:
    params = {"fields": FIELDS}
    try:
        resp = await _http_get_with_retry(f"{BASE_URL}/studies/{nct_id}", params)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (400, 404):
            return None
        raise
    try:
        data = resp.json()
    except Exception as e:
        logger.error("trials.json_parse_failed", nct_id=nct_id, error=str(e))
        return None

    return _extract_study(data)
