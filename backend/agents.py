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
from prompts import (
    DOSSIER_ANALYSIS_PROMPT,
    ENROLLMENT_PACKET_PROMPT,
    OUTREACH_MESSAGE_PROMPT,
    PATIENT_PREP_PROMPT,
)
from trials_client import get_trial

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

        # Parallel analysis with rate-limit-safe concurrency
        semaphore = asyncio.Semaphore(settings.dossier_max_concurrent)

        async def _analyze_one(i: int, match: dict) -> dict:
            async with semaphore:
                await ctx.emit(
                    "progress",
                    {
                        "step": "analyzing_trial",
                        "trial_index": i + 1,
                        "total": len(top_matches),
                        "nct_id": match["nct_id"],
                    },
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


# --- Phase 2C agents ---


async def _sonnet_json(prompt: str, max_tokens: int = 1500) -> dict | None:
    """Helper: call Sonnet, parse JSON response."""
    settings = get_settings()
    response = await _paced_claude_call(
        _get_client(),
        model=settings.claude_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json_response(response.content[0].text)


@register_agent
class EnrollmentAgent(BaseAgent):
    agent_type: ClassVar[str] = "enrollment"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        patient_data = ctx.input_data["patient"]
        dossier = ctx.input_data["dossier"]
        trial_nct_id = ctx.input_data["trial_nct_id"]

        # Find the dossier section for this trial
        section = next((s for s in dossier.get("sections", []) if s.get("nct_id") == trial_nct_id), None)
        if not section:
            return AgentResult(success=False, error=f"No dossier section found for {trial_nct_id}")

        # Fetch fresh trial data for site info
        trial = await get_trial(trial_nct_id)
        nearest_site = {}
        if trial and trial.get("locations"):
            nearest_site = trial["locations"][0] if trial["locations"] else {}

        await ctx.emit("progress", {"step": "generating_packet"})
        packet = await _sonnet_json(
            ENROLLMENT_PACKET_PROMPT.format(
                patient_json=json.dumps(patient_data, indent=2),
                nct_id=trial_nct_id,
                brief_title=section.get("brief_title", ""),
                revised_score=section.get("revised_score", "?"),
                clinical_summary=section.get("clinical_summary", ""),
                criteria_json=json.dumps(section.get("criteria_analysis", [])[:10], indent=2),
            )
        )

        await ctx.emit("progress", {"step": "generating_prep_guide"})
        prep = await _sonnet_json(
            PATIENT_PREP_PROMPT.format(
                cancer_type=patient_data.get("cancer_type", ""),
                cancer_stage=patient_data.get("cancer_stage", ""),
                age=patient_data.get("age", ""),
                brief_title=section.get("brief_title", ""),
                site_name=nearest_site.get("facility", "Trial site"),
                site_city=nearest_site.get("city", ""),
                site_state=nearest_site.get("state", ""),
                screening_checklist=json.dumps((packet or {}).get("screening_checklist", []), indent=2),
            )
        )

        await ctx.emit("progress", {"step": "generating_outreach_draft"})
        outreach = await _sonnet_json(
            OUTREACH_MESSAGE_PROMPT.format(
                nct_id=trial_nct_id,
                brief_title=section.get("brief_title", ""),
                site_name=nearest_site.get("facility", "Trial site"),
                site_city=nearest_site.get("city", ""),
                site_state=nearest_site.get("state", ""),
                contact_name=nearest_site.get("contacts", [{}])[0].get("name", "Research Coordinator")
                if nearest_site.get("contacts")
                else "Research Coordinator",
                patient_summary=section.get("clinical_summary", dossier.get("patient_summary", "")),
                match_score=section.get("revised_score", "?"),
                match_rationale=section.get("score_justification", ""),
            )
        )

        output = {
            "patient_packet": packet or {"error": "Failed to generate"},
            "patient_prep_guide": prep or {"error": "Failed to generate"},
            "outreach_draft": outreach or {"error": "Failed to generate"},
            "trial_nct_id": trial_nct_id,
            "trial_title": section.get("brief_title", ""),
        }

        return AgentResult(
            success=True,
            output_data=output,
            gate_request=GateRequest(gate_type="enrollment_review", requested_data=output),
        )


@register_agent
class MonitorAgent(BaseAgent):
    agent_type: ClassVar[str] = "monitor"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        watches = ctx.input_data.get("watches", [])
        await ctx.emit("progress", {"step": "checking_trials", "count": len(watches)})

        changes: list[dict] = []
        for watch in watches:
            nct_id = watch["nct_id"]
            trial = await get_trial(nct_id)
            if trial is None:
                changes.append({"nct_id": nct_id, "change_type": "not_found", "detail": "Trial no longer available"})
                continue

            current_status = trial.get("overall_status", "")
            last_status = watch.get("last_status", "")
            if current_status and current_status != last_status:
                changes.append(
                    {
                        "nct_id": nct_id,
                        "change_type": "status_changed",
                        "old_status": last_status,
                        "new_status": current_status,
                    }
                )

            current_sites = len(trial.get("locations", []))
            last_sites = watch.get("last_site_count", 0)
            if current_sites > last_sites:
                changes.append(
                    {
                        "nct_id": nct_id,
                        "change_type": "sites_added",
                        "old_count": last_sites,
                        "new_count": current_sites,
                    }
                )

            await ctx.emit("progress", {"step": "checked_trial", "nct_id": nct_id})

        return AgentResult(
            success=True,
            output_data={
                "changes": changes,
                "trials_checked": len(watches),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        )


@register_agent
class OutreachAgent(BaseAgent):
    agent_type: ClassVar[str] = "outreach"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        outreach_draft = ctx.input_data.get("outreach_draft", {})
        trial_nct_id = ctx.input_data.get("trial_nct_id", "")

        await ctx.emit("progress", {"step": "extracting_contacts"})
        trial = await get_trial(trial_nct_id)

        contacts = []
        if trial:
            for loc in trial.get("locations", [])[:5]:
                for contact in loc.get("contacts", []):
                    contacts.append(
                        {
                            "name": contact.get("name", ""),
                            "role": contact.get("role", ""),
                            "phone": contact.get("phone", ""),
                            "email": contact.get("email", ""),
                            "facility": loc.get("facility", ""),
                            "city": loc.get("city", ""),
                            "state": loc.get("state", ""),
                        }
                    )

        await ctx.emit("progress", {"step": "finalizing_message"})
        # Use the pre-drafted message, personalize with contact info if available
        final_message = outreach_draft.get("message_body", "")
        if contacts and contacts[0].get("name"):
            # Quick personalization via Sonnet
            personalized = await _sonnet_json(
                f"Personalize this outreach message for {contacts[0]['name']} at {contacts[0].get('facility', 'the trial site')}. "
                f"Keep the message professional and under 4 paragraphs.\n\nOriginal message:\n{final_message}\n\n"
                'Respond with ONLY a JSON object: {{"message_body": "<personalized message>"}}',
                max_tokens=800,
            )
            if personalized:
                final_message = personalized.get("message_body", final_message)

        output = {
            "contacts": contacts,
            "final_message": final_message,
            "subject_line": outreach_draft.get("subject_line", f"Pre-screened patient candidate for {trial_nct_id}"),
            "outreach_status": "ready_for_review",
        }

        return AgentResult(
            success=True,
            output_data=output,
            gate_request=GateRequest(gate_type="outreach_review", requested_data=output),
        )
