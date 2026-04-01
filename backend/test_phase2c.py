"""Tests for Phase 2C: EnrollmentAgent, MonitorAgent, OutreachAgent, auto-chaining."""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents import AgentContext, EnrollmentAgent, MonitorAgent, OutreachAgent
from models import EnrollmentRequest, GateResolution, MonitorRequest, OutreachRequest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_patient():
    return {
        "cancer_type": "Triple Negative Breast Cancer",
        "cancer_stage": "Stage IV",
        "biomarkers": ["ER-", "PR-", "HER2-"],
        "prior_treatments": ["AC-T"],
        "lines_of_therapy": 1,
        "age": 45,
        "sex": "female",
        "ecog_score": 0,
        "location_zip": "90210",
        "willing_to_travel_miles": 100,
    }


@pytest.fixture
def sample_dossier():
    return {
        "patient_summary": "A 45-year-old woman with Stage IV TNBC.",
        "generated_at": "2026-04-01T00:00:00Z",
        "sections": [
            {
                "nct_id": "NCT05107674",
                "brief_title": "A Study of NX-1607",
                "revised_score": 82,
                "score_justification": "Strong match based on criteria.",
                "clinical_summary": "Patient meets key inclusion criteria.",
                "criteria_analysis": [
                    {"criterion": "Age >= 18", "type": "inclusion", "status": "met", "evidence": "Age 45", "notes": ""}
                ],
                "patient_summary": "You are a good candidate.",
                "next_steps": ["Contact trial site"],
                "flags": ["Verify labs"],
            }
        ],
    }


def _make_ctx(input_data):
    emitted = []

    async def mock_emit(event_type, data=None):
        emitted.append((event_type, data))

    ctx = AgentContext(task_id=uuid.uuid4(), patient_id=uuid.uuid4(), input_data=input_data, emit=mock_emit)
    return ctx, emitted


def _mock_sonnet_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(data))]
    return resp


# ---------------------------------------------------------------------------
# EnrollmentAgent tests
# ---------------------------------------------------------------------------


class TestEnrollmentAgent:
    @pytest.mark.asyncio
    async def test_produces_packet_and_gate(self, sample_patient, sample_dossier):
        agent = EnrollmentAgent()
        ctx, emitted = _make_ctx(
            {
                "patient": sample_patient,
                "dossier": sample_dossier,
                "trial_nct_id": "NCT05107674",
            }
        )

        mock_trial = {"locations": [{"facility": "UCLA", "city": "LA", "state": "CA", "contacts": []}]}
        packet_resp = _mock_sonnet_response({"screening_checklist": [{"item": "CBC", "category": "labs"}]})
        prep_resp = _mock_sonnet_response({"what_to_expect": "You will visit the site."})
        outreach_resp = _mock_sonnet_response({"subject_line": "Patient candidate", "message_body": "Dear CRC..."})

        with (
            patch("agents.get_trial", new_callable=AsyncMock, return_value=mock_trial),
            patch(
                "agents._paced_claude_call", new_callable=AsyncMock, side_effect=[packet_resp, prep_resp, outreach_resp]
            ),
            patch("agents._get_client", return_value=MagicMock()),
        ):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.gate_request is not None
        assert result.gate_request.gate_type == "enrollment_review"
        assert "patient_packet" in result.output_data
        assert "patient_prep_guide" in result.output_data
        assert "outreach_draft" in result.output_data
        assert result.output_data["trial_nct_id"] == "NCT05107674"

        progress_steps = [e[1]["step"] for e in emitted if e[0] == "progress"]
        assert "generating_packet" in progress_steps
        assert "generating_prep_guide" in progress_steps
        assert "generating_outreach_draft" in progress_steps

    @pytest.mark.asyncio
    async def test_missing_dossier_section(self, sample_patient, sample_dossier):
        agent = EnrollmentAgent()
        ctx, _ = _make_ctx(
            {
                "patient": sample_patient,
                "dossier": sample_dossier,
                "trial_nct_id": "NCT_NONEXISTENT",
            }
        )

        result = await agent.execute(ctx)
        assert result.success is False
        assert "No dossier section found" in result.error


# ---------------------------------------------------------------------------
# MonitorAgent tests
# ---------------------------------------------------------------------------


