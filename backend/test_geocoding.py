"""Tests for the geocoding service."""

import pytest

from geocoding import get_coordinates, get_zip_info


class TestGetCoordinates:
    def test_nyc_zip(self):
        lat, lon = get_coordinates("10001")
        assert 40.5 < lat < 41.0
        assert -74.5 < lon < -73.5

    def test_beverly_hills(self):
        lat, lon = get_coordinates("90210")
        assert 33.5 < lat < 34.5
        assert -119.0 < lon < -117.5

    def test_chicago(self):
        lat, lon = get_coordinates("60601")
        assert 41.5 < lat < 42.5
        assert -88.0 < lon < -87.0

    def test_invalid_zip_returns_fallback(self):
        lat, lon = get_coordinates("00000")
        assert -90 <= lat <= 90
        assert -180 <= lon <= 180

    def test_caching(self):
        r1 = get_coordinates("10001")
        r2 = get_coordinates("10001")
        assert r1 == r2

    def test_short_zip_prefix(self):
        """3-digit prefix should hit the fallback map."""
        lat, lon = get_coordinates("100")
        assert 40.0 < lat < 41.5


class TestGetZipInfo:
    def test_known_zip(self):
        info = get_zip_info("10001")
        assert info is not None
        assert "lat" in info
        assert "lon" in info
        assert info.get("city") is not None

    def test_invalid_zip(self):
        info = get_zip_info("00000")
        if info is not None:
            assert "lat" in info
