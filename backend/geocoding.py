"""Production geocoding: pgeocode local database with prefix fallback.

Uses pgeocode for instant local lookups (GeoNames dataset of all US postal codes).
Falls back to hardcoded prefix map, then US geographic center.
"""

from __future__ import annotations

import math
from functools import lru_cache

from logging_config import get_logger

logger = get_logger("kyriaki.geocoding")

# Initialize pgeocode for US postal codes
_nomi = None
try:
    import pgeocode

    _nomi = pgeocode.Nominatim("us")
    logger.info("geocoding.init", backend="pgeocode", status="ok")
except Exception as e:
    logger.warning("geocoding.init", backend="pgeocode", status="unavailable", error=str(e))

# Fallback: hardcoded prefix map (same as the original prototype)
_ZIP_PREFIX_COORDS: dict[str, tuple[float, float]] = {
    "100": (40.71, -74.01),
    "021": (42.36, -71.06),
    "606": (41.88, -87.63),
    "770": (29.76, -95.37),
    "900": (34.05, -118.24),
    "941": (37.77, -122.42),
    "200": (38.91, -77.04),
    "303": (33.75, -84.39),
    "331": (25.76, -80.19),
    "981": (47.61, -122.33),
    "852": (33.45, -112.07),
    "802": (39.74, -104.99),
    "191": (39.95, -75.17),
    "481": (42.33, -83.05),
    "551": (44.98, -93.27),
}

_US_CENTER: tuple[float, float] = (39.8, -98.6)


@lru_cache(maxsize=2048)
def get_coordinates(zip_code: str) -> tuple[float, float]:
    """Return (lat, lon) for a US ZIP code. Always returns a result (falls back to US center)."""
    # Strategy 1: pgeocode local database
    if _nomi is not None:
        try:
            result = _nomi.query_postal_code(zip_code)
            if result is not None and not math.isnan(result.latitude):
                return (float(result.latitude), float(result.longitude))
        except Exception:
            pass

    # Strategy 2: hardcoded prefix map
    for prefix_len in (3, 2):
        prefix = zip_code[:prefix_len]
        if prefix in _ZIP_PREFIX_COORDS:
            return _ZIP_PREFIX_COORDS[prefix]

    # Strategy 3: US geographic center
    logger.debug("geocoding.fallback", zip_code=zip_code, fallback="us_center")
    return _US_CENTER


@lru_cache(maxsize=2048)
def get_zip_info(zip_code: str) -> dict | None:
    """Return full ZIP info (city, state, lat, lon) or None."""
    if _nomi is None:
        coords = get_coordinates(zip_code)
        return {"zip_code": zip_code, "lat": coords[0], "lon": coords[1]}

    try:
        result = _nomi.query_postal_code(zip_code)
        if result is not None and not math.isnan(result.latitude):
            return {
                "zip_code": zip_code,
                "city": str(result.place_name) if result.place_name else None,
                "state": str(result.state_name) if result.state_name else None,
                "lat": float(result.latitude),
                "lon": float(result.longitude),
            }
    except Exception:
        pass
    return None
