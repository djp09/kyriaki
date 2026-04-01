"""Agent definitions: BaseAgent interface, MatchingAgent, DossierAgent."""

from __future__ import annotations

import asyncio
import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, ClassVar

from config import get_settings
from dispatcher import register_agent
from logging_config import get_logger
from matching_engine import _get_client, _paced_claude_call, _parse_json_response, match_trials
from models import PatientProfile
from prompts import DOSSIER_ANALYSIS_PROMPT

logger = get_logger("kyriaki.agents")


# --- Framework types ---


@dataclass
class AgentContext:
    """Everything an agent needs to do its work."""

    task_id: uuid.UUID
    patient_id: uuid.UUID
    input_data: dict[str, Any]
    emit: Callable[[str, dict[str, Any] | None], Coroutine[Any, Any, None]]


@dataclass
class GateRequest:
    """Agent wants to pause for human approval."""

    gate_type: str
    requested_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """What an agent returns when done."""

    success: bool
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    gate_request: GateRequest | None = None


class BaseAgent(ABC):
    agent_type: ClassVar[str]

    @abstractmethod
    async def execute(self, ctx: AgentContext) -> AgentResult: ...


# --- Concrete agents ---


@register_agent
class MatchingAgent(BaseAgent):
    agent_type: ClassVar[str] = "matching"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        patient = PatientProfile(**ctx.input_data["patient"])
        max_results = ctx.input_data.get("max_results", 10)

        await ctx.emit("progress", {"step": "searching_trials"})
        result = await match_trials(patient, max_results=max_results)

        matches_data = [m.model_dump() for m in result["matches"]]

        return AgentResult(
            success=True,
            output_data={
                "patient_summary": result["patient_summary"],
                "matches": matches_data,
                "total_trials_screened": result["total_trials_screened"],
            },
        )


@register_agent
class DossierAgent(BaseAgent):
    agent_type: ClassVar[str] = "dossier"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        patient_data = ctx.input_data["patient"]
        matches = ctx.input_data["matches"]
        settings = get_settings()
        top_n = ctx.input_data.get("top_n", settings.dossier_top_n)

        top_matches = sorted(matches, key=lambda m: m.get("match_score", 0), reverse=True)[:top_n]
        await ctx.emit("progress", {"step": "deep_analysis", "trial_count": len(top_matches)})

        # Parallel analysis — all trials analyzed concurrently (like MatchingAgent)
        async def _analyze_one(i: int, match: dict) -> dict:
            await ctx.emit(
                "progress",
                {"step": "analyzing_trial", "trial_index": i + 1, "total": len(top_matches), "nct_id": match["nct_id"]},
            )
            return await self._analyze_deep(patient_data, match)

        sections = await asyncio.gather(*[_analyze_one(i, m) for i, m in enumerate(top_matches)])

        dossier = {
            "patient_summary": ctx.input_data.get("patient_summary", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sections": list(sections),
        }

        return AgentResult(
            success=True,
            output_data={"dossier": dossier},
            gate_request=GateRequest(gate_type="dossier_review", requested_data={"dossier": dossier}),
        )

    async def _analyze_deep(self, patient_data: dict, match: dict) -> dict:
        """Use Opus for deep criterion-by-criterion eligibility analysis."""
        settings = get_settings()

        prompt = DOSSIER_ANALYSIS_PROMPT.format(
            patient_json=json.dumps(patient_data, indent=2),
            nct_id=match["nct_id"],
            brief_title=match["brief_title"],
            eligibility_criteria=match.get("eligibility_criteria", "Not available"),
            initial_score=match.get("match_score", 0),
            initial_explanation=match.get("match_explanation", ""),
        )

        response = await _paced_claude_call(
            _get_client(),
            model=settings.dossier_model,
            max_tokens=settings.dossier_max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        result = _parse_json_response(response.content[0].text)
        if result is None:
            logger.warning("dossier.parse_failed", nct_id=match["nct_id"])
            return {
                "nct_id": match["nct_id"],
                "brief_title": match["brief_title"],
                "analysis_error": "Failed to parse deep analysis response",
            }

        result["nct_id"] = match["nct_id"]
        result["brief_title"] = match["brief_title"]
        return result
