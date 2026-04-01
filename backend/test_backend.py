"""Tests for the Kyriaki backend."""

import pytest
from pydantic import ValidationError

from models import PatientProfile, MatchRequest
from trials_client import (
    _extract_study,
    _parse_age_years,
    _haversine_miles,
    find_nearest_site,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _valid_patient(**overrides) -> dict:
    """Return a valid patient profile dict with optional overrides."""
    base = {
        "cancer_type": "Non-Small Cell Lung Cancer",
        "cancer_stage": "Stage IV",
        "biomarkers": ["EGFR+", "PD-L1 80%"],
        "prior_treatments": ["Carboplatin/Pemetrexed"],
        "lines_of_therapy": 1,
        "age": 62,
        "sex": "male",
        "ecog_score": 1,
        "key_labs": {"wbc": 5.2},
        "location_zip": "10001",
        "willing_to_travel_miles": 100,
        "additional_conditions": [],
        "additional_notes": None,
    }
    base.update(overrides)
    return base


SAMPLE_CTGOV_STUDY = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT00000001",
            "briefTitle": "Test Study of Drug X in NSCLC",
        },
        "statusModule": {
            "overallStatus": "RECRUITING",
            "phases": ["PHASE2", "PHASE3"],
        },
        "eligibilityModule": {
            "eligibilityCriteria": "Inclusion:\\n- Age >= 18\\nExclusion:\\n- Prior brain mets",
            "sex": "ALL",
            "minimumAge": "18 Years",
            "maximumAge": "75 Years",
        },
        "conditionsModule": {
            "conditions": ["Non-Small Cell Lung Cancer", "NSCLC"],
        },
        "descriptionModule": {
            "briefSummary": "A phase 2/3 trial testing Drug X.",
        },
        "contactsLocationsModule": {
            "locations": [
                {
                    "facility": "Memorial Sloan Kettering",
                    "city": "New York",
                    "state": "New York",
                    "country": "United States",
                    "status": "RECRUITING",
                    "geoPoint": {"lat": 40.76, "lon": -73.96},
                },
                {
                    "facility": "MD Anderson",
                    "city": "Houston",
                    "state": "Texas",
                    "country": "United States",
                    "status": "RECRUITING",
                    "geoPoint": {"lat": 29.71, "lon": -95.40},
                },
            ],
        },
        "armsInterventionsModule": {
            "interventions": [
                {"name": "Drug X", "type": "DRUG"},
                {"name": "Placebo", "type": "DRUG"},
            ],
        },
    }
}


# ---------------------------------------------------------------------------
# PatientProfile validation tests
# ---------------------------------------------------------------------------

class TestPatientProfile:
    def test_valid_profile(self):
        p = PatientProfile(**_valid_patient())
        assert p.cancer_type == "Non-Small Cell Lung Cancer"
        assert p.age == 62
        assert p.sex == "male"

    def test_valid_female(self):
        p = PatientProfile(**_valid_patient(sex="female"))
        assert p.sex == "female"

    def test_defaults_applied(self):
        """Minimal required fields should still work with defaults."""
        p = PatientProfile(
            cancer_type="TNBC",
            cancer_stage="Stage III",
            age=45,
            sex="female",
            location_zip="90001",
        )
        assert p.lines_of_therapy == 0
        assert p.biomarkers == []
        assert p.willing_to_travel_miles == 50
        assert p.ecog_score is None

    def test_invalid_age_too_high(self):
        with pytest.raises(ValidationError):
            PatientProfile(**_valid_patient(age=200))

    def test_invalid_age_negative(self):
        with pytest.raises(ValidationError):
            PatientProfile(**_valid_patient(age=-1))

    def test_invalid_sex(self):
        with pytest.raises(ValidationError):
            PatientProfile(**_valid_patient(sex="other"))

    def test_invalid_sex_capitalized(self):
        with pytest.raises(ValidationError):
            PatientProfile(**_valid_patient(sex="Male"))

    def test_missing_required_cancer_type(self):
        data = _valid_patient()
        del data["cancer_type"]
        with pytest.raises(ValidationError):
            PatientProfile(**data)

    def test_missing_required_age(self):
        data = _valid_patient()
        del data["age"]
        with pytest.raises(ValidationError):
            PatientProfile(**data)

    def test_missing_required_sex(self):
        data = _valid_patient()
        del data["sex"]
        with pytest.raises(ValidationError):
            PatientProfile(**data)

    def test_missing_required_location_zip(self):
        data = _valid_patient()
        del data["location_zip"]
        with pytest.raises(ValidationError):
            PatientProfile(**data)

    def test_zip_too_short(self):
        with pytest.raises(ValidationError):
            PatientProfile(**_valid_patient(location_zip="123"))

    def test_ecog_out_of_range(self):
        with pytest.raises(ValidationError):
            PatientProfile(**_valid_patient(ecog_score=5))

    def test_lines_of_therapy_negative(self):
        with pytest.raises(ValidationError):
            PatientProfile(**_valid_patient(lines_of_therapy=-1))


# ---------------------------------------------------------------------------
# _extract_study tests
# ---------------------------------------------------------------------------

