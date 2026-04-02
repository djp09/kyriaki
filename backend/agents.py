"""Agent definitions — thin orchestrators in the WAT framework.

Each agent reads its workflow SOP (workflows/*.md), calls tools in sequence,
handles concurrency, and returns results. The actual work happens in tools/.

Workflow SOPs:
  - workflows/matching.md
  - workflows/dossier.md
  - workflows/enrollment.md
  - workflows/outreach.md
  - workflows/monitor.md
"""

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
from models import (
    DossierInput,
    EnrollmentInput,
    MatchingInput,
    MonitorInput,
    OutreachInput,
    PatientProfile,
)
from tools.claude_api import (
    claude_json_call,
    claude_text_call,
    evaluate_score,
    extract_minimal_result,
    get_claude_client,
    paced_claude_call,
    parse_json_response,
)
from tools.data_formatter import (
    build_dossier_section,
    build_scored_match,
    build_unscored_match,
    extract_contacts,
    format_patient_for_prompt,
)
from tools.prompt_renderer import render_prompt
from tools.trial_search import fetch_trial_tool, search_trials_tool

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
# Each agent follows its workflow SOP in workflows/*.md


@register_agent
class MatchingAgent(BaseAgent):
    """Workflow: workflows/matching.md

    Search → Analyze (parallel) → Filter by distance → Rank → Return top N.
    """

    agent_type: ClassVar[str] = "matching"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = MatchingInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        patient = PatientProfile(**inputs.patient)
        max_results = inputs.max_results
        settings = get_settings()

        # Step 1: Search trials
        await ctx.emit("progress", {"step": "searching_trials"})
        candidate_count = min(max(max_results * 2, 6), settings.default_page_size)
        search_result = await search_trials_tool(
            cancer_type=patient.cancer_type,
            age=patient.age,
            sex=patient.sex,
            page_size=candidate_count,
        )
        if not search_result.success:
            return AgentResult(success=False, error=f"Trial search failed: {search_result.error}")
        trials = search_result.data
        total = len(trials)

        # Steps 2+3: Patient summary + eligibility analysis (concurrent)
        summary_task = asyncio.create_task(self._generate_summary(patient))
        analyses = await self._analyze_all(patient, trials, ctx, settings)

        # Step 3.5: Evaluator-optimizer loop on borderline scores
        if settings.evaluation_enabled:
            analyses = await self._evaluate_borderline(patient, analyses, ctx, settings)

        # Step 4+5: Build matches, filter by distance, rank, trim
        matches = self._build_matches(patient, trials, analyses)
        matches.sort(key=lambda m: m.match_score, reverse=True)
        matches = matches[:max_results]

        patient_summary = await summary_task
        matches_data = [m.model_dump() for m in matches]

        return AgentResult(
            success=True,
            output_data={
                "patient_summary": patient_summary,
                "matches": matches_data,
                "total_trials_screened": total,
            },
        )

    async def _generate_summary(self, patient: PatientProfile) -> str:
        """Step 2: Render prompt → call Claude for patient summary."""
        patient_vars = format_patient_for_prompt(patient)
        prompt_result = render_prompt(prompt_name="patient_summary", **patient_vars)
        if not prompt_result.success:
            return self._fallback_summary(patient)

        result = await claude_text_call(prompt_result.data)
        if not result.success:
            return self._fallback_summary(patient)
        return result.data

    def _fallback_summary(self, patient: PatientProfile) -> str:
        treatments_str = ", ".join(patient.prior_treatments) if patient.prior_treatments else None
        biomarkers_str = ", ".join(patient.biomarkers) if patient.biomarkers else None

        summary = f"You are a {patient.age}-year-old navigating {patient.cancer_stage} {patient.cancer_type}."
        if treatments_str:
            summary += (
                f" You have been through {patient.lines_of_therapy} line(s) of treatment including {treatments_str}."
            )
        if biomarkers_str:
            summary += f" Your biomarker profile includes {biomarkers_str}."
        summary += " We are searching for clinical trials that may be a good fit for your specific situation."
        return summary

    async def _analyze_all(
        self, patient: PatientProfile, trials: list[dict], ctx: AgentContext, settings
    ) -> list[tuple[dict, dict | None]]:
        """Step 3: Parallel eligibility analysis with semaphore."""
        semaphore = asyncio.Semaphore(settings.max_concurrent_analyses)

        async def analyze_one(trial: dict, index: int) -> tuple[dict, dict | None]:
            async with semaphore:
                return trial, await self._analyze_trial(patient, trial, index, len(trials), settings)

        results = await asyncio.gather(*[analyze_one(t, i + 1) for i, t in enumerate(trials)])
        return list(results)

    async def _analyze_trial(
        self, patient: PatientProfile, trial: dict, trial_index: int, total: int, settings
    ) -> dict | None:
        """Render prompt → call Claude → parse JSON for a single trial."""
        nct_id = trial["nct_id"]
        logger.info("trial.analyze_start", nct_id=nct_id, title=trial["brief_title"][:60])

        eligibility_text = trial["eligibility_criteria"]
        if len(eligibility_text) > 6000:
            eligibility_text = (
                eligibility_text[:6000] + "\n\n[Eligibility text truncated — focus on the criteria above]"
            )

        patient_vars = format_patient_for_prompt(patient)
        prompt_result = render_prompt(
            prompt_name="eligibility_analysis",
            **patient_vars,
            nct_id=nct_id,
            brief_title=trial["brief_title"],
            phase=trial["phase"],
            brief_summary=trial["brief_summary"],
            eligibility_criteria=eligibility_text,
        )
        if not prompt_result.success:
            logger.error("trial.prompt_render_failed", nct_id=nct_id, error=prompt_result.error)
            return None

        for attempt in range(settings.max_retries + 1):
            try:
                response = await paced_claude_call(
                    get_claude_client(),
                    model=settings.claude_model,
                    max_tokens=1500,
                    messages=[{"role": "user", "content": prompt_result.data}],
                )
                text = response.content[0].text.strip()
                result = parse_json_response(text)

                if result is not None:
                    if "match_score" not in result:
                        result["match_score"] = 0
                    logger.info("trial.analyze_complete", nct_id=nct_id, score=result["match_score"])
                    return result

                if attempt < settings.max_retries:
                    logger.warning("trial.parse_failed", nct_id=nct_id, attempt=attempt + 1)
                    continue

                logger.error("trial.parse_exhausted", nct_id=nct_id, attempts=settings.max_retries + 1)
                return extract_minimal_result(text, nct_id)

            except Exception as e:
                if attempt < settings.max_retries:
                    logger.warning("trial.analyze_error", nct_id=nct_id, error=str(e), attempt=attempt + 1)
                    continue
                logger.error("trial.analyze_failed", nct_id=nct_id, error=str(e))
                return None

        return None

    async def _evaluate_borderline(
        self, patient: PatientProfile, analyses: list[tuple[dict, dict | None]], ctx: AgentContext, settings
    ) -> list[tuple[dict, dict | None]]:
        """Step 3.5: Re-evaluate borderline scores (evaluator-optimizer pattern).

        Scores between evaluation_score_min and evaluation_score_max get a second
        evaluation pass to catch scoring errors, logical inconsistencies, and
        missed disqualifiers.
        """
        patient_vars = format_patient_for_prompt(patient)
        borderline = []
        for i, (trial, analysis) in enumerate(analyses):
            if analysis is None:
                continue
            score = analysis.get("match_score", 0)
            if settings.evaluation_score_min <= score <= settings.evaluation_score_max:
                borderline.append((i, trial, analysis))

        if not borderline:
            return analyses

        await ctx.emit("progress", {"step": "evaluating_borderline", "count": len(borderline)})
        logger.info("eval.borderline_start", count=len(borderline))

        semaphore = asyncio.Semaphore(settings.max_concurrent_analyses)

        async def eval_one(idx: int, trial: dict, analysis: dict) -> tuple[int, dict]:
            async with semaphore:
                eligibility_text = trial["eligibility_criteria"]
                if len(eligibility_text) > 6000:
                    eligibility_text = eligibility_text[:6000]

                # Build criteria JSON from the initial evaluations
                criteria = []
                for ev in analysis.get("inclusion_evaluations", []):
                    criteria.append({"type": "inclusion", **ev})
                for ev in analysis.get("exclusion_evaluations", []):
                    criteria.append({"type": "exclusion", **ev})

                result = await evaluate_score(
                    patient_vars=patient_vars,
                    nct_id=trial["nct_id"],
                    brief_title=trial["brief_title"],
                    eligibility_criteria=eligibility_text,
                    initial_score=analysis.get("match_score", 0),
                    initial_explanation=analysis.get("match_explanation", ""),
                    criteria_json=json.dumps(criteria, indent=2),
                )
                return idx, result

        eval_results = await asyncio.gather(*[eval_one(i, t, a) for i, t, a in borderline])

        # Apply adjustments
        updated = list(analyses)
        for idx, result in eval_results:
            if not result.success:
                logger.warning("eval.failed", nct_id=analyses[idx][0]["nct_id"], error=result.error)
                continue

            data = result.data
            trial, analysis = updated[idx]
            nct_id = trial["nct_id"]

            if not data["confirmed"] and data["adjusted_score"] is not None:
                old_score = analysis["match_score"]
                analysis["match_score"] = data["adjusted_score"]
                analysis.setdefault("flags_for_oncologist", []).append(
                    f"Score adjusted from {old_score} to {data['adjusted_score']}: {data['adjustment_reason']}"
                )
                logger.info(
                    "eval.adjusted",
                    nct_id=nct_id,
                    old_score=old_score,
                    new_score=data["adjusted_score"],
                    reason=data["adjustment_reason"],
                )
            else:
                logger.info("eval.confirmed", nct_id=nct_id, score=analysis["match_score"])

        return updated

    def _build_matches(self, patient, trials, analyses):
        """Step 4: Build TrialMatch objects, handling all-failed fallback."""
        from models import TrialMatch

        all_failed = all(analysis is None for _, analysis in analyses)
        matches: list[TrialMatch] = []

        if all_failed and trials:
            logger.warning("match.all_analyses_failed", fallback="unscored")
            for trial, _ in analyses:
                match = build_unscored_match(trial, patient)
                if match.distance_miles is None or match.distance_miles <= patient.willing_to_travel_miles:
                    matches.append(match)
        else:
            for trial, analysis in analyses:
                if analysis is None:
                    continue
                match = build_scored_match(trial, analysis, patient)
                if match is not None:
                    matches.append(match)

        return matches


