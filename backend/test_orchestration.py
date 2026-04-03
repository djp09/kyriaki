"""Tests for the agent orchestration layer: dispatcher, MatchingAgent, DossierAgent, gates."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from agent_loop import Scratchpad, _build_tool_use_tools
from agents import MATCHING_TOOLS, AgentContext, DossierAgent, MatchingAgent
from db_models import AgentEventDB, AgentTaskDB, GateStatus, HumanGateDB, TaskStatus
from dispatcher import (
    dispatch,
    dispatch_background,
    get_or_create_pipeline,
    get_trial_watches,
    has_active_task,
    recover_stale_tasks,
    retry_task,
    upsert_trial_watches,
)
from models import (
    ActivityItem,
    DossierRequest,
    EventResponse,
    GateResolution,
    GateResponse,
    TaskDetailResponse,
    TaskResponse,
)
from tools import TokenUsage, ToolResult

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
        "willing_to_travel_miles": 50,
        "additional_conditions": [],
        "additional_notes": None,
    }


@pytest.fixture
def sample_match_output():
    return {
        "patient_summary": "You are a 62-year-old navigating Stage IV NSCLC.",
        "matches": [
            {
                "nct_id": "NCT12345678",
                "brief_title": "Study of Drug X in NSCLC",
                "phase": "Phase 2",
                "overall_status": "RECRUITING",
                "conditions": ["NSCLC"],
                "brief_summary": "A study of Drug X.",
                "eligibility_criteria": "Inclusion: Stage IV NSCLC...",
                "match_score": 85,
                "match_explanation": "Strong match based on cancer type and stage.",
                "inclusion_evaluations": [],
                "exclusion_evaluations": [],
                "flags_for_oncologist": [],
                "nearest_site": None,
                "distance_miles": None,
                "interventions": [],
            }
        ],
        "total_trials_screened": 5,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_matching_scratchpad(trials=None, analyses=None):
    """Build a pre-populated scratchpad for MatchingAgent tests."""

    if trials is None:
        trials = {
            "NCT123": {
                "nct_id": "NCT123",
                "brief_title": "Test Trial",
                "phase": "Phase 2",
                "overall_status": "RECRUITING",
                "conditions": ["NSCLC"],
                "brief_summary": "A test",
                "eligibility_criteria": "Age 18+",
                "locations": [],
                "interventions": [],
            }
        }
    if analyses is None:
        analyses = {
            "NCT123": {
                "match_score": 80,
                "match_explanation": "Good match",
                "inclusion_evaluations": [],
                "exclusion_evaluations": [],
                "flags_for_oncologist": [],
            }
        }

    scratchpad = Scratchpad(state={"trials_pool": trials, "analyses": analyses})
    scratchpad.add(0, "search", "Searching for trials", {}, "Found 1 trial", True)
    scratchpad.add(1, "analyze_batch", "Analyzing", {}, "Scored 1 trial", True)
    scratchpad.add(2, "finish", "Done", {}, "Agent decided to stop.", True)
    return scratchpad


# ---------------------------------------------------------------------------
# FakeSession for testing without DB
# ---------------------------------------------------------------------------


class _FakeResult:
    """Fake SQLAlchemy result that returns empty for all queries."""

    def scalars(self):
        return self

    def first(self):
        return None

    def all(self):
        return []

    def unique(self):
        return self


class FakeSession:
    def __init__(self):
        self.added = []
        self._flushed = False
        self._next_id = 1

    def add(self, obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def add_all(self, objs):
        for obj in objs:
            self.add(obj)

    async def flush(self):
        self._flushed = True

    async def get(self, model, pk):
        return None

    async def execute(self, stmt):
        return _FakeResult()


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
        """Dispatch a matching task with mocked direct pipeline."""
        session = FakeSession()
        patient_id = uuid.uuid4()

        scratchpad = _build_matching_scratchpad()
        mock_pool = scratchpad.state["trials_pool"]
        mock_analyses = scratchpad.state["analyses"]
        mock_summary = AsyncMock(return_value=ToolResult(success=True, data="Summary"))

        with (
            patch.object(MatchingAgent, "_do_search", AsyncMock(return_value=mock_pool)),
            patch.object(MatchingAgent, "_do_prescreen_and_analyze", AsyncMock(return_value=mock_analyses)),
            patch("agents.claude_text_call", mock_summary),
        ):
            task = await dispatch(
                session, "matching", patient_id, input_data={"patient": sample_patient_data, "max_results": 10}
            )

        assert task.status == TaskStatus.completed.value
        assert task.output_data["patient_summary"] == "Summary"
        assert task.completed_at is not None
        assert task.error is None

        events = [obj for obj in session.added if isinstance(obj, AgentEventDB)]
        event_types = [e.event_type for e in events]
        assert "started" in event_types
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_dispatch_failed_task(self, sample_patient_data):
        """Agent exception results in failed task status."""
        session = FakeSession()
        patient_id = uuid.uuid4()

        mock_search = AsyncMock(side_effect=RuntimeError("API down"))
        with patch("agents.search_and_merge_tool", mock_search):
            task = await dispatch(
                session, "matching", patient_id, input_data={"patient": sample_patient_data, "max_results": 10}
            )

        assert task.status == TaskStatus.failed.value
        assert "RuntimeError" in task.error
        assert task.completed_at is not None

    @pytest.mark.asyncio
    async def test_dispatch_blocked_task_with_gate(self, sample_patient_data, sample_match_output):
        """DossierAgent creates a human gate, task goes to blocked."""
        session = FakeSession()
        patient_id = uuid.uuid4()

        dossier_section = {
            "nct_id": "NCT12345678",
            "brief_title": "Study of Drug X in NSCLC",
            "revised_score": 90,
            "score_justification": "Strong match",
            "criteria_analysis": [],
            "patient_summary": "Good candidate",
            "clinical_summary": "Meets criteria",
            "next_steps": ["Contact site"],
            "flags": [],
        }

        mock_scratchpad = Scratchpad(state={"sections": {"NCT12345678": dossier_section}})
        mock_scratchpad.add(0, "deep_analyze", "Analyzing", {"nct_id": "NCT12345678"}, "Done", True)
        mock_scratchpad.add(1, "finish", "Done", {}, "Stop", True)

        mock_loop = AsyncMock(return_value=mock_scratchpad)

        with patch("agents.run_agent_loop", mock_loop):
            task = await dispatch(
                session,
                "dossier",
                patient_id,
                input_data={
                    "patient": sample_patient_data,
                    "match": sample_match_output["matches"][0],
                    "nct_id": sample_match_output["matches"][0]["nct_id"],
                    "patient_summary": "Summary",
                },
            )

        assert task.status == TaskStatus.blocked.value
        assert task.output_data is not None
        assert "dossier" in task.output_data

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

        mock_scratchpad = _build_matching_scratchpad()
        mock_loop = AsyncMock(return_value=mock_scratchpad)
        mock_summary = AsyncMock(return_value=ToolResult(success=True, data="S"))

        with (
            patch("agents.run_agent_loop", mock_loop),
            patch("agents.claude_text_call", mock_summary),
        ):
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
    async def test_execute_returns_matches(self, sample_patient_data):
        """MatchingAgent produces matches via direct pipeline (simple patient)."""
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

        scratchpad = _build_matching_scratchpad()
        mock_pool = scratchpad.state["trials_pool"]
        mock_analyses = scratchpad.state["analyses"]
        mock_summary = AsyncMock(return_value=ToolResult(success=True, data="Summary text"))

        with (
            patch.object(agent, "_do_search", AsyncMock(return_value=mock_pool)),
            patch.object(agent, "_do_prescreen_and_analyze", AsyncMock(return_value=mock_analyses)),
            patch("agents.claude_text_call", mock_summary),
        ):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.output_data["patient_summary"] == "Summary text"
        assert len(result.output_data["matches"]) == 1
        assert result.gate_request is None

    @pytest.mark.asyncio
    async def test_execute_propagates_exception(self, sample_patient_data):
        """MatchingAgent lets exceptions bubble up (dispatcher catches them)."""
        agent = MatchingAgent()

        async def mock_emit(event_type, data=None):
            pass

        ctx = AgentContext(
            task_id=uuid.uuid4(), patient_id=uuid.uuid4(), input_data={"patient": sample_patient_data}, emit=mock_emit
        )

        mock_search = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch.object(agent, "_do_search", mock_search),
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
                "match": sample_match_output["matches"][0],
                "nct_id": sample_match_output["matches"][0]["nct_id"],
                "patient_summary": "Summary",
            },
            emit=mock_emit,
        )

        dossier_section = {
            "nct_id": "NCT12345678",
            "brief_title": "Study of Drug X in NSCLC",
            "revised_score": 92,
            "criteria_analysis": [{"criterion": "Stage IV", "type": "inclusion", "status": "met"}],
            "patient_summary": "Good candidate.",
            "clinical_summary": "Meets all criteria.",
            "next_steps": ["Call the site"],
            "flags": ["Verify labs"],
        }

        mock_scratchpad = Scratchpad(state={"sections": {"NCT12345678": dossier_section}})
        mock_loop = AsyncMock(return_value=mock_scratchpad)

        with patch("agents.run_agent_loop", mock_loop):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.gate_request is not None
        assert result.gate_request.gate_type == "dossier_review"
        dossier = result.output_data["dossier"]
        assert dossier["nct_id"] == sample_match_output["matches"][0]["nct_id"]
        assert len(dossier["sections"]) == 1
        assert dossier["sections"][0]["nct_id"] == "NCT12345678"
        assert dossier["sections"][0]["revised_score"] == 92

    @pytest.mark.asyncio
    async def test_execute_handles_empty_sections(self, sample_patient_data, sample_match_output):
        """DossierAgent handles case where no sections were produced."""
        agent = DossierAgent()

        async def mock_emit(event_type, data=None):
            pass

        ctx = AgentContext(
            task_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            input_data={
                "patient": sample_patient_data,
                "match": sample_match_output["matches"][0],
                "nct_id": sample_match_output["matches"][0]["nct_id"],
                "patient_summary": "Summary",
            },
            emit=mock_emit,
        )

        mock_scratchpad = Scratchpad(state={"sections": {}})
        mock_loop = AsyncMock(return_value=mock_scratchpad)

        with patch("agents.run_agent_loop", mock_loop):
            result = await agent.execute(ctx)

        assert result.success is True
        assert result.output_data["dossier"]["sections"] == []


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
        req = DossierRequest(matching_task_id=str(uuid.uuid4()), nct_id="NCT12345678")
        assert req.nct_id == "NCT12345678"

    def test_dossier_request_requires_nct_id(self):
        with pytest.raises(Exception):
            DossierRequest(matching_task_id=str(uuid.uuid4()))

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


# ---------------------------------------------------------------------------
# Background dispatch tests
# ---------------------------------------------------------------------------


class TestBackgroundDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_background_returns_pending(self, sample_patient_data):
        session = FakeSession()
        patient_id = uuid.uuid4()
        task = await dispatch_background(
            session, "matching", patient_id, input_data={"patient": sample_patient_data, "max_results": 5}
        )
        assert task.status == TaskStatus.pending.value
        assert task.id is not None

    @pytest.mark.asyncio
    async def test_dispatch_background_unknown_agent(self):
        session = FakeSession()
        with pytest.raises(ValueError, match="Unknown agent type"):
            await dispatch_background(session, "nonexistent", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_dispatch_background_spawns_task(self, sample_patient_data):
        session = FakeSession()
        patient_id = uuid.uuid4()
        task = await dispatch_background(session, "matching", patient_id, input_data={"patient": sample_patient_data})
        assert task.agent_type == "matching"
        assert task.patient_id == patient_id


# ---------------------------------------------------------------------------
# Phase 2B models and endpoints
# ---------------------------------------------------------------------------

_is_postgres = "postgresql" in os.environ.get("KYRIAKI_DATABASE_URL", "")


class TestPhase2BModels:
    def test_gate_response_serialization(self):
        resp = GateResponse(
            gate_id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            gate_type="dossier_review",
            status="pending",
            created_at="2026-04-01T00:00:00",
        )
        assert resp.gate_type == "dossier_review"

    def test_event_response_serialization(self):
        resp = EventResponse(
            event_id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            event_type="progress",
            data={"step": "searching"},
            created_at="2026-04-01T00:00:00",
        )
        assert resp.event_type == "progress"

    def test_task_detail_response_with_gates(self):
        gate = GateResponse(
            gate_id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            gate_type="dossier_review",
            status="pending",
            created_at="now",
        )
        resp = TaskDetailResponse(
            task_id=str(uuid.uuid4()),
            agent_type="dossier",
            status="blocked",
            created_at="now",
            gates=[gate],
        )
        assert len(resp.gates) == 1

    def test_task_detail_response_default_gates(self):
        resp = TaskDetailResponse(
            task_id=str(uuid.uuid4()), agent_type="matching", status="completed", created_at="now"
        )
        assert resp.gates == []

    def test_activity_item(self):
        item = ActivityItem(type="task", timestamp="2026-04-01T00:00:00", data={"agent_type": "matching"})
        assert item.type == "task"


@pytest.mark.skipif(_is_postgres, reason="BaseHTTPMiddleware + asyncpg TestClient conflict")
class TestPhase2BEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from main import app

        with TestClient(app) as c:
            yield c

    def test_list_gates_endpoint(self, client):
        resp = client.get("/api/agents/gates?status=pending")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_gates_invalid_status(self, client):
        resp = client.get("/api/agents/gates?status=maybe")
        assert resp.status_code == 422

    def test_list_tasks_endpoint(self, client):
        resp = client.get("/api/agents/tasks")
        assert resp.status_code == 200

    def test_task_events_not_found(self, client):
        resp = client.get(f"/api/agents/tasks/{uuid.uuid4()}/events")
        assert resp.status_code == 404

    def test_patient_activity_endpoint(self, client):
        resp = client.get(f"/api/patients/{uuid.uuid4()}/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data


# ---------------------------------------------------------------------------
# Token tracking tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stale task recovery tests
# ---------------------------------------------------------------------------

_is_postgres = "postgresql" in os.environ.get("KYRIAKI_DATABASE_URL", "")


@pytest.mark.skipif(_is_postgres, reason="Uses SQLite test DB")
class TestStaleTaskRecovery:
    @pytest_asyncio.fixture
    async def db_session(self):
        from database import async_session, engine
        from db_models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_session() as session:
            yield session

    @pytest.mark.asyncio
    async def test_recover_stale_running_tasks(self, db_session):
        """Running tasks are marked failed on recovery."""
        patient_id = uuid.uuid4()
        task = AgentTaskDB(
            agent_type="matching",
            status=TaskStatus.running.value,
            patient_id=patient_id,
            input_data={},
        )
        db_session.add(task)
        await db_session.flush()

        count = await recover_stale_tasks(db_session)
        assert count >= 1

        await db_session.refresh(task)
        assert task.status == TaskStatus.failed.value
        assert "orphaned" in task.error

    @pytest.mark.asyncio
    async def test_recover_stale_pending_tasks(self, db_session):
        """Pending tasks are also recovered."""
        patient_id = uuid.uuid4()
        task = AgentTaskDB(
            agent_type="matching",
            status=TaskStatus.pending.value,
            patient_id=patient_id,
            input_data={},
        )
        db_session.add(task)
        await db_session.flush()

        count = await recover_stale_tasks(db_session)
        assert count >= 1

        await db_session.refresh(task)
        assert task.status == TaskStatus.failed.value

    @pytest.mark.asyncio
    async def test_completed_tasks_not_affected(self, db_session):
        """Completed tasks are not touched by recovery."""
        patient_id = uuid.uuid4()
        task = AgentTaskDB(
            agent_type="matching",
            status=TaskStatus.completed.value,
            patient_id=patient_id,
            input_data={},
            output_data={"matches": []},
        )
        db_session.add(task)
        await db_session.flush()

        await recover_stale_tasks(db_session)

        await db_session.refresh(task)
        assert task.status == TaskStatus.completed.value
        assert task.error is None


# ---------------------------------------------------------------------------
# Tool use planning tests
# ---------------------------------------------------------------------------


class TestToolUse:
    def test_build_tool_use_tools_includes_finish(self):
        """Tool list always includes the finish tool."""
        tools = _build_tool_use_tools([MATCHING_TOOLS[0]])
        names = [t["name"] for t in tools]
        assert "finish" in names
        assert "search" in names

    def test_build_tool_use_tools_all_matching(self):
        tools = _build_tool_use_tools(MATCHING_TOOLS)
        names = [t["name"] for t in tools]
        assert set(names) == {"search", "analyze_batch", "evaluate", "finish"}

    def test_tool_definition_schema(self):
        """Tool definitions produce valid Claude API tool format."""
        tools = _build_tool_use_tools(MATCHING_TOOLS)
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_finish_tool_has_reason(self):
        tools = _build_tool_use_tools([])
        finish = next(t for t in tools if t["name"] == "finish")
        assert "reason" in finish["input_schema"]["properties"]

    def test_matching_search_tool_requires_query_cond(self):
        search = next(t for t in MATCHING_TOOLS if t.name == "search")
        assert "query_cond" in search.parameters["required"]


class TestTokenTracking:
    def test_token_usage_total(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_token_usage_defaults(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0

    def test_scratchpad_total_token_usage(self):
        scratchpad = Scratchpad()
        scratchpad.add(0, "search", "reason", {}, "ok", True, TokenUsage(100, 50))
        scratchpad.add(1, "analyze", "reason", {}, "ok", True, TokenUsage(200, 80))
        scratchpad.add(2, "finish", "done", {}, "ok", True)  # no tokens

        total = scratchpad.total_token_usage
        assert total.input_tokens == 300
        assert total.output_tokens == 130
        assert total.total_tokens == 430

    def test_scratchpad_empty_token_usage(self):
        scratchpad = Scratchpad()
        total = scratchpad.total_token_usage
        assert total.total_tokens == 0

    @pytest.mark.asyncio
    async def test_matching_agent_returns_results(self, sample_patient_data):
        """MatchingAgent output_data includes matches and screening count."""
        agent = MatchingAgent()

        async def mock_emit(event_type, data=None):
            pass

        ctx = AgentContext(
            task_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            input_data={"patient": sample_patient_data, "max_results": 5},
            emit=mock_emit,
        )

        scratchpad = _build_matching_scratchpad()
        mock_pool = scratchpad.state["trials_pool"]
        mock_analyses = scratchpad.state["analyses"]
        mock_summary = AsyncMock(return_value=ToolResult(success=True, data="Summary"))

        with (
            patch.object(agent, "_do_search", AsyncMock(return_value=mock_pool)),
            patch.object(agent, "_do_prescreen_and_analyze", AsyncMock(return_value=mock_analyses)),
            patch("agents.claude_text_call", mock_summary),
        ):
            result = await agent.execute(ctx)

        assert result.success
        assert result.output_data["total_trials_screened"] == 1
        assert len(result.output_data["matches"]) == 1


# ---------------------------------------------------------------------------
# Workflow state management tests (require real DB)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_is_postgres, reason="Uses SQLite test DB")
class TestDuplicateDispatchGuard:
    @pytest_asyncio.fixture
    async def db_session(self):
        from database import async_session, engine
        from db_models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_session() as session:
            yield session

    @pytest.mark.asyncio
    async def test_has_active_task_returns_none_when_clean(self, db_session):
        result = await has_active_task(db_session, "matching", uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_has_active_task_finds_running(self, db_session):
        pid = uuid.uuid4()
        task = AgentTaskDB(agent_type="matching", status="running", patient_id=pid, input_data={})
        db_session.add(task)
        await db_session.flush()

        result = await has_active_task(db_session, "matching", pid)
        assert result is not None
        assert result.id == task.id

    @pytest.mark.asyncio
    async def test_has_active_task_ignores_completed(self, db_session):
        pid = uuid.uuid4()
        task = AgentTaskDB(agent_type="matching", status="completed", patient_id=pid, input_data={})
        db_session.add(task)
        await db_session.flush()

        result = await has_active_task(db_session, "matching", pid)
        assert result is None

    @pytest.mark.asyncio
    async def test_has_active_task_scoped_to_agent_type(self, db_session):
        pid = uuid.uuid4()
        task = AgentTaskDB(agent_type="dossier", status="running", patient_id=pid, input_data={})
        db_session.add(task)
        await db_session.flush()

        # Different agent type should not be found
        result = await has_active_task(db_session, "matching", pid)
        assert result is None


@pytest.mark.skipif(_is_postgres, reason="Uses SQLite test DB")
class TestTrialWatches:
    @pytest_asyncio.fixture
    async def db_session(self):
        from database import async_session, engine
        from db_models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_session() as session:
            yield session

    @pytest.mark.asyncio
    async def test_upsert_creates_watches(self, db_session):
        pid = uuid.uuid4()
        watches = [
            {"nct_id": "NCT001", "last_status": "RECRUITING"},
            {"nct_id": "NCT002", "last_status": "RECRUITING"},
        ]
        count = await upsert_trial_watches(db_session, pid, watches)
        assert count == 2

        result = await get_trial_watches(db_session, pid)
        assert len(result) == 2
        nct_ids = {w["nct_id"] for w in result}
        assert nct_ids == {"NCT001", "NCT002"}

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, db_session):
        pid = uuid.uuid4()
        await upsert_trial_watches(db_session, pid, [{"nct_id": "NCT001", "last_status": "RECRUITING"}])

        # Update status
        await upsert_trial_watches(db_session, pid, [{"nct_id": "NCT001", "last_status": "COMPLETED"}])

        result = await get_trial_watches(db_session, pid)
        assert len(result) == 1
        assert result[0]["last_status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_get_watches_empty(self, db_session):
        result = await get_trial_watches(db_session, uuid.uuid4())
        assert result == []


@pytest.mark.skipif(_is_postgres, reason="Uses SQLite test DB")
class TestPipelineState:
    @pytest_asyncio.fixture
    async def db_session(self):
        from database import async_session, engine
        from db_models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_session() as session:
            yield session

    @pytest.mark.asyncio
    async def test_get_or_create_pipeline(self, db_session):
        pid = uuid.uuid4()
        pipeline = await get_or_create_pipeline(db_session, pid)
        assert pipeline.current_stage == "matching"
        assert pipeline.patient_id == pid

        # Second call returns same record
        pipeline2 = await get_or_create_pipeline(db_session, pid)
        assert pipeline2.id == pipeline.id

    @pytest.mark.asyncio
    async def test_retry_task_creates_new(self, db_session):
        pid = uuid.uuid4()
        original = AgentTaskDB(
            agent_type="matching",
            status="failed",
            patient_id=pid,
            input_data={"patient": {"cancer_type": "NSCLC"}},
            error="API down",
        )
        db_session.add(original)
        await db_session.flush()

        new_task = await retry_task(db_session, original.id)
        assert new_task is not None
        assert new_task.id != original.id
        assert new_task.agent_type == "matching"
        assert new_task.status == "pending"
        assert new_task.input_data == original.input_data

    @pytest.mark.asyncio
    async def test_retry_non_failed_returns_none(self, db_session):
        pid = uuid.uuid4()
        task = AgentTaskDB(agent_type="matching", status="completed", patient_id=pid, input_data={}, output_data={})
        db_session.add(task)
        await db_session.flush()

        result = await retry_task(db_session, task.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_retry_nonexistent_returns_none(self, db_session):
        result = await retry_task(db_session, uuid.uuid4())
        assert result is None


@pytest.mark.skipif(_is_postgres, reason="Uses SQLite test DB")
class TestPipelineEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from main import app

        with TestClient(app) as c:
            yield c

    def test_pipeline_status_new_patient(self, client):
        resp = client.get(f"/api/patients/{uuid.uuid4()}/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_stage"] == "matching"
        assert data["current_task_id"] is None

    def test_retry_not_found(self, client):
        resp = client.post(f"/api/agents/tasks/{uuid.uuid4()}/retry")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PDF generation tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_is_postgres, reason="Uses SQLite test DB")
class TestProfileVersioning:
    @pytest_asyncio.fixture
    async def db_session(self):
        from database import async_session, engine
        from db_models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with async_session() as session:
            yield session

    @pytest.mark.asyncio
    async def test_update_creates_version(self, db_session):
        from db_models import PatientProfileDB
        from db_service import get_patient_versions, update_patient_profile

        patient = PatientProfileDB(
            cancer_type="NSCLC",
            cancer_stage="Stage IV",
            age=62,
            sex="male",
            location_zip="10001",
            biomarkers=["EGFR+"],
            prior_treatments=[],
            lines_of_therapy=0,
        )
        db_session.add(patient)
        await db_session.flush()

        updated = await update_patient_profile(
            db_session,
            patient.id,
            {"cancer_stage": "Stage IIIB", "biomarkers": ["EGFR+", "PD-L1 80%"]},
        )

        assert updated is not None
        assert updated.version == 2
        assert updated.cancer_stage == "Stage IIIB"

        versions = await get_patient_versions(db_session, patient.id)
        assert len(versions) == 1
        assert versions[0].version == 1
        assert versions[0].profile_snapshot["cancer_stage"] == "Stage IV"
        assert "Stage" in versions[0].change_summary

    @pytest.mark.asyncio
    async def test_multiple_updates(self, db_session):
        from db_models import PatientProfileDB
        from db_service import get_patient_versions, update_patient_profile

        patient = PatientProfileDB(
            cancer_type="TNBC",
            cancer_stage="Stage IV",
            age=45,
            sex="female",
            location_zip="90210",
            biomarkers=[],
            prior_treatments=[],
        )
        db_session.add(patient)
        await db_session.flush()

        await update_patient_profile(db_session, patient.id, {"lines_of_therapy": 1})
        await update_patient_profile(db_session, patient.id, {"lines_of_therapy": 2, "ecog_score": 1})

        assert patient.version == 3
        versions = await get_patient_versions(db_session, patient.id)
        assert len(versions) == 2

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self, db_session):
        from db_service import update_patient_profile

        result = await update_patient_profile(db_session, uuid.uuid4(), {"age": 50})
        assert result is None


class TestPDFRenderer:
    def test_render_basic_dossier(self):
        from tools.pdf_renderer import render_dossier_pdf

        dossier = {
            "patient_summary": "A 62-year-old male with Stage IV NSCLC.",
            "generated_at": "2026-04-02T00:00:00Z",
            "sections": [
                {
                    "nct_id": "NCT12345678",
                    "brief_title": "Study of Drug X in NSCLC",
                    "revised_score": 85,
                    "score_justification": "Strong match based on cancer type and biomarkers.",
                    "clinical_summary": "Patient meets all major inclusion criteria.",
                    "patient_summary": "This trial is a strong fit for you.",
                    "criteria_analysis": [
                        {
                            "criterion": "Stage IV NSCLC",
                            "type": "inclusion",
                            "status": "met",
                            "evidence": "Patient has Stage IV NSCLC",
                        },
                        {"criterion": "EGFR mutation", "type": "inclusion", "status": "met", "evidence": "EGFR+"},
                        {
                            "criterion": "Active brain mets",
                            "type": "exclusion",
                            "status": "not_triggered",
                            "evidence": "None reported",
                        },
                    ],
                    "next_steps": ["Contact trial site", "Get recent labs"],
                    "flags": ["Verify no brain metastases"],
                }
            ],
        }

        patient_data = {
            "cancer_type": "Non-Small Cell Lung Cancer",
            "cancer_stage": "Stage IV",
            "age": 62,
            "sex": "male",
            "biomarkers": ["EGFR+", "PD-L1 80%"],
            "prior_treatments": ["Carboplatin/Pemetrexed"],
            "lines_of_therapy": 1,
            "ecog_score": 1,
        }

        result = render_dossier_pdf(dossier, patient_data)
        assert result.success
        assert isinstance(result.data, bytes)
        assert len(result.data) > 1000  # A real PDF should be > 1KB
        assert result.data[:5] == b"%PDF-"  # Valid PDF header

    def test_render_empty_dossier(self):
        from tools.pdf_renderer import render_dossier_pdf

        dossier = {"patient_summary": "", "sections": []}
        result = render_dossier_pdf(dossier)
        assert result.success
        assert result.data[:5] == b"%PDF-"

    def test_render_multiple_sections(self):
        from tools.pdf_renderer import render_dossier_pdf

        dossier = {
            "patient_summary": "Summary text.",
            "sections": [
                {"nct_id": "NCT001", "brief_title": "Trial A", "revised_score": 90, "criteria_analysis": []},
                {"nct_id": "NCT002", "brief_title": "Trial B", "revised_score": 45, "criteria_analysis": []},
                {"nct_id": "NCT003", "brief_title": "Trial C", "revised_score": 15, "criteria_analysis": []},
            ],
        }
        result = render_dossier_pdf(dossier)
        assert result.success

    def test_render_with_analysis_error_section(self):
        from tools.pdf_renderer import render_dossier_pdf

        dossier = {
            "patient_summary": "Summary.",
            "sections": [
                {"nct_id": "NCT001", "brief_title": "Trial A", "analysis_error": "Failed to parse"},
            ],
        }
        result = render_dossier_pdf(dossier)
        assert result.success