class TestMonitorAgent:
    @pytest.mark.asyncio
    async def test_detects_status_change(self):
        agent = MonitorAgent()
        ctx, emitted = _make_ctx({"watches": [{"nct_id": "NCT123", "last_status": "RECRUITING", "last_site_count": 5}]})

        changed_trial = {"overall_status": "ACTIVE_NOT_RECRUITING", "locations": [1, 2, 3, 4, 5]}

        with patch("agents.get_trial", new_callable=AsyncMock, return_value=changed_trial):
            result = await agent.execute(ctx)

        assert result.success is True
        assert len(result.output_data["changes"]) == 1
        assert result.output_data["changes"][0]["change_type"] == "status_changed"
        assert result.output_data["changes"][0]["new_status"] == "ACTIVE_NOT_RECRUITING"

    @pytest.mark.asyncio
    async def test_detects_new_sites(self):
        agent = MonitorAgent()
        ctx, _ = _make_ctx({"watches": [{"nct_id": "NCT123", "last_status": "RECRUITING", "last_site_count": 3}]})

        trial = {"overall_status": "RECRUITING", "locations": [1, 2, 3, 4, 5]}

        with patch("agents.get_trial", new_callable=AsyncMock, return_value=trial):
            result = await agent.execute(ctx)

        assert result.success is True
        sites_added = [c for c in result.output_data["changes"] if c["change_type"] == "sites_added"]
        assert len(sites_added) == 1
        assert sites_added[0]["new_count"] == 5

    @pytest.mark.asyncio
    async def test_no_changes(self):
        agent = MonitorAgent()
        ctx, _ = _make_ctx({"watches": [{"nct_id": "NCT123", "last_status": "RECRUITING", "last_site_count": 3}]})

        trial = {"overall_status": "RECRUITING", "locations": [1, 2, 3]}

        with patch("agents.get_trial", new_callable=AsyncMock, return_value=trial):
            result = await agent.execute(ctx)

        assert result.success is True
        assert len(result.output_data["changes"]) == 0

    @pytest.mark.asyncio
    async def test_trial_not_found(self):
        agent = MonitorAgent()
        ctx, _ = _make_ctx({"watches": [{"nct_id": "NCT999", "last_status": "RECRUITING", "last_site_count": 0}]})

        with patch("agents.get_trial", new_callable=AsyncMock, return_value=None):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.output_data["changes"][0]["change_type"] == "not_found"


# ---------------------------------------------------------------------------
# OutreachAgent tests
# ---------------------------------------------------------------------------


class TestOutreachAgent:
    @pytest.mark.asyncio
    async def test_produces_message_and_gate(self):
        agent = OutreachAgent()
        ctx, emitted = _make_ctx(
            {
                "outreach_draft": {"subject_line": "Patient candidate", "message_body": "Dear CRC..."},
                "trial_nct_id": "NCT123",
                "patient": {},
            }
        )

        trial = {
            "locations": [
                {
                    "facility": "UCLA",
                    "city": "LA",
                    "state": "CA",
                    "contacts": [{"name": "Dr. Smith", "role": "CRC", "email": "smith@ucla.edu", "phone": "555-1234"}],
                }
            ]
        }
        personalized = _mock_sonnet_response({"message_body": "Dear Dr. Smith, ..."})

        with (
            patch("agents.get_trial", new_callable=AsyncMock, return_value=trial),
            patch("agents._paced_claude_call", new_callable=AsyncMock, return_value=personalized),
            patch("agents._get_client", return_value=MagicMock()),
        ):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.gate_request is not None
        assert result.gate_request.gate_type == "outreach_review"
        assert len(result.output_data["contacts"]) == 1
        assert result.output_data["contacts"][0]["name"] == "Dr. Smith"
        assert "Dr. Smith" in result.output_data["final_message"]

    @pytest.mark.asyncio
    async def test_no_contacts(self):
        agent = OutreachAgent()
        ctx, _ = _make_ctx(
            {
                "outreach_draft": {"message_body": "Hello..."},
                "trial_nct_id": "NCT123",
                "patient": {},
            }
        )

        trial = {"locations": [{"facility": "UCLA", "city": "LA", "state": "CA", "contacts": []}]}

        with patch("agents.get_trial", new_callable=AsyncMock, return_value=trial):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.output_data["contacts"] == []
        assert result.output_data["final_message"] == "Hello..."


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestPhase2CModels:
    def test_enrollment_request(self):
        req = EnrollmentRequest(dossier_task_id=str(uuid.uuid4()), trial_nct_id="NCT05107674")
        assert req.trial_nct_id == "NCT05107674"

    def test_outreach_request(self):
        req = OutreachRequest(enrollment_task_id=str(uuid.uuid4()))
        assert req.enrollment_task_id

    def test_monitor_request(self):
        req = MonitorRequest(patient_id=str(uuid.uuid4()))
        assert req.patient_id

    def test_gate_resolution_with_chain(self):
        res = GateResolution(status="approved", resolved_by="nav1", chain_to_trial="NCT123")
        assert res.chain_to_trial == "NCT123"

    def test_gate_resolution_without_chain(self):
        res = GateResolution(status="approved", resolved_by="nav1")
        assert res.chain_to_trial is None


# ---------------------------------------------------------------------------
# Endpoint tests (SQLite only — skip on PostgreSQL)
# ---------------------------------------------------------------------------

_is_postgres = "postgresql" in os.environ.get("KYRIAKI_DATABASE_URL", "")


@pytest.mark.skipif(_is_postgres, reason="BaseHTTPMiddleware + asyncpg TestClient conflict")
class TestPhase2CEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from main import app

        with TestClient(app) as c:
            yield c

    def test_monitor_status(self, client):
        resp = client.get("/api/agents/monitor/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "interval_seconds" in data

    def test_enrollment_missing_task(self, client):
        resp = client.post(
            "/api/agents/enrollment",
            json={"dossier_task_id": str(uuid.uuid4()), "trial_nct_id": "NCT123"},
        )
        assert resp.status_code == 404

    def test_outreach_missing_task(self, client):
        resp = client.post(
            "/api/agents/outreach",
            json={"enrollment_task_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404