@register_agent
class DossierAgent(BaseAgent):
    """Workflow: workflows/dossier.md

    Select top N → Deep Opus analysis (parallel) → Assemble dossier → Human gate.
    """

    agent_type: ClassVar[str] = "dossier"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = DossierInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        patient_data = inputs.patient
        matches = inputs.matches
        settings = get_settings()
        top_n = inputs.top_n or settings.dossier_top_n

        # Step 1: Select top matches
        top_matches = sorted(matches, key=lambda m: m.get("match_score", 0), reverse=True)[:top_n]
        await ctx.emit("progress", {"step": "deep_analysis", "trial_count": len(top_matches)})

        # Step 2: Deep analysis (concurrent)
        semaphore = asyncio.Semaphore(settings.dossier_max_concurrent)

        async def analyze_one(i: int, match: dict) -> dict:
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
                return await self._deep_analyze(patient_data, match, settings)

        sections = await asyncio.gather(*[analyze_one(i, m) for i, m in enumerate(top_matches)])

        # Step 3: Assemble dossier
        dossier = {
            "patient_summary": ctx.input_data.get("patient_summary", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sections": list(sections),
        }

        # Step 4: Request human gate
        return AgentResult(
            success=True,
            output_data={"dossier": dossier},
            gate_request=GateRequest(gate_type="dossier_review", requested_data={"dossier": dossier}),
        )

    async def _deep_analyze(self, patient_data: dict, match: dict, settings) -> dict:
        """Render prompt → Claude Opus → build dossier section."""
        prompt_result = render_prompt(
            prompt_name="dossier_analysis",
            patient_json=json.dumps(patient_data, indent=2),
            nct_id=match["nct_id"],
            brief_title=match["brief_title"],
            eligibility_criteria=match.get("eligibility_criteria", "Not available"),
            initial_score=match.get("match_score", 0),
            initial_explanation=match.get("match_explanation", ""),
        )
        if not prompt_result.success:
            return build_dossier_section(match, None)

        result = await claude_json_call(
            prompt_result.data,
            model=settings.dossier_model,
            max_tokens=settings.dossier_max_tokens,
        )

        return build_dossier_section(match, result.data if result.success else None)


@register_agent
class EnrollmentAgent(BaseAgent):
    """Workflow: workflows/enrollment.md

    Locate section → Fetch trial → Generate packet → Prep guide → Outreach draft → Human gate.
    """

    agent_type: ClassVar[str] = "enrollment"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = EnrollmentInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        patient_data = inputs.patient
        dossier = inputs.dossier
        trial_nct_id = inputs.trial_nct_id

        # Step 1: Locate dossier section
        section = next((s for s in dossier.get("sections", []) if s.get("nct_id") == trial_nct_id), None)
        if not section:
            return AgentResult(success=False, error=f"No dossier section found for {trial_nct_id}")

        # Step 2: Fetch fresh trial data
        trial_result = await fetch_trial_tool(nct_id=trial_nct_id)
        nearest_site = {}
        if trial_result.success and trial_result.data.get("locations"):
            nearest_site = trial_result.data["locations"][0]

        # Step 3: Generate enrollment packet
        await ctx.emit("progress", {"step": "generating_packet"})
        packet_prompt = render_prompt(
            prompt_name="enrollment_packet",
            patient_json=json.dumps(patient_data, indent=2),
            nct_id=trial_nct_id,
            brief_title=section.get("brief_title", ""),
            revised_score=section.get("revised_score", "?"),
            clinical_summary=section.get("clinical_summary", ""),
            criteria_json=json.dumps(section.get("criteria_analysis", [])[:10], indent=2),
        )
        packet = None
        if packet_prompt.success:
            packet_result = await claude_json_call(packet_prompt.data)
            packet = packet_result.data if packet_result.success else None

        # Step 4: Generate patient prep guide
        await ctx.emit("progress", {"step": "generating_prep_guide"})
        prep_prompt = render_prompt(
            prompt_name="patient_prep",
            cancer_type=patient_data.get("cancer_type", ""),
            cancer_stage=patient_data.get("cancer_stage", ""),
            age=patient_data.get("age", ""),
            brief_title=section.get("brief_title", ""),
            site_name=nearest_site.get("facility", "Trial site"),
            site_city=nearest_site.get("city", ""),
            site_state=nearest_site.get("state", ""),
            screening_checklist=json.dumps((packet or {}).get("screening_checklist", []), indent=2),
        )
        prep = None
        if prep_prompt.success:
            prep_result = await claude_json_call(prep_prompt.data)
            prep = prep_result.data if prep_result.success else None

        # Step 5: Generate outreach draft
        await ctx.emit("progress", {"step": "generating_outreach_draft"})
        contact_name = "Research Coordinator"
        if nearest_site.get("contacts"):
            contact_name = nearest_site["contacts"][0].get("name", "Research Coordinator")

        outreach_prompt = render_prompt(
            prompt_name="outreach_message",
            nct_id=trial_nct_id,
            brief_title=section.get("brief_title", ""),
            site_name=nearest_site.get("facility", "Trial site"),
            site_city=nearest_site.get("city", ""),
            site_state=nearest_site.get("state", ""),
            contact_name=contact_name,
            patient_summary=section.get("clinical_summary", dossier.get("patient_summary", "")),
            match_score=section.get("revised_score", "?"),
            match_rationale=section.get("score_justification", ""),
        )
        outreach = None
        if outreach_prompt.success:
            outreach_result = await claude_json_call(outreach_prompt.data)
            outreach = outreach_result.data if outreach_result.success else None

        # Step 6: Request human gate
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
    """Workflow: workflows/monitor.md

    For each watched trial: fetch current data → compare status/sites → collect changes.
    """

    agent_type: ClassVar[str] = "monitor"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = MonitorInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        watches = inputs.watches
        await ctx.emit("progress", {"step": "checking_trials", "count": len(watches)})

        changes: list[dict] = []
        for watch in watches:
            nct_id = watch["nct_id"]

            # Tool: fetch_trial
            trial_result = await fetch_trial_tool(nct_id=nct_id)
            if not trial_result.success:
                changes.append({"nct_id": nct_id, "change_type": "not_found", "detail": "Trial no longer available"})
                continue

            trial = trial_result.data

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
    """Workflow: workflows/outreach.md

    Extract contacts → Personalize message → Human gate.
    """

    agent_type: ClassVar[str] = "outreach"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = OutreachInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        outreach_draft = inputs.outreach_draft
        trial_nct_id = inputs.trial_nct_id

        # Step 1: Extract contacts
        await ctx.emit("progress", {"step": "extracting_contacts"})
        trial_result = await fetch_trial_tool(nct_id=trial_nct_id)
        contacts = []
        if trial_result.success:
            contacts = extract_contacts(trial_result.data)

        # Step 2: Personalize message
        await ctx.emit("progress", {"step": "finalizing_message"})
        final_message = outreach_draft.get("message_body", "")
        if contacts and contacts[0].get("name"):
            personalized = await claude_json_call(
                f"Personalize this outreach message for {contacts[0]['name']} at {contacts[0].get('facility', 'the trial site')}. "
                f"Keep the message professional and under 4 paragraphs.\n\nOriginal message:\n{final_message}\n\n"
                'Respond with ONLY a JSON object: {{"message_body": "<personalized message>"}}',
                max_tokens=800,
            )
            if personalized.success:
                final_message = personalized.data.get("message_body", final_message)

        # Step 3: Request human gate
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
