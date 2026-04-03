"""Agent definitions — adaptive orchestrators using the ReAct loop.

Each agent provides:
- An orchestrator prompt (domain-specific reasoning strategy)
- Action handlers (map decisions to tool calls)
- A result builder (assembles final output from scratchpad)

The agent_loop.py engine handles the plan→act→observe cycle.

Workflow SOPs in workflows/*.md document each agent's strategy.
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

from agent_loop import AgentBudget, AgentDecision, Scratchpad, ToolDefinition, run_agent_loop
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
from prompts import (
    DOSSIER_ORCHESTRATOR_PROMPT,
    ENROLLMENT_ORCHESTRATOR_PROMPT,
    MATCHING_ORCHESTRATOR_PROMPT,
    MONITOR_ORCHESTRATOR_PROMPT,
    OUTREACH_ORCHESTRATOR_PROMPT,
)
from routing import classify_patient
from tools.biomarker_lookup import enrich_biomarkers_tool
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
from tools.drug_normalization import normalize_drug_list_tool
from tools.prompt_renderer import render_prompt
from tools.trial_search import fetch_trial_tool, search_and_merge_tool

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


# ---------------------------------------------------------------------------
# MatchingAgent — adaptive trial search and analysis
# ---------------------------------------------------------------------------


MATCHING_TOOLS = [
    ToolDefinition(
        name="search",
        description="Search ClinicalTrials.gov for recruiting trials matching criteria.",
        parameters={
            "type": "object",
            "properties": {
                "query_cond": {
                    "type": "string",
                    "description": "Condition to search (e.g., 'Non-Small Cell Lung Cancer')",
                },
                "query_intr": {"type": "string", "description": "Intervention search (e.g., 'osimertinib')"},
                "query_term": {"type": "string", "description": "General term search (e.g., 'immunotherapy EGFR')"},
                "page_size": {"type": "integer", "description": "Max results (10-50)", "default": 20},
            },
            "required": ["query_cond"],
        },
    ),
    ToolDefinition(
        name="analyze_batch",
        description="Run eligibility analysis on all unanalyzed trials in the pool.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    ToolDefinition(
        name="evaluate",
        description="Re-evaluate borderline scores (30-70) for accuracy using a second opinion.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
]

DOSSIER_TOOLS = [
    ToolDefinition(
        name="deep_analyze",
        description="Run deep criterion-by-criterion analysis on a specific trial.",
        parameters={
            "type": "object",
            "properties": {"nct_id": {"type": "string", "description": "Trial NCT ID to analyze"}},
            "required": ["nct_id"],
        },
    ),
    ToolDefinition(
        name="investigate_criterion",
        description="Fetch fresh trial data to resolve an ambiguous criterion.",
        parameters={
            "type": "object",
            "properties": {
                "nct_id": {"type": "string", "description": "Trial NCT ID"},
                "question": {"type": "string", "description": "What to investigate"},
            },
            "required": ["nct_id", "question"],
        },
    ),
]

ENROLLMENT_TOOLS = [
    ToolDefinition(
        name="fetch_site_info",
        description="Fetch fresh trial data for site/contact details.",
        parameters={
            "type": "object",
            "properties": {"nct_id": {"type": "string", "description": "Trial NCT ID"}},
            "required": ["nct_id"],
        },
    ),
    ToolDefinition(
        name="generate_packet",
        description="Generate the screening checklist and enrollment packet.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    ToolDefinition(
        name="generate_prep_guide",
        description="Generate patient preparation guide for the screening visit.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    ToolDefinition(
        name="generate_outreach",
        description="Draft site coordinator outreach message.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
]

OUTREACH_TOOLS = [
    ToolDefinition(
        name="fetch_contacts",
        description="Fetch trial data to extract site coordinator contacts.",
        parameters={
            "type": "object",
            "properties": {"nct_id": {"type": "string", "description": "Trial NCT ID"}},
            "required": ["nct_id"],
        },
    ),
    ToolDefinition(
        name="personalize",
        description="Personalize the outreach message for a specific contact.",
        parameters={
            "type": "object",
            "properties": {
                "contact_name": {"type": "string", "description": "Contact person's name"},
                "facility": {"type": "string", "description": "Facility name"},
            },
            "required": ["contact_name", "facility"],
        },
    ),
]

MONITOR_TOOLS = [
    ToolDefinition(
        name="check_trial",
        description="Fetch current trial data and compare to last known state.",
        parameters={
            "type": "object",
            "properties": {
                "nct_id": {"type": "string", "description": "Trial NCT ID"},
                "last_status": {"type": "string", "description": "Previous known status"},
                "last_site_count": {"type": "integer", "description": "Previous known site count"},
            },
            "required": ["nct_id"],
        },
    ),
    ToolDefinition(
        name="assess_impact",
        description="For a detected change, assess its impact on the patient.",
        parameters={
            "type": "object",
            "properties": {
                "nct_id": {"type": "string", "description": "Trial NCT ID"},
                "change_type": {"type": "string", "description": "Type of change (status_changed, sites_added)"},
                "detail": {"type": "string", "description": "What changed"},
            },
            "required": ["nct_id", "change_type", "detail"],
        },
    ),
]


@register_agent
class MatchingAgent(BaseAgent):
    """Adaptive agent: plans search strategy, analyzes, refines, and self-corrects.

    Uses the ReAct loop with domain-specific search strategies.
    Workflow: workflows/matching.md
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

        # Route: classify patient complexity → configure budget and strategy
        route = classify_patient(patient)
        budget = route.to_budget()

        # Run enrichments concurrently: patient summary, biomarker lookup, drug normalization
        summary_task = asyncio.create_task(self._generate_summary(patient))
        biomarker_task = asyncio.create_task(self._enrich_biomarkers(patient))
        drug_task = asyncio.create_task(self._normalize_drugs(patient))

        # Await enrichments (these feed into prompts)
        biomarker_context, drug_map = await asyncio.gather(biomarker_task, drug_task)

        # Build prompt variables from patient profile
        patient_vars = format_patient_for_prompt(patient)

        # Inject normalized drug names into patient vars
        if drug_map:
            normalized_treatments = []
            for t in patient.prior_treatments:
                norm = drug_map.get(t)
                if norm and norm["canonical"] != t:
                    normalized_treatments.append(f"{norm['canonical']} (reported as: {t})")
                else:
                    normalized_treatments.append(t)
            patient_vars["prior_treatments"] = ", ".join(normalized_treatments) or "None"

        prompt_vars = {
            **patient_vars,
            "location_zip": patient.location_zip,
            "willing_to_travel_miles": patient.willing_to_travel_miles,
            "strategy_hint": route.strategy_hint,
        }

        # Agent-specific state stored in scratchpad
        scratchpad = Scratchpad(
            state={
                "patient": patient,
                "max_results": max_results,
                "trials_pool": {},  # nct_id → trial dict (deduplicated)
                "analyses": {},  # nct_id → analysis dict
                "settings": settings,
                "route": route,
                "biomarker_context": biomarker_context,  # CIViC enrichment for prompts
                "drug_map": drug_map,  # RxNorm normalized drug names
            }
        )

        # Define action handlers
        handlers = {
            "search": self._handle_search,
            "analyze_batch": self._handle_analyze_batch,
            "evaluate": self._handle_evaluate,
        }

        # Run the adaptive loop with routed budget
        scratchpad = await run_agent_loop(
            orchestrator_prompt_template=MATCHING_ORCHESTRATOR_PROMPT,
            prompt_vars=prompt_vars,
            action_handlers=handlers,
            scratchpad=scratchpad,
            budget=budget,
            emit=ctx.emit,
            tool_definitions=MATCHING_TOOLS,
        )

        # Build final result from scratchpad state
        patient_summary = await summary_task
        matches = self._build_final_matches(scratchpad, patient, max_results)
        matches_data = [m.model_dump() for m in matches]

        total_tokens = scratchpad.total_token_usage
        return AgentResult(
            success=True,
            output_data={
                "patient_summary": patient_summary,
                "matches": matches_data,
                "total_trials_screened": len(scratchpad.state.get("trials_pool", {})),
                "token_usage": {
                    "input_tokens": total_tokens.input_tokens,
                    "output_tokens": total_tokens.output_tokens,
                    "total_tokens": total_tokens.total_tokens,
                },
            },
        )

    async def _handle_search(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        """Handle a search action — query ClinicalTrials.gov."""
        if budget.searches_remaining <= 0:
            return "Search budget exhausted", False

        patient = scratchpad.state["patient"]
        params = decision.params
        result = await search_and_merge_tool(
            cancer_type=params.get("query_cond", patient.cancer_type),
            age=patient.age,
            sex=patient.sex,
            page_size=params.get("page_size", 20),
            query_intr=params.get("query_intr"),
            query_term=params.get("query_term"),
            include_nci=True,
        )
        budget.search_calls_used += 1

        if not result.success:
            return f"Search failed: {result.error}", False

        # Deduplicate into trials pool
        pool = scratchpad.state["trials_pool"]
        new_count = 0
        for trial in result.data:
            nct_id = trial["nct_id"]
            if nct_id not in pool:
                pool[nct_id] = trial
                new_count += 1

        total = len(pool)
        return f"Found {len(result.data)} trials ({new_count} new, {total} total in pool)", True

    async def _handle_analyze_batch(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        """Handle analyze_batch — run eligibility analysis on unanalyzed trials."""
        pool = scratchpad.state["trials_pool"]
        analyses = scratchpad.state["analyses"]
        patient = scratchpad.state["patient"]
        settings = scratchpad.state["settings"]

        # Find unanalyzed trials
        unanalyzed = {nct_id: trial for nct_id, trial in pool.items() if nct_id not in analyses}
        if not unanalyzed:
            return "No unanalyzed trials in pool", False

        # Respect budget
        to_analyze = list(unanalyzed.values())[: budget.analyses_remaining]
        if not to_analyze:
            return "Analysis budget exhausted", False

        biomarker_context = scratchpad.state.get("biomarker_context", "")
        semaphore = asyncio.Semaphore(settings.max_concurrent_analyses)

        async def analyze_one(trial: dict) -> tuple[str, dict | None]:
            async with semaphore:
                result = await self._analyze_single_trial(patient, trial, settings, biomarker_context)
                return trial["nct_id"], result

        results = await asyncio.gather(*[analyze_one(t) for t in to_analyze])
        budget.analysis_calls_used += len(to_analyze)

        scored = 0
        high_scores = 0
        for nct_id, analysis in results:
            if analysis is not None:
                analyses[nct_id] = analysis
                scored += 1
                if analysis.get("match_score", 0) >= 60:
                    high_scores += 1

        scores = [a.get("match_score", 0) for a in analyses.values()]
        score_summary = ""
        if scores:
            score_summary = f" Scores: min={min(scores)}, max={max(scores)}, ≥60: {high_scores}"

        return f"Analyzed {len(to_analyze)} trials, {scored} scored.{score_summary}", True

    async def _handle_evaluate(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        """Handle evaluate — re-evaluate borderline scores."""
        analyses = scratchpad.state["analyses"]
        pool = scratchpad.state["trials_pool"]
        patient = scratchpad.state["patient"]
        settings = scratchpad.state["settings"]

        patient_vars = format_patient_for_prompt(patient)
        borderline = [
            (nct_id, analysis)
            for nct_id, analysis in analyses.items()
            if settings.evaluation_score_min <= analysis.get("match_score", 0) <= settings.evaluation_score_max
        ]

        if not borderline:
            return "No borderline scores to evaluate", True

        adjusted_count = 0
        for nct_id, analysis in borderline:
            trial = pool[nct_id]
            eligibility_text = trial["eligibility_criteria"][:6000]

            criteria = []
            for ev in analysis.get("inclusion_evaluations", []):
                criteria.append({"type": "inclusion", **ev})
            for ev in analysis.get("exclusion_evaluations", []):
                criteria.append({"type": "exclusion", **ev})

            result = await evaluate_score(
                patient_vars=patient_vars,
                nct_id=nct_id,
                brief_title=trial["brief_title"],
                eligibility_criteria=eligibility_text,
                initial_score=analysis.get("match_score", 0),
                initial_explanation=analysis.get("match_explanation", ""),
                criteria_json=json.dumps(criteria, indent=2),
            )

            if result.success and not result.data["confirmed"] and result.data["adjusted_score"] is not None:
                old = analysis["match_score"]
                analysis["match_score"] = result.data["adjusted_score"]
                analysis.setdefault("flags_for_oncologist", []).append(
                    f"Score adjusted from {old} to {result.data['adjusted_score']}: {result.data['adjustment_reason']}"
                )
                adjusted_count += 1

        return f"Evaluated {len(borderline)} borderline scores, adjusted {adjusted_count}", True

    async def _analyze_single_trial(
        self, patient: PatientProfile, trial: dict, settings, biomarker_context: str = ""
    ) -> dict | None:
        """Analyze a single trial's eligibility with enriched biomarker data."""
        nct_id = trial["nct_id"]
        eligibility_text = trial["eligibility_criteria"]
        if len(eligibility_text) > 6000:
            eligibility_text = (
                eligibility_text[:6000] + "\n\n[Eligibility text truncated — focus on the criteria above]"
            )

        # Append CIViC biomarker context to eligibility text if available
        if biomarker_context:
            eligibility_text = eligibility_text + "\n\n" + biomarker_context

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
                    return result
                if attempt < settings.max_retries:
                    continue
                return extract_minimal_result(text, nct_id)
            except Exception:
                if attempt < settings.max_retries:
                    continue
                return None
        return None

    def _build_final_matches(self, scratchpad: Scratchpad, patient: PatientProfile, max_results: int):
        """Build ranked TrialMatch list from scratchpad state."""
        from models import TrialMatch

        pool = scratchpad.state.get("trials_pool", {})
        analyses = scratchpad.state.get("analyses", {})
        matches: list[TrialMatch] = []

        if not analyses and pool:
            # All analyses failed — return unscored matches
            for trial in pool.values():
                match = build_unscored_match(trial, patient)
                if match.distance_miles is None or match.distance_miles <= patient.willing_to_travel_miles:
                    matches.append(match)
        else:
            for nct_id, analysis in analyses.items():
                trial = pool.get(nct_id)
                if trial is None:
                    continue
                match = build_scored_match(trial, analysis, patient)
                if match is not None:
                    matches.append(match)

        matches.sort(key=lambda m: m.match_score, reverse=True)
        return matches[:max_results]

    async def _enrich_biomarkers(self, patient: PatientProfile) -> str:
        """Look up CIViC evidence for patient biomarkers. Returns context block for prompts."""
        if not patient.biomarkers:
            return ""
        try:
            result = await enrich_biomarkers_tool(biomarkers=patient.biomarkers, cancer_type=patient.cancer_type)
            if result.success:
                return result.data.get("context_block", "")
        except Exception as e:
            logger.warning("matching.biomarker_enrichment_failed", error=str(e))
        return ""

    async def _normalize_drugs(self, patient: PatientProfile) -> dict:
        """Normalize patient's prior treatment names via RxNorm. Returns name→info map."""
        if not patient.prior_treatments:
            return {}
        try:
            result = await normalize_drug_list_tool(names=patient.prior_treatments)
            if result.success:
                return result.data.get("normalized", {})
        except Exception as e:
            logger.warning("matching.drug_normalization_failed", error=str(e))
        return {}

    async def _generate_summary(self, patient: PatientProfile) -> str:
        """Generate patient summary (runs concurrently with agent loop)."""
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


# ---------------------------------------------------------------------------
# DossierAgent — adaptive deep analysis
# ---------------------------------------------------------------------------


@register_agent
class DossierAgent(BaseAgent):
    """Adaptive agent: reasons about which trials need deeper investigation.

    Workflow: workflows/dossier.md
    """

    agent_type: ClassVar[str] = "dossier"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = DossierInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        settings = get_settings()
        top_n = inputs.top_n or settings.dossier_top_n
        top_matches = sorted(inputs.matches, key=lambda m: m.get("match_score", 0), reverse=True)[:top_n]

        matches_summary = "\n".join(
            f"- {m['nct_id']}: {m.get('brief_title', '?')[:60]} (score: {m.get('match_score', '?')})"
            for m in top_matches
        )

        scratchpad = Scratchpad(
            state={
                "patient_data": inputs.patient,
                "matches": {m["nct_id"]: m for m in top_matches},
                "sections": {},
                "settings": settings,
            }
        )

        handlers = {
            "deep_analyze": self._handle_deep_analyze,
            "investigate_criterion": self._handle_investigate,
        }

        scratchpad = await run_agent_loop(
            orchestrator_prompt_template=DOSSIER_ORCHESTRATOR_PROMPT,
            prompt_vars={
                "patient_json": json.dumps(inputs.patient, indent=2),
                "matches_summary": matches_summary,
            },
            action_handlers=handlers,
            scratchpad=scratchpad,
            emit=ctx.emit,
            tool_definitions=DOSSIER_TOOLS,
        )

        # Assemble dossier from completed analyses
        sections = list(scratchpad.state.get("sections", {}).values())
        total_tokens = scratchpad.total_token_usage
        dossier = {
            "patient_summary": ctx.input_data.get("patient_summary", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sections": sections,
        }

        return AgentResult(
            success=True,
            output_data={
                "dossier": dossier,
                "token_usage": {
                    "input_tokens": total_tokens.input_tokens,
                    "output_tokens": total_tokens.output_tokens,
                    "total_tokens": total_tokens.total_tokens,
                },
            },
            gate_request=GateRequest(gate_type="dossier_review", requested_data={"dossier": dossier}),
        )

    async def _handle_deep_analyze(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        nct_id = decision.params.get("nct_id", "")
        match = scratchpad.state["matches"].get(nct_id)
        if not match:
            return f"Trial {nct_id} not in top matches", False

        settings = scratchpad.state["settings"]
        patient_data = scratchpad.state["patient_data"]

        prompt_result = render_prompt(
            prompt_name="dossier_analysis",
            patient_json=json.dumps(patient_data, indent=2),
            nct_id=nct_id,
            brief_title=match["brief_title"],
            eligibility_criteria=match.get("eligibility_criteria", "Not available"),
            initial_score=match.get("match_score", 0),
            initial_explanation=match.get("match_explanation", ""),
        )
        if not prompt_result.success:
            section = build_dossier_section(match, None)
            scratchpad.state["sections"][nct_id] = section
            return f"Prompt failed for {nct_id}, recorded error section", False

        result = await claude_json_call(
            prompt_result.data,
            model=settings.dossier_model,
            max_tokens=settings.dossier_max_tokens,
        )

        section = build_dossier_section(match, result.data if result.success else None)
        scratchpad.state["sections"][nct_id] = section

        revised = section.get("revised_score", "?")
        return f"Deep analysis of {nct_id}: revised score {revised}", True

    async def _handle_investigate(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        nct_id = decision.params.get("nct_id", "")
        question = decision.params.get("question", "")
        trial_result = await fetch_trial_tool(nct_id=nct_id)
        if not trial_result.success:
            return f"Could not fetch {nct_id}: {trial_result.error}", False
        return (
            f"Fetched fresh data for {nct_id}. Question: {question}. Trial has {len(trial_result.data.get('locations', []))} sites.",
            True,
        )


# ---------------------------------------------------------------------------
# EnrollmentAgent — adaptive packet generation
# ---------------------------------------------------------------------------


@register_agent
class EnrollmentAgent(BaseAgent):
    """Adaptive agent: strategizes enrollment packet creation.

    Workflow: workflows/enrollment.md
    """

    agent_type: ClassVar[str] = "enrollment"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = EnrollmentInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        dossier = inputs.dossier
        trial_nct_id = inputs.trial_nct_id
        section = next((s for s in dossier.get("sections", []) if s.get("nct_id") == trial_nct_id), None)
        if not section:
            return AgentResult(success=False, error=f"No dossier section found for {trial_nct_id}")

        scratchpad = Scratchpad(
            state={
                "patient_data": inputs.patient,
                "dossier": dossier,
                "section": section,
                "trial_nct_id": trial_nct_id,
                "nearest_site": {},
                "packet": None,
                "prep": None,
                "outreach": None,
            }
        )

        handlers = {
            "fetch_site_info": self._handle_fetch_site,
            "generate_packet": self._handle_generate_packet,
            "generate_prep_guide": self._handle_generate_prep,
            "generate_outreach": self._handle_generate_outreach,
        }

        scratchpad = await run_agent_loop(
            orchestrator_prompt_template=ENROLLMENT_ORCHESTRATOR_PROMPT,
            prompt_vars={
                "patient_summary": section.get("clinical_summary", dossier.get("patient_summary", "")),
                "nct_id": trial_nct_id,
                "brief_title": section.get("brief_title", ""),
                "revised_score": section.get("revised_score", "?"),
            },
            action_handlers=handlers,
            scratchpad=scratchpad,
            emit=ctx.emit,
            tool_definitions=ENROLLMENT_TOOLS,
        )

        state = scratchpad.state
        output = {
            "patient_packet": state.get("packet") or {"error": "Failed to generate"},
            "patient_prep_guide": state.get("prep") or {"error": "Failed to generate"},
            "outreach_draft": state.get("outreach") or {"error": "Failed to generate"},
            "trial_nct_id": trial_nct_id,
            "trial_title": section.get("brief_title", ""),
        }

        return AgentResult(
            success=True,
            output_data=output,
            gate_request=GateRequest(gate_type="enrollment_review", requested_data=output),
        )

    async def _handle_fetch_site(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        nct_id = decision.params.get("nct_id", scratchpad.state["trial_nct_id"])
        result = await fetch_trial_tool(nct_id=nct_id)
        if not result.success:
            return f"Could not fetch trial: {result.error}", False
        locations = result.data.get("locations", [])
        if locations:
            scratchpad.state["nearest_site"] = locations[0]
        contacts_count = sum(len(loc.get("contacts", [])) for loc in locations[:5])
        return f"Fetched {nct_id}: {len(locations)} sites, {contacts_count} contacts", True

    async def _handle_generate_packet(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        state = scratchpad.state
        prompt_result = render_prompt(
            prompt_name="enrollment_packet",
            patient_json=json.dumps(state["patient_data"], indent=2),
            nct_id=state["trial_nct_id"],
            brief_title=state["section"].get("brief_title", ""),
            revised_score=state["section"].get("revised_score", "?"),
            clinical_summary=state["section"].get("clinical_summary", ""),
            criteria_json=json.dumps(state["section"].get("criteria_analysis", [])[:10], indent=2),
        )
        if not prompt_result.success:
            return f"Prompt failed: {prompt_result.error}", False
        result = await claude_json_call(prompt_result.data)
        if result.success:
            state["packet"] = result.data
            items = len(result.data.get("screening_checklist", []))
            return f"Generated packet with {items} screening items", True
        return "Failed to generate packet", False

    async def _handle_generate_prep(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        state = scratchpad.state
        site = state.get("nearest_site", {})
        prompt_result = render_prompt(
            prompt_name="patient_prep",
            cancer_type=state["patient_data"].get("cancer_type", ""),
            cancer_stage=state["patient_data"].get("cancer_stage", ""),
            age=state["patient_data"].get("age", ""),
            brief_title=state["section"].get("brief_title", ""),
            site_name=site.get("facility", "Trial site"),
            site_city=site.get("city", ""),
            site_state=site.get("state", ""),
            screening_checklist=json.dumps((state.get("packet") or {}).get("screening_checklist", []), indent=2),
        )
        if not prompt_result.success:
            return f"Prompt failed: {prompt_result.error}", False
        result = await claude_json_call(prompt_result.data)
        if result.success:
            state["prep"] = result.data
            return "Generated patient prep guide", True
        return "Failed to generate prep guide", False

    async def _handle_generate_outreach(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        state = scratchpad.state
        site = state.get("nearest_site", {})
        contact_name = "Research Coordinator"
        if site.get("contacts"):
            contact_name = site["contacts"][0].get("name", "Research Coordinator")

        prompt_result = render_prompt(
            prompt_name="outreach_message",
            nct_id=state["trial_nct_id"],
            brief_title=state["section"].get("brief_title", ""),
            site_name=site.get("facility", "Trial site"),
            site_city=site.get("city", ""),
            site_state=site.get("state", ""),
            contact_name=contact_name,
            patient_summary=state["section"].get("clinical_summary", state["dossier"].get("patient_summary", "")),
            match_score=state["section"].get("revised_score", "?"),
            match_rationale=state["section"].get("score_justification", ""),
        )
        if not prompt_result.success:
            return f"Prompt failed: {prompt_result.error}", False
        result = await claude_json_call(prompt_result.data)
        if result.success:
            state["outreach"] = result.data
            return "Generated outreach draft", True
        return "Failed to generate outreach", False


# ---------------------------------------------------------------------------
# OutreachAgent — adaptive contact extraction and personalization
# ---------------------------------------------------------------------------


@register_agent
class OutreachAgent(BaseAgent):
    """Adaptive agent: strategizes outreach personalization.

    Workflow: workflows/outreach.md
    """

    agent_type: ClassVar[str] = "outreach"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = OutreachInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        scratchpad = Scratchpad(
            state={
                "outreach_draft": inputs.outreach_draft,
                "trial_nct_id": inputs.trial_nct_id,
                "contacts": [],
                "final_message": inputs.outreach_draft.get("message_body", ""),
                "subject_line": inputs.outreach_draft.get(
                    "subject_line", f"Pre-screened patient candidate for {inputs.trial_nct_id}"
                ),
            }
        )

        handlers = {
            "fetch_contacts": self._handle_fetch_contacts,
            "personalize": self._handle_personalize,
        }

        scratchpad = await run_agent_loop(
            orchestrator_prompt_template=OUTREACH_ORCHESTRATOR_PROMPT,
            prompt_vars={
                "nct_id": inputs.trial_nct_id,
                "brief_title": inputs.outreach_draft.get("brief_title", ""),
                "outreach_draft": json.dumps(inputs.outreach_draft, indent=2),
            },
            action_handlers=handlers,
            scratchpad=scratchpad,
            emit=ctx.emit,
            tool_definitions=OUTREACH_TOOLS,
        )

        state = scratchpad.state
        output = {
            "contacts": state["contacts"],
            "final_message": state["final_message"],
            "subject_line": state["subject_line"],
            "outreach_status": "ready_for_review",
        }

        return AgentResult(
            success=True,
            output_data=output,
            gate_request=GateRequest(gate_type="outreach_review", requested_data=output),
        )

    async def _handle_fetch_contacts(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        nct_id = decision.params.get("nct_id", scratchpad.state["trial_nct_id"])
        result = await fetch_trial_tool(nct_id=nct_id)
        if not result.success:
            return f"Could not fetch trial: {result.error}", False
        contacts = extract_contacts(result.data)
        scratchpad.state["contacts"] = contacts
        named = sum(1 for c in contacts if c.get("name"))
        return f"Found {len(contacts)} contacts ({named} with names)", True

    async def _handle_personalize(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        contact_name = decision.params.get("contact_name", "")
        facility = decision.params.get("facility", "the trial site")
        original = scratchpad.state["final_message"]

        result = await claude_json_call(
            f"Personalize this outreach message for {contact_name} at {facility}. "
            f"Keep the message professional and under 4 paragraphs.\n\nOriginal message:\n{original}\n\n"
            'Respond with ONLY a JSON object: {{"message_body": "<personalized message>"}}',
            max_tokens=800,
        )
        if result.success:
            scratchpad.state["final_message"] = result.data.get("message_body", original)
            return f"Personalized message for {contact_name}", True
        return "Personalization failed, keeping original", False


# ---------------------------------------------------------------------------
# MonitorAgent — adaptive trial status monitoring
# ---------------------------------------------------------------------------


@register_agent
class MonitorAgent(BaseAgent):
    """Adaptive agent: reasons about trial changes and their impact.

    Workflow: workflows/monitor.md
    """

    agent_type: ClassVar[str] = "monitor"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = MonitorInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        watches = inputs.watches
        watches_summary = "\n".join(
            f"- {w['nct_id']}: last_status={w.get('last_status', '?')}, sites={w.get('last_site_count', '?')}"
            for w in watches
        )

        scratchpad = Scratchpad(
            state={
                "watches": {w["nct_id"]: w for w in watches},
                "changes": [],
                "checked": set(),
            }
        )

        handlers = {
            "check_trial": self._handle_check_trial,
            "assess_impact": self._handle_assess_impact,
        }

        scratchpad = await run_agent_loop(
            orchestrator_prompt_template=MONITOR_ORCHESTRATOR_PROMPT,
            prompt_vars={"watches_summary": watches_summary},
            action_handlers=handlers,
            scratchpad=scratchpad,
            emit=ctx.emit,
            tool_definitions=MONITOR_TOOLS,
        )

        return AgentResult(
            success=True,
            output_data={
                "changes": scratchpad.state["changes"],
                "trials_checked": len(scratchpad.state["checked"]),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _handle_check_trial(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        nct_id = decision.params.get("nct_id", "")
        last_status = decision.params.get("last_status", "")
        last_site_count = decision.params.get("last_site_count", 0)

        result = await fetch_trial_tool(nct_id=nct_id)
        scratchpad.state["checked"].add(nct_id)

        if not result.success:
            scratchpad.state["changes"].append(
                {"nct_id": nct_id, "change_type": "not_found", "detail": "Trial no longer available"}
            )
            return f"{nct_id}: not found", True

        trial = result.data
        changes_found = []

        current_status = trial.get("overall_status", "")
        if current_status and current_status != last_status:
            change = {
                "nct_id": nct_id,
                "change_type": "status_changed",
                "old_status": last_status,
                "new_status": current_status,
            }
            scratchpad.state["changes"].append(change)
            changes_found.append(f"status: {last_status} → {current_status}")

        current_sites = len(trial.get("locations", []))
        if current_sites > last_site_count:
            change = {
                "nct_id": nct_id,
                "change_type": "sites_added",
                "old_count": last_site_count,
                "new_count": current_sites,
            }
            scratchpad.state["changes"].append(change)
            changes_found.append(f"sites: {last_site_count} → {current_sites}")

        if changes_found:
            return f"{nct_id}: {', '.join(changes_found)}", True
        return f"{nct_id}: no changes", True

    async def _handle_assess_impact(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        nct_id = decision.params.get("nct_id", "")
        change_type = decision.params.get("change_type", "")
        detail = decision.params.get("detail", "")

        # For now, record the assessment as a note on the change
        for change in scratchpad.state["changes"]:
            if change["nct_id"] == nct_id and change["change_type"] == change_type:
                change["impact_assessment"] = detail
                return f"Assessed impact of {change_type} on {nct_id}", True

        return f"No matching change found for {nct_id}/{change_type}", False