class TestExtractStudy:
    def test_full_study(self):
        result = _extract_study(SAMPLE_CTGOV_STUDY)
        assert result["nct_id"] == "NCT00000001"
        assert result["brief_title"] == "Test Study of Drug X in NSCLC"
        assert result["overall_status"] == "RECRUITING"
        assert result["phase"] == "Phase 2, Phase 3"
        assert "Non-Small Cell Lung Cancer" in result["conditions"]
        assert result["sex"] == "ALL"
        assert result["minimum_age"] == "18 Years"
        assert result["maximum_age"] == "75 Years"
        assert len(result["interventions"]) == 2
        assert "DRUG: Drug X" in result["interventions"]
        assert len(result["locations"]) == 2

    def test_empty_study(self):
        """Gracefully handle a study with no protocolSection."""
        result = _extract_study({})
        assert result["nct_id"] == ""
        assert result["phase"] == "N/A"
        assert result["conditions"] == []
        assert result["interventions"] == []

    def test_missing_phases(self):
        study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT99999999"},
                "statusModule": {"overallStatus": "RECRUITING"},
            }
        }
        result = _extract_study(study)
        assert result["phase"] == "N/A"

    def test_intervention_without_type(self):
        study = {
            "protocolSection": {
                "armsInterventionsModule": {
                    "interventions": [{"name": "SomeTherapy"}],
                }
            }
        }
        result = _extract_study(study)
        assert result["interventions"] == ["SomeTherapy"]


# ---------------------------------------------------------------------------
# _parse_age_years tests
# ---------------------------------------------------------------------------

class TestParseAgeYears:
    def test_standard_format(self):
        assert _parse_age_years("18 Years") == 18

    def test_months_format(self):
        # "6 Months" -- first part is the number
        assert _parse_age_years("6 Months") == 6

    def test_just_number(self):
        assert _parse_age_years("65") == 65

    def test_empty_string(self):
        assert _parse_age_years("") is None

    def test_none_like(self):
        assert _parse_age_years("") is None

    def test_non_numeric(self):
        assert _parse_age_years("N/A") is None

    def test_75_years(self):
        assert _parse_age_years("75 Years") == 75


# ---------------------------------------------------------------------------
# _haversine_miles tests
# ---------------------------------------------------------------------------

class TestHaversineMiles:
    def test_same_point(self):
        assert _haversine_miles(40.0, -74.0, 40.0, -74.0) == 0.0

    def test_nyc_to_la(self):
        # NYC (40.71, -74.01) to LA (34.05, -118.24) ~= 2,451 miles
        d = _haversine_miles(40.71, -74.01, 34.05, -118.24)
        assert 2400 < d < 2500

    def test_nyc_to_boston(self):
        # NYC to Boston ~= 190 miles
        d = _haversine_miles(40.71, -74.01, 42.36, -71.06)
        assert 150 < d < 220

    def test_symmetry(self):
        d1 = _haversine_miles(40.71, -74.01, 34.05, -118.24)
        d2 = _haversine_miles(34.05, -118.24, 40.71, -74.01)
        assert abs(d1 - d2) < 0.01


# ---------------------------------------------------------------------------
# find_nearest_site tests
# ---------------------------------------------------------------------------

class TestFindNearestSite:
    def test_finds_nearest(self):
        locations = [
            {
                "facility": "NYC Hospital",
                "city": "New York",
                "state": "NY",
                "country": "US",
                "status": "RECRUITING",
                "geoPoint": {"lat": 40.76, "lon": -73.96},
            },
            {
                "facility": "Houston Clinic",
                "city": "Houston",
                "state": "TX",
                "country": "US",
                "status": "RECRUITING",
                "geoPoint": {"lat": 29.71, "lon": -95.40},
            },
        ]
        # ZIP 10001 is NYC
        site, distance = find_nearest_site(locations, "10001")
        assert site is not None
        assert site["facility"] == "NYC Hospital"
        assert distance is not None
        assert distance < 50  # Should be very close

    def test_empty_locations(self):
        site, distance = find_nearest_site([], "10001")
        assert site is None
        assert distance is None

    def test_locations_without_geopoint(self):
        locations = [{"facility": "NoGeo Hospital", "city": "Somewhere"}]
        site, distance = find_nearest_site(locations, "10001")
        assert site is None
        assert distance is None

    def test_mixed_locations(self):
        """One location with geo, one without -- should pick the one with geo."""
        locations = [
            {"facility": "NoGeo", "city": "X"},
            {
                "facility": "HasGeo",
                "city": "Y",
                "state": "NY",
                "country": "US",
                "status": "RECRUITING",
                "geoPoint": {"lat": 40.76, "lon": -73.96},
            },
        ]
        site, distance = find_nearest_site(locations, "10001")
        assert site is not None
        assert site["facility"] == "HasGeo"


# ---------------------------------------------------------------------------
# FastAPI endpoint tests
# ---------------------------------------------------------------------------

class TestEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_intake_valid(self, client):
        resp = client.post("/api/intake", json=_valid_patient())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["patient"]["cancer_type"] == "Non-Small Cell Lung Cancer"

    def test_intake_invalid_age(self, client):
        resp = client.post("/api/intake", json=_valid_patient(age=200))
        assert resp.status_code == 422

    def test_intake_invalid_sex(self, client):
        resp = client.post("/api/intake", json=_valid_patient(sex="other"))
        assert resp.status_code == 422

    def test_intake_missing_required(self, client):
        resp = client.post("/api/intake", json={"age": 50})
        assert resp.status_code == 422

    def test_intake_minimal_valid(self, client):
        """Only required fields."""
        resp = client.post("/api/intake", json={
            "cancer_type": "TNBC",
            "cancer_stage": "Stage III",
            "age": 45,
            "sex": "female",
            "location_zip": "90001",
        })
        assert resp.status_code == 200

    def test_trial_detail_not_found(self, client):
        """The /api/trials endpoint should return 404 for nonexistent trials
        but that requires a network call. We just test the route exists."""
        # This will attempt a real network call; we just check we get a response
        # (might be 404, might be a network error depending on environment)
        resp = client.get("/api/trials/NCT_DOES_NOT_EXIST_99999")
        assert resp.status_code in (404, 500, 502, 503)
