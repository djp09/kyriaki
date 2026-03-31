from typing import Dict, List, Optional, Tuple

import httpx
import math

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

# Approximate lat/lon for US ZIP codes (first 3 digits).
# For a real product, use a geocoding API. This is good enough for the prototype.
ZIP_PREFIX_COORDS: Dict[str, Tuple[float, float]] = {
    "100": (40.71, -74.01),   # NYC
    "021": (42.36, -71.06),   # Boston
    "606": (41.88, -87.63),   # Chicago
    "770": (29.76, -95.37),   # Houston
    "900": (34.05, -118.24),  # LA
    "941": (37.77, -122.42),  # SF
    "200": (38.91, -77.04),   # DC
    "303": (33.75, -84.39),   # Atlanta
    "331": (25.76, -80.19),   # Miami
    "981": (47.61, -122.33),  # Seattle
    "852": (33.45, -112.07),  # Phoenix
    "802": (39.74, -104.99),  # Denver
    "191": (39.95, -75.17),   # Philadelphia
    "481": (42.33, -83.05),   # Detroit
    "551": (44.98, -93.27),   # Minneapolis
}


def _zip_to_coords(zip_code: str) -> Optional[Tuple[float, float]]:
    """Best-effort ZIP to lat/lon. Returns None if unknown."""
    for prefix_len in (3, 2, 1):
        prefix = zip_code[:prefix_len]
        if prefix in ZIP_PREFIX_COORDS:
            return ZIP_PREFIX_COORDS[prefix]
    # Default to geographic center of US
    return (39.8, -98.6)


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
    patient_coords = _zip_to_coords(patient_zip)
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
    """Flatten the nested ClinicalTrials.gov study structure."""
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
    """Parse '18 Years' -> 18."""
    if not age_str:
        return None
    parts = age_str.split()
    try:
        return int(parts[0])
    except (ValueError, IndexError):
        return None


async def search_trials(
    cancer_type: str,
    age: Optional[int] = None,
    sex: Optional[str] = None,
    page_size: int = 10,
) -> List[Dict]:
    """Search ClinicalTrials.gov for recruiting trials matching the cancer type."""
    params = {
        "query.cond": cancer_type,
        "filter.overallStatus": "RECRUITING",
        "fields": FIELDS,
        "pageSize": min(page_size, 100),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/studies", params=params)
        resp.raise_for_status()
        data = resp.json()

    studies = []
    for study_raw in data.get("studies", []):
        study = _extract_study(study_raw)

        # Pre-filter: age
        if age is not None:
            min_age = _parse_age_years(study.get("minimum_age", ""))
            max_age = _parse_age_years(study.get("maximum_age", ""))
            if min_age and age < min_age:
                continue
            if max_age and age > max_age:
                continue

        # Pre-filter: sex
        if sex and study.get("sex") != "ALL":
            if study["sex"].upper() != sex.upper():
                continue

        studies.append(study)

    return studies


async def get_trial(nct_id: str) -> Optional[Dict]:
    """Fetch a single trial by NCT ID."""
    params = {"fields": FIELDS}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/studies/{nct_id}", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()

    return _extract_study(data)
