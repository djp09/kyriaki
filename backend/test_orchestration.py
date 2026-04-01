"""Tests for the agent orchestration layer: dispatcher, MatchingAgent, DossierAgent, gates."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents import AgentContext, AgentResult, BaseAgent, DossierAgent, MatchingAgent
from db_models import AgentEventDB, GateStatus, HumanGateDB, TaskStatus
from dispatcher import _registry, dispatch, register_agent
from models import DossierRequest, GateResolution, TaskResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_patient_data():
    return {
        "cancer_type": "Non-Small Cell Lung Cancer",
        "cancer_stage": "Stage IV",
        "biomarkers": ["EGFR+", "PD-L1 80%"],
        "prior_treatments": ["Carboplatin/Pemetrexed"],
        "lines_of_therapy": 1,
        "age": 62,
        "sex": "male",
        "ecog_score": 1,
        "key_labs": None,
        "location_zip": "10001",
        "willing_to_travel_miles": 100,
        "additional_conditions": [],
        "additional_notes": None,
    }


@pytest.fixture
def sample_match_output():
    return {
        "patient_summary": "You are a 62-year-old navigating Stage IV NSCLC.",
        "total_trials_screened": 5,
        "matches": [
            {
                "nct_id": "NCT12345678",
                "brief_title": "Study of Drug X in NSCLC",
                "phase": "Phase 2",
                "overall_status": "RECRUITING",
                "conditions": ["NSCLC"],
                "brief_summary": "A study of Drug X.",
                "eligibility_criteria": "Inclusion: Stage IV NSCLC, EGFR+\nExclusion: Brain mets",
                "match_score": 85,
                "match_explanation": "Strong match for this trial.",
                "inclusion_evaluations": [],
                "exclusion_evaluations": [],
                "flags_for_oncologist": [],
                "nearest_site": None,
                "distance_miles": None,
                "interventions": ["DRUG: Drug X"],
            },
            {
                "nct_id": "NCT87654321",
                "brief_title": "Study of Drug Y",
                "phase": "Phase 3",
                "overall_status": "RECRUITING",
                "conditions": ["NSCLC"],
                "brief_summary": "A study of Drug Y.",
                "eligibility_criteria": "Inclusion: Stage IV NSCLC\nExclusion: Autoimmune",
                "match_score": 60,
                "match_explanation": "Possible match.",
                "inclusion_evaluations": [],
                "exclusion_evaluations": [],
                "flags_for_oncologist": [],
                "nearest_site": None,
                "distance_miles": None,
                "interventions": ["DRUG: Drug Y"],
            },
        ],
    }


class FakeSession:
    """Minimal mock for AsyncSession that tracks added objects and supports get()."""

    def __init__(self):
        self.added: list[Any] = []
        self._store: dict[tuple, Any] = {}

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if hasattr(obj, "id") and obj.id:
            self._store[(type(obj), obj.id)] = obj

    async def flush(self) -> None:
        for obj in self.added:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()
            if hasattr(obj, "id") and obj.id:
                self._store[(type(obj), obj.id)] = obj

    async def get(self, model_cls: type, obj_id: Any) -> Any:
        return self._store.get((model_cls, obj_id))


# ---------------------------------------------------------------------------
# Agent registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_matching_agent_registered(self):
        assert "matching" in _registry
        assert _registry["matching"] is MatchingAgent

    def test_dossier_agent_registered(self):
        assert "dossier" in _registry
        assert _registry["dossier"] is DossierAgent

    def test_register_custom_agent(self):
        @register_agent
        class TestAgent(BaseAgent):
            agent_type = "test_custom"

            async def execute(self, ctx: AgentContext) -> AgentResult:
                return AgentResult(success=True)

        assert "test_custom" in _registry
        # Clean up
        del _registry["test_custom"]


# ---------------------------------------------------------------------------
# Dispatcher tests
# ---------------------------------------------------------------------------


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_unknown_agent_raises(self):
        session = FakeSession()
        with pytest.raises(ValueError, match="Unknown agent type"):
            await dispatch(session, "nonexistent", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_dispatch_successful_task(self, sample_patient_data):
        """Dispatch a matching task with mocked match_trials."""
        session = FakeSession()
        patient_id = uuid.uuid4()

        mock_match = MagicMock()
        mock_match.model_dump.return_value = {"nct_id": "NCT123", "match_score": 80}

        mock_result = {
            "patient_summary": "Summary",
            "matches": [mock_match],
            "total_trials_screened": 5,
        }

        with patch("agents.match_trials", new_callable=AsyncMock, return_value=mock_result):
            task = await dispatch(
                session, "matching", patient_id, input_data={"patient": sample_patient_data, "max_results": 10}
            )

        assert task.status == TaskStatus.completed.value
        assert task.output_data["patient_summary"] == "Summary"
        assert task.output_data["total_trials_screened"] == 5
        assert task.completed_at is not None
        assert task.error is None

        # Verify events were emitted
        events = [obj for obj in session.added if isinstance(obj, AgentEventDB)]
        event_types = [e.event_type for e in events]
        assert "started" in event_types
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_dispatch_failed_task(self, sample_patient_data):
        """Agent exception results in failed task status."""
        session = FakeSession()
        patient_id = uuid.uuid4()

        with patch("agents.match_trials", new_callable=AsyncMock, side_effect=RuntimeError("API down")):
            task = await dispatch(
                session, "matching", patient_id, input_data={"patient": sample_patient_data, "max_results": 10}
            )

        assert task.status == TaskStatus.failed.value
        assert "RuntimeError" in task.error
        assert "API down" in task.error
        assert task.completed_at is not None

        events = [obj for obj in session.added if isinstance(obj, AgentEventDB)]
        event_types = [e.event_type for e in events]
        assert "failed" in event_types

    @pytest.mark.asyncio
    async def test_dispatch_blocked_task_with_gate(self, sample_patient_data, sample_match_output):
        """DossierAgent creates a human gate, task goes to blocked."""
        session = FakeSession()
        patient_id = uuid.uuid4()

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "revised_score": 90,
                        "score_justification": "Strong match",
                        "criteria_analysis": [],
                        "patient_summary": "Good candidate",
                        "clinical_summary": "Meets criteria",
                        "next_steps": ["Contact site"],
                        "flags": [],
                    }
                )
            )
        ]

        with (
            patch("agents._paced_claude_call", new_callable=AsyncMock, return_value=mock_response),
            patch("agents._get_client", return_value=MagicMock()),
        ):
            task = await dispatch(
                session,
                "dossier",
                patient_id,
                input_data={
                    "patient": sample_patient_data,
                    "matches": sample_match_output["matches"][:1],
                    "patient_summary": "Summary",
                    "top_n": 1,
                },
            )

        assert task.status == TaskStatus.blocked.value
        assert task.output_data is not None
        assert "dossier" in task.output_data

        # Verify gate was created
        gates = [obj for obj in session.added if isinstance(obj, HumanGateDB)]
        assert len(gates) == 1
        assert gates[0].gate_type == "dossier_review"
        assert gates[0].status == GateStatus.pending.value

    @pytest.mark.asyncio
    async def test_dispatch_with_parent_task(self, sample_patient_data):
        """Tasks can reference a parent task."""
        session = FakeSession()
        patient_id = uuid.uuid4()
        parent_id = uuid.uuid4()

        mock_match = MagicMock()
        mock_match.model_dump.return_value = {"nct_id": "NCT123", "match_score": 80}
        mock_result = {"patient_summary": "S", "matches": [mock_match], "total_trials_screened": 1}

        with patch("agents.match_trials", new_callable=AsyncMock, return_value=mock_result):
            task = await dispatch(
                session,
                "matching",
                patient_id,
                input_data={"patient": sample_patient_data, "max_results": 5},
                parent_task_id=parent_id,
            )

        assert task.parent_task_id == parent_id


# ---------------------------------------------------------------------------
# MatchingAgent tests
# ---------------------------------------------------------------------------


class TestMatchingAgent:
    @pytest.mark.asyncio
    async def test_execute_wraps_match_trials(self, sample_patient_data):
        """MatchingAgent wraps match_trials and serializes output."""
        agent = MatchingAgent()
        emitted = []

        async def mock_emit(event_type, data=None):
            emitted.append((event_type, data))

        ctx = AgentContext(
            task_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            input_data={"patient": sample_patient_data, "max_results": 5},
            emit=mock_emit,
        )

        mock_match = MagicMock()
        mock_match.model_dump.return_value = {"nct_id": "NCT123", "match_score": 88}

        mock_result = {"patient_summary": "Summary text", "matches": [mock_match], "total_trials_screened": 3}

        with patch("agents.match_trials", new_callable=AsyncMock, return_value=mock_result):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.output_data["patient_summary"] == "Summary text"
        assert result.output_data["total_trials_screened"] == 3
        assert len(result.output_data["matches"]) == 1
        assert result.gate_request is None

        # Progress event emitted
        assert any(e[0] == "progress" for e in emitted)

    @pytest.mark.asyncio
    async def test_execute_propagates_exception(self, sample_patient_data):
        """MatchingAgent lets exceptions bubble up (dispatcher catches them)."""
        agent = MatchingAgent()

        async def mock_emit(event_type, data=None):
            pass

        ctx = AgentContext(
            task_id=uuid.uuid4(), patient_id=uuid.uuid4(), input_data={"patient": sample_patient_data}, emit=mock_emit
        )

        with (
            patch("agents.match_trials", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await agent.execute(ctx)


# ---------------------------------------------------------------------------
# DossierAgent tests
# ---------------------------------------------------------------------------


class TestDossierAgent:
    @pytest.mark.asyncio
    async def test_execute_produces_dossier_and_gate(self, sample_patient_data, sample_match_output):
        """DossierAgent produces a dossier and requests a human gate."""
        agent = DossierAgent()
        emitted = []

        async def mock_emit(event_type, data=None):
            emitted.append((event_type, data))

        ctx = AgentContext(
            task_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            input_data={
                "patient": sample_patient_data,
                "matches": sample_match_output["matches"][:1],
                "patient_summary": "Summary",
                "top_n": 1,
            },
            emit=mock_emit,
        )

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "revised_score": 92,
                        "score_justification": "Very strong match",
                        "criteria_analysis": [
                            {
                                "criterion": "Stage IV",
                                "type": "inclusion",
                                "status": "met",
                                "evidence": "Patient is Stage IV",
                                "notes": "",
                            }
                        ],
                        "patient_summary": "You are a good candidate.",
                        "clinical_summary": "Meets all criteria.",
                        "next_steps": ["Call the site"],
                        "flags": ["Verify labs"],
                    }
                )
            )
        ]

        with (
            patch("agents._paced_claude_call", new_callable=AsyncMock, return_value=mock_response),
            patch("agents._get_client", return_value=MagicMock()),
        ):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.gate_request is not None
        assert result.gate_request.gate_type == "dossier_review"

        dossier = result.output_data["dossier"]
        assert "sections" in dossier
        assert len(dossier["sections"]) == 1
        assert dossier["sections"][0]["nct_id"] == "NCT12345678"
        assert dossier["sections"][0]["revised_score"] == 92

        # Progress events
        progress_events = [e for e in emitted if e[0] == "progress"]
        assert len(progress_events) >= 2  # deep_analysis + analyzing_trial

    @pytest.mark.asyncio
    async def test_execute_handles_parse_failure(self, sample_patient_data, sample_match_output):
        """DossierAgent handles unparseable Claude response gracefully."""
        agent = DossierAgent()

        async def mock_emit(event_type, data=None):
            pass

        ctx = AgentContext(
            task_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            input_data={
                "patient": sample_patient_data,
                "matches": sample_match_output["matches"][:1],
                "patient_summary": "Summary",
                "top_n": 1,
            },
            emit=mock_emit,
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="This is not valid JSON at all")]

        with (
            patch("agents._paced_claude_call", new_callable=AsyncMock, return_value=mock_response),
            patch("agents._get_client", return_value=MagicMock()),
        ):
            result = await agent.execute(ctx)

        assert result.success is True
        section = result.output_data["dossier"]["sections"][0]
        assert "analysis_error" in section


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_task_response_serialization(self):
        resp = TaskResponse(
            task_id=str(uuid.uuid4()),
            agent_type="matching",
            status="completed",
            output_data={"key": "value"},
            created_at="2026-04-01T00:00:00+00:00",
        )
        assert resp.status == "completed"
        assert resp.output_data == {"key": "value"}

    def test_dossier_request_validation(self):
        req = DossierRequest(matching_task_id=str(uuid.uuid4()), top_n=5)
        assert req.top_n == 5

    def test_dossier_request_default_top_n(self):
        req = DossierRequest(matching_task_id=str(uuid.uuid4()))
        assert req.top_n == 3

    def test_gate_resolution_approved(self):
        res = GateResolution(status="approved", resolved_by="dr.smith@hospital.org", notes="Looks good")
        assert res.status == "approved"

    def test_gate_resolution_rejected(self):
        res = GateResolution(status="rejected", resolved_by="navigator1")
        assert res.status == "rejected"
        assert res.notes is None

    def test_gate_resolution_invalid_status(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            GateResolution(status="maybe", resolved_by="someone")


# ---------------------------------------------------------------------------
# DB model tests
# ---------------------------------------------------------------------------


class TestDBModels:
    def test_task_status_enum(self):
        assert TaskStatus.pending.value == "pending"
        assert TaskStatus.blocked.value == "blocked"
        assert len(TaskStatus) == 5

    def test_gate_status_enum(self):
        assert GateStatus.pending.value == "pending"
        assert GateStatus.approved.value == "approved"
        assert GateStatus.rejected.value == "rejected"
        assert len(GateStatus) == 3
