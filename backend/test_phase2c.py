"""Tests for Phase 2C: EnrollmentAgent, MonitorAgent, OutreachAgent, auto-chaining."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from agent_loop import Scratchpad
from agents import AgentContext, EnrollmentAgent, MonitorAgent, OutreachAgent
from models import EnrollmentRequest, GateResolution, MonitorRequest, OutreachRequest, PatientProfile
from tools import ToolResult

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


_MOCK_PATIENT = PatientProfile(
    cancer_type="Triple Negative Breast Cancer",
    cancer_stage="Stage IV",
    biomarkers=["ER-", "PR-", "HER2-"],
    prior_treatments=["AC-T"],
    lines_of_therapy=1,
    age=45,
    sex="female",
    ecog_score=0,
    location_zip="90210",
    willing_to_travel_miles=100,
)


@pytest.fixture(autouse=True)
def _mock_patient_loader():
    with patch("agents.load_patient_from_db", AsyncMock(return_value=_MOCK_PATIENT)):
        yield


def _make_ctx(input_data):
    emitted = []

    async def mock_emit(event_type, data=None):
        emitted.append((event_type, data))

    ctx = AgentContext(task_id=uuid.uuid4(), patient_id=uuid.uuid4(), input_data=input_data, emit=mock_emit)
    return ctx, emitted


# ---------------------------------------------------------------------------
# EnrollmentAgent tests
# ---------------------------------------------------------------------------


class TestEnrollmentAgent:
    @pytest.mark.asyncio
    async def test_produces_packet_and_gate(self, sample_patient, sample_dossier):
        """Verifies execute() fetches site info then runs the three
        generators in parallel (packet/prep/outreach), assembling the
        outputs into a gated AgentResult."""

        agent = EnrollmentAgent()
        ctx, emitted = _make_ctx(
            {
                "dossier": sample_dossier,
                "trial_nct_id": "NCT05107674",
            }
        )

        async def fake_claude(prompt, **kwargs):
            # Route by unique schema keys baked into each prompt template.
            if "patient_demographics" in prompt:  # enrollment_packet
                return ToolResult(
                    success=True,
                    data={
                        "screening_checklist": [{"item": "CBC", "category": "labs", "status": "needed"}],
                        "diagnosis_summary": "TNBC Stage IV",
                    },
                )
            if "documents_to_bring" in prompt:  # patient_prep
                return ToolResult(
                    success=True,
                    data={
                        "what_to_expect": "You will visit the site.",
                        "documents_to_bring": ["photo ID"],
                    },
                )
            if "subject_line" in prompt:  # outreach_message
                return ToolResult(
                    success=True,
                    data={
                        "subject_line": "Patient candidate",
                        "message_body": "Dear CRC...",
                        "follow_up_notes": "Follow up in 3 days.",
                    },
                )
            return ToolResult(success=False, error=f"Unexpected prompt: {prompt[:100]}")

        mock_fetch = AsyncMock(
            return_value=ToolResult(
                success=True,
                data={
                    "locations": [
                        {
                            "facility": "Memorial Cancer Center",
                            "city": "Los Angeles",
                            "state": "CA",
                            "contacts": [{"name": "Dr. Jane Coordinator"}],
                        }
                    ]
                },
            )
        )

        with (
            patch("agents.claude_json_call", side_effect=fake_claude),
            patch("agents.fetch_trial_tool", mock_fetch),
        ):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.gate_request is not None
        assert result.gate_request.gate_type == "enrollment_review"
        assert result.output_data["trial_nct_id"] == "NCT05107674"
        assert result.output_data["patient_packet"]["screening_checklist"][0]["item"] == "CBC"
        assert result.output_data["patient_prep_guide"]["what_to_expect"]
        assert result.output_data["outreach_draft"]["subject_line"] == "Patient candidate"
        event_names = {name for name, _ in emitted}
        assert "enrollment.fetch_site_start" in event_names
        assert "enrollment.generation_start" in event_names
        assert "enrollment.generation_complete" in event_names

    @pytest.mark.asyncio
    async def test_runs_handlers_in_parallel(self, sample_dossier):
        """Verifies that packet, prep, and outreach generators run
        concurrently rather than sequentially. We enforce this by making
        each mocked Claude call wait on a shared barrier — if they run
        in sequence, the barrier will deadlock and the test will time out."""
        import asyncio

        agent = EnrollmentAgent()
        ctx, _ = _make_ctx(
            {
                "dossier": sample_dossier,
                "trial_nct_id": "NCT05107674",
            }
        )

        barrier = asyncio.Barrier(3)

        async def fake_claude(prompt, **kwargs):
            await barrier.wait()
            if "patient_demographics" in prompt:
                return ToolResult(success=True, data={"screening_checklist": []})
            if "documents_to_bring" in prompt:
                return ToolResult(success=True, data={"what_to_expect": "OK"})
            return ToolResult(success=True, data={"subject_line": "Hi"})

        mock_fetch = AsyncMock(return_value=ToolResult(success=True, data={"locations": []}))

        with (
            patch("agents.claude_json_call", side_effect=fake_claude),
            patch("agents.fetch_trial_tool", mock_fetch),
        ):
            result = await asyncio.wait_for(agent.execute(ctx), timeout=5.0)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_missing_dossier_section(self, sample_patient, sample_dossier):
        agent = EnrollmentAgent()
        ctx, _ = _make_ctx(
            {
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

        mock_scratchpad = Scratchpad(
            state={
                "watches": {"NCT123": {"nct_id": "NCT123", "last_status": "RECRUITING", "last_site_count": 5}},
                "changes": [
                    {
                        "nct_id": "NCT123",
                        "change_type": "status_changed",
                        "old_status": "RECRUITING",
                        "new_status": "ACTIVE_NOT_RECRUITING",
                    }
                ],
                "checked": {"NCT123"},
            }
        )
        mock_loop = AsyncMock(return_value=mock_scratchpad)

        with patch("agents.run_agent_loop", mock_loop):
            result = await agent.execute(ctx)

        assert result.success is True
        assert len(result.output_data["changes"]) == 1
        assert result.output_data["changes"][0]["change_type"] == "status_changed"

    @pytest.mark.asyncio
    async def test_no_changes(self):
        agent = MonitorAgent()
        ctx, _ = _make_ctx({"watches": [{"nct_id": "NCT123", "last_status": "RECRUITING", "last_site_count": 3}]})

        mock_scratchpad = Scratchpad(state={"watches": {}, "changes": [], "checked": {"NCT123"}})
        mock_loop = AsyncMock(return_value=mock_scratchpad)

        with patch("agents.run_agent_loop", mock_loop):
            result = await agent.execute(ctx)

        assert result.success is True
        assert len(result.output_data["changes"]) == 0


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

        mock_scratchpad = Scratchpad(
            state={
                "outreach_draft": {"subject_line": "Patient candidate", "message_body": "Dear CRC..."},
                "trial_nct_id": "NCT123",
                "contacts": [{"name": "Dr. Smith", "role": "CRC", "email": "smith@ucla.edu", "facility": "UCLA"}],
                "final_message": "Dear Dr. Smith, ...",
                "subject_line": "Patient candidate",
            }
        )
        mock_loop = AsyncMock(return_value=mock_scratchpad)

        with patch("agents.run_agent_loop", mock_loop):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.gate_request is not None
        assert result.gate_request.gate_type == "outreach_review"
        assert len(result.output_data["contacts"]) == 1
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

        mock_scratchpad = Scratchpad(
            state={
                "outreach_draft": {"message_body": "Hello..."},
                "trial_nct_id": "NCT123",
                "contacts": [],
                "final_message": "Hello...",
                "subject_line": "Pre-screened patient candidate for NCT123",
            }
        )
        mock_loop = AsyncMock(return_value=mock_scratchpad)

        with patch("agents.run_agent_loop", mock_loop):
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
