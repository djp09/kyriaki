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

# Gemma pipeline imports — lazy to avoid import errors when Ollama not running
_intake_mod = None
_recall_mod = None


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

        # Stage 1 (Gemma, local): normalize free-text intake before routing
        if settings.gemma_stage1_enabled and patient.additional_notes:
            patient = await self._normalize_intake(patient)

        # Route: classify patient complexity → configure budget and strategy
        route = classify_patient(patient)

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

        # Simple patients: direct pipeline (no agent loop planning overhead)
        # Moderate/complex patients: adaptive agent loop with planning
        if route.complexity == "simple":
            pool, analyses = await self._run_direct_pipeline(
                patient,
                settings,
                biomarker_context,
                ctx.emit,
            )
        else:
            pool, analyses = await self._run_agent_loop_pipeline(
                patient,
                max_results,
                settings,
                route,
                patient_vars,
                biomarker_context,
                drug_map,
                ctx.emit,
            )

        # Build final result
        patient_summary = await summary_task
        matches = self._build_final_matches_from(pool, analyses, patient, max_results)
        matches_data = [m.model_dump() for m in matches]

        return AgentResult(
            success=True,
            output_data={
                "patient_summary": patient_summary,
                "matches": matches_data,
                "total_trials_screened": len(pool),
            },
        )

    async def _run_direct_pipeline(
        self,
        patient: PatientProfile,
        settings,
        biomarker_context: str,
        emit,
    ) -> tuple[dict, dict]:
        """Fast path for simple patients: search → prescreen → deep analyze. No planning calls."""
        logger.info("matching.direct_pipeline_start")

        if emit:
            await emit("progress", {"step": "searching_trials", "iteration": 1, "reasoning": "Searching for trials"})

        pool = await self._do_search(patient)
        logger.info("matching.direct_search_complete", trials=len(pool))
        # NOTE: no Stage 3 semantic ranking in direct pipeline — the API
        # already returns results in relevance order. Re-ranking with
        # shallow embeddings degrades that ordering.

        if emit:
            await emit("progress", {"step": "analyzing_trials", "iteration": 2, "reasoning": "Analyzing eligibility"})

        analyses = await self._do_prescreen_and_analyze(pool, patient, settings, biomarker_context, max_deep=5)
        logger.info("matching.direct_pipeline_complete", analyzed=len(analyses), pool=len(pool))

        return pool, analyses

    async def _run_agent_loop_pipeline(
        self,
        patient: PatientProfile,
        max_results: int,
        settings,
        route,
        patient_vars: dict,
        biomarker_context: str,
        drug_map: dict,
        emit,
    ) -> tuple[dict, dict]:
        """Adaptive path for moderate/complex patients: full ReAct agent loop."""
        budget = route.to_budget()

        prompt_vars = {
            **patient_vars,
            "location_zip": patient.location_zip,
            "willing_to_travel_miles": patient.willing_to_travel_miles,
            "strategy_hint": route.strategy_hint,
        }

        scratchpad = Scratchpad(
            state={
                "patient": patient,
                "max_results": max_results,
                "trials_pool": {},
                "analyses": {},
                "settings": settings,
                "route": route,
                "biomarker_context": biomarker_context,
                "drug_map": drug_map,
            }
        )

        handlers = {
            "search": self._handle_search,
            "analyze_batch": self._handle_analyze_batch,
            "evaluate": self._handle_evaluate,
        }

        scratchpad = await run_agent_loop(
            orchestrator_prompt_template=MATCHING_ORCHESTRATOR_PROMPT,
            prompt_vars=prompt_vars,
            action_handlers=handlers,
            scratchpad=scratchpad,
            budget=budget,
            emit=emit,
            tool_definitions=MATCHING_TOOLS,
        )

        return scratchpad.state.get("trials_pool", {}), scratchpad.state.get("analyses", {})

    async def _do_search(self, patient: PatientProfile) -> dict:
        """Core search logic: query ClinicalTrials.gov + NCI, return deduplicated pool."""
        result = await search_and_merge_tool(
            cancer_type=patient.cancer_type,
            age=patient.age,
            sex=patient.sex,
            page_size=20,
            include_nci=True,
        )
        if not result.success:
            logger.warning("matching.search_failed", error=result.error)
            return {}

        pool = {}
        for trial in result.data:
            pool[trial["nct_id"]] = trial
        return pool

    async def _do_prescreen_and_analyze(
        self,
        pool: dict,
        patient: PatientProfile,
        settings,
        biomarker_context: str,
        max_deep: int = 5,
    ) -> dict:
        """Core prescreen + deep analysis logic. Returns analyses dict."""
        from prompts import PRESCREEN_PROMPT

        analyses: dict = {}
        if not pool:
            return analyses

        MAX_PRESCREEN = 30
        unanalyzed = dict(list(pool.items())[:MAX_PRESCREEN])

        # --- Tier 1: Fast pre-screen ---
        trials_list_lines = []
        for trial in unanalyzed.values():
            trials_list_lines.append(
                f"- **{trial['nct_id']}**: {trial['brief_title']}\n"
                f"  Phase: {trial['phase']} | Conditions: {', '.join(trial.get('conditions', []))}\n"
                f"  Summary: {trial['brief_summary'][:200]}"
            )

        patient_vars = format_patient_for_prompt(patient)
        prescreen_prompt = PRESCREEN_PROMPT.format(
            **patient_vars,
            trials_list="\n".join(trials_list_lines),
        )

        prescreen_result = await claude_json_call(prescreen_prompt, max_tokens=1200)
        if not prescreen_result.success:
            high_tier_ids = list(unanalyzed.keys())[:max_deep]
        else:
            rankings = prescreen_result.data.get("rankings", [])
            high_tier_ids = [r["nct_id"] for r in rankings if r.get("tier") == "HIGH"]
            logger.info(
                "matching.prescreen",
                total=len(rankings),
                high=len(high_tier_ids),
                low=len(rankings) - len(high_tier_ids),
            )

            for r in rankings:
                if r.get("tier") == "LOW" and r["nct_id"] not in analyses:
                    analyses[r["nct_id"]] = {
                        "match_score": 0,
                        "match_tier": "EXCLUDED",
                        "match_explanation": f"Pre-screen: {r.get('reason', 'Not relevant')}",
                        "inclusion_evaluations": [],
                        "exclusion_evaluations": [],
                        "flags_for_oncologist": [],
                        "criteria_met": 0,
                        "criteria_not_met": 0,
                        "criteria_unknown": 0,
                        "criteria_total": 0,
                    }

        # If pre-screen found very few HIGH candidates, force-analyze the top
        # few anyway. The fast pre-screen can be overly aggressive for early-stage
        # or uncommon cancer types, and a deeper criterion-level analysis may
        # find partial matches the pre-screen missed.
        MIN_DEEP_ANALYZE = 3
        if len(high_tier_ids) < MIN_DEEP_ANALYZE:
            # Add unanalyzed trials not already in high_tier_ids, preserving pool order
            for nct_id in unanalyzed:
                if nct_id not in high_tier_ids and nct_id not in analyses:
                    high_tier_ids.append(nct_id)
                if len(high_tier_ids) >= MIN_DEEP_ANALYZE:
                    break

        if not high_tier_ids:
            return analyses

        # --- Tier 2: Deep analysis on HIGH-tier ---
        to_analyze = [unanalyzed[nid] for nid in high_tier_ids[:max_deep] if nid in unanalyzed]

        async def analyze_one(trial: dict) -> tuple[str, dict | None]:
            result = await self._analyze_single_trial(patient, trial, settings, biomarker_context)
            return trial["nct_id"], result

        results = await asyncio.gather(*[analyze_one(t) for t in to_analyze])

        for nct_id, analysis in results:
            if analysis is not None:
                analyses[nct_id] = analysis

        return analyses

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
        """Handle analyze_batch — two-tier analysis for speed.

        Tier 1: Fast pre-screen ALL unanalyzed trials in one Claude call (~5s).
        Tier 2: Deep criterion-level analysis on only the HIGH-tier trials (~5s each).
        """
        from prompts import PRESCREEN_PROMPT

        pool = scratchpad.state["trials_pool"]
        analyses = scratchpad.state["analyses"]
        patient = scratchpad.state["patient"]
        settings = scratchpad.state["settings"]

        # Find unanalyzed trials
        unanalyzed = {nct_id: trial for nct_id, trial in pool.items() if nct_id not in analyses}
        if not unanalyzed:
            return "No unanalyzed trials in pool", False

        # Stage 3 (Gemma, local): re-rank unanalyzed trials by semantic similarity
        unanalyzed = await self._semantic_rank(unanalyzed, patient, settings)

        # --- Tier 1: Fast pre-screen in a single call ---
        trials_list_lines = []
        for trial in unanalyzed.values():
            trials_list_lines.append(
                f"- **{trial['nct_id']}**: {trial['brief_title']}\n"
                f"  Phase: {trial['phase']} | Conditions: {', '.join(trial.get('conditions', []))}\n"
                f"  Summary: {trial['brief_summary'][:150]}"
            )

        patient_vars = format_patient_for_prompt(patient)
        prescreen_prompt = PRESCREEN_PROMPT.format(
            **patient_vars,
            trials_list="\n".join(trials_list_lines),
        )

        prescreen_result = await claude_json_call(prescreen_prompt, max_tokens=800)
        if not prescreen_result.success:
            # Fallback: analyze first 5 without pre-screening
            high_tier_ids = list(unanalyzed.keys())[:5]
        else:
            rankings = prescreen_result.data.get("rankings", [])
            high_tier_ids = [r["nct_id"] for r in rankings if r.get("tier") == "HIGH"]
            low_count = len(rankings) - len(high_tier_ids)
            logger.info(
                "matching.prescreen",
                total=len(rankings),
                high=len(high_tier_ids),
                low=low_count,
            )

            # Mark LOW-tier trials as analyzed with score 0 so we don't re-analyze
            for r in rankings:
                if r.get("tier") == "LOW" and r["nct_id"] not in analyses:
                    analyses[r["nct_id"]] = {
                        "match_score": 0,
                        "match_tier": "EXCLUDED",
                        "match_explanation": f"Pre-screen: {r.get('reason', 'Not relevant')}",
                        "inclusion_evaluations": [],
                        "exclusion_evaluations": [],
                        "flags_for_oncologist": [],
                        "criteria_met": 0,
                        "criteria_not_met": 0,
                        "criteria_unknown": 0,
                        "criteria_total": 0,
                    }

        if not high_tier_ids:
            return f"Pre-screened {len(unanalyzed)} trials, none passed to deep analysis", True

        # --- Tier 2: Deep criterion-level analysis on HIGH-tier only ---
        max_deep = min(len(high_tier_ids), budget.analyses_remaining, 5)
        to_analyze = [unanalyzed[nid] for nid in high_tier_ids[:max_deep] if nid in unanalyzed]

        biomarker_context = scratchpad.state.get("biomarker_context", "")

        async def analyze_one(trial: dict) -> tuple[str, dict | None]:
            result = await self._analyze_single_trial(patient, trial, settings, biomarker_context)
            return trial["nct_id"], result

        results = await asyncio.gather(*[analyze_one(t) for t in to_analyze])
        budget.analysis_calls_used += len(to_analyze) + 1  # +1 for prescreen

        scored = 0
        high_scores = 0
        for nct_id, analysis in results:
            if analysis is not None:
                analyses[nct_id] = analysis
                scored += 1
                if analysis.get("match_score", 0) >= 60:
                    high_scores += 1

        scores = [a.get("match_score", 0) for a in analyses.values() if a.get("match_score", 0) > 0]
        score_summary = ""
        if scores:
            score_summary = f" Scores: min={min(scores)}, max={max(scores)}, ≥60: {high_scores}"

        return (
            f"Pre-screened {len(unanalyzed)}, deep-analyzed {len(to_analyze)}, {scored} scored.{score_summary}",
            True,
        )

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

        async def _eval_one(nct_id: str, analysis: dict) -> bool:
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
                return True
            return False

        results = await asyncio.gather(*[_eval_one(nct_id, analysis) for nct_id, analysis in borderline])
        adjusted_count = sum(1 for r in results if r)

        return f"Evaluated {len(borderline)} borderline scores, adjusted {adjusted_count}", True

    async def _analyze_single_trial(
        self, patient: PatientProfile, trial: dict, settings, biomarker_context: str = ""
    ) -> dict | None:
        """Analyze a single trial's eligibility using criterion-level decomposition.

        Pipeline: parse criteria → evaluate per-criterion → score programmatically.
        """
        from tools.criteria_parser import parse_eligibility_criteria
        from tools.scoring import calculate_match_score

        nct_id = trial["nct_id"]
        eligibility_text = trial["eligibility_criteria"]
        if len(eligibility_text) > 6000:
            eligibility_text = eligibility_text[:6000] + "\n\n[Eligibility text truncated]"

        # Step 1: Parse criteria into structured list
        # Check for Gemma-extracted criteria (Stage 4, cached during nightly sync) first.
        # Fall back to rule-based parser for real-time.
        cached_criteria = await self._get_cached_criteria(nct_id, eligibility_text, settings)
        if cached_criteria:
            parsed = cached_criteria
            logger.info("analysis.using_cached_gemma_criteria", nct_id=nct_id)
        else:
            parse_result = parse_eligibility_criteria(eligibility_text)
            if not parse_result.success or parse_result.data["total_criteria"] == 0:
                logger.warning("analysis.no_criteria_parsed", nct_id=nct_id)
                return None
            parsed = parse_result.data

        # Prioritize the most important criteria to keep prompts short.
        # High-priority categories determine eligibility; low-priority are
        # consent/washout/labs that rarely disqualify.
        HIGH_PRIORITY = {"diagnosis", "biomarker", "stage", "prior_therapy", "performance", "demographic"}

        def _sort_key(c):
            return 0 if c["category"] in HIGH_PRIORITY else 1

        MAX_CRITERIA = 15
        inc = sorted(parsed["inclusion_criteria"], key=_sort_key)[:MAX_CRITERIA]
        exc = sorted(parsed["exclusion_criteria"], key=_sort_key)[:MAX_CRITERIA]

        criteria_lines = []
        for c in inc:
            criteria_lines.append(f"[{c['id']}] INCLUSION ({c['category']}): {c['text']}")
        for c in exc:
            criteria_lines.append(f"[{c['id']}] EXCLUSION ({c['category']}): {c['text']}")
        parsed_criteria_text = "\n".join(criteria_lines)

        # Step 2: Evaluate each criterion with Claude
        patient_vars = format_patient_for_prompt(patient)
        enriched = ""
        if biomarker_context:
            enriched = f"## Enriched Biomarker Context\n{biomarker_context}"

        prompt_result = render_prompt(
            prompt_name="eligibility_analysis",
            **patient_vars,
            nct_id=nct_id,
            brief_title=trial["brief_title"],
            phase=trial["phase"],
            brief_summary=trial["brief_summary"],
            parsed_criteria=parsed_criteria_text,
            enriched_context=enriched,
        )
        if not prompt_result.success:
            return None

        # Adaptive max_tokens: scale with criteria count to avoid truncation
        analysis_max_tokens = min(2500, max(1200, len(criteria_lines) * 120))

        for attempt in range(settings.max_retries + 1):
            try:
                response = await paced_claude_call(
                    get_claude_client(),
                    model=settings.claude_model,
                    max_tokens=analysis_max_tokens,
                    messages=[{"role": "user", "content": prompt_result.data}],
                )
                text = response.content[0].text.strip()
                result = parse_json_response(text)
                if result is None:
                    logger.warning("analysis.parse_failed", nct_id=nct_id, attempt=attempt + 1, text_preview=text[:200])
                    if attempt < settings.max_retries:
                        continue
                    return None

                # Step 3: Score programmatically from criterion evaluations
                evals = result.get("criterion_evaluations", [])
                if not evals:
                    logger.warning("analysis.no_evals", nct_id=nct_id, attempt=attempt + 1, keys=list(result.keys()))
                    if attempt < settings.max_retries:
                        continue
                    return None

                # Merge category from parsed criteria into evaluations
                parsed_by_id = {}
                for c in parsed["inclusion_criteria"] + parsed["exclusion_criteria"]:
                    parsed_by_id[c["id"]] = c
                for ev in evals:
                    cid = ev.get("criterion_id", "")
                    if cid in parsed_by_id:
                        ev["category"] = parsed_by_id[cid].get("category", "other")

                flags = result.get("flags_for_oncologist", [])
                score_result = calculate_match_score(evals, flags)
                logger.info("analysis.scored", nct_id=nct_id, score=score_result["score"], tier=score_result["tier"])

                # Build the analysis dict in the shape downstream expects
                inclusion_evals = [e for e in evals if e.get("type") == "inclusion"]
                exclusion_evals = [e for e in evals if e.get("type") == "exclusion"]

                return {
                    "match_score": score_result["score"],
                    "match_tier": score_result["tier"],
                    "match_explanation": score_result["match_explanation"],
                    "inclusion_evaluations": [
                        {
                            "criterion": e.get("criterion_text", ""),
                            "criterion_id": e.get("criterion_id", ""),
                            "type": "inclusion",
                            "status": e.get("status", "INSUFFICIENT_INFO"),
                            "confidence": e.get("confidence", "MEDIUM"),
                            "explanation": e.get("reasoning", ""),
                            "patient_data_used": e.get("patient_data_used", []),
                        }
                        for e in inclusion_evals
                    ],
                    "exclusion_evaluations": [
                        {
                            "criterion": e.get("criterion_text", ""),
                            "criterion_id": e.get("criterion_id", ""),
                            "type": "exclusion",
                            "status": e.get("status", "INSUFFICIENT_INFO"),
                            "confidence": e.get("confidence", "MEDIUM"),
                            "explanation": e.get("reasoning", ""),
                            "patient_data_used": e.get("patient_data_used", []),
                        }
                        for e in exclusion_evals
                    ],
                    "flags_for_oncologist": flags,
                    "criteria_met": score_result["criteria_met"],
                    "criteria_not_met": score_result["criteria_not_met"],
                    "criteria_unknown": score_result["criteria_unknown"],
                    "criteria_total": score_result["criteria_total"],
                }

            except Exception as e:
                logger.warning("analysis.error", nct_id=nct_id, attempt=attempt, error=str(e))
                if attempt < settings.max_retries:
                    continue
                return None
        return None

    def _build_final_matches_from(self, pool: dict, analyses: dict, patient: PatientProfile, max_results: int):
        """Build ranked TrialMatch list from pool and analyses dicts."""
        from models import TrialMatch

        matches: list[TrialMatch] = []

        if not analyses and pool:
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

    async def _normalize_intake(self, patient: PatientProfile) -> PatientProfile:
        """Stage 1 (Gemma): normalize free-text intake notes into canonical fields.

        Merges Gemma-inferred fields into the patient profile, preferring
        form-provided values (ground truth) over Gemma-inferred ones.
        Returns original patient on failure (no regression).
        """
        try:
            from intake import normalize_intake

            normalized = await normalize_intake(
                patient.additional_notes or "",
                form_hints={
                    "cancer_type": patient.cancer_type,
                    "cancer_stage": patient.cancer_stage,
                    "age": patient.age,
                    "sex": patient.sex,
                },
            )
            logger.info(
                "matching.stage1_normalized",
                cancer_type=normalized.cancer_type,
                biomarkers=len(normalized.biomarkers),
            )
            return self._merge_normalized(patient, normalized)
        except Exception as e:
            logger.warning("matching.stage1_failed", error=str(e))
            return patient

    def _merge_normalized(self, patient: PatientProfile, normalized) -> PatientProfile:
        """Merge Gemma-normalized fields into patient, keeping form values as ground truth."""
        updates = {}
        # Only override if the normalized value is non-empty and the form value is generic/empty
        if normalized.cancer_type and not patient.cancer_type:
            updates["cancer_type"] = normalized.cancer_type
        if normalized.cancer_stage and not patient.cancer_stage:
            updates["cancer_stage"] = normalized.cancer_stage
        # Biomarkers and treatments: merge (union) — Gemma may extract from free-text notes
        if normalized.biomarkers:
            existing = set(patient.biomarkers)
            new_markers = [b for b in normalized.biomarkers if b not in existing]
            if new_markers:
                updates["biomarkers"] = patient.biomarkers + new_markers
        if normalized.prior_treatments:
            existing = set(patient.prior_treatments)
            new_treatments = [t for t in normalized.prior_treatments if t not in existing]
            if new_treatments:
                updates["prior_treatments"] = patient.prior_treatments + new_treatments
                updates["lines_of_therapy"] = max(patient.lines_of_therapy, normalized.lines_of_therapy)
        if normalized.ecog_score is not None and patient.ecog_score is None:
            updates["ecog_score"] = normalized.ecog_score
        if normalized.additional_conditions:
            existing = set(patient.additional_conditions)
            new_conds = [c for c in normalized.additional_conditions if c not in existing]
            if new_conds:
                updates["additional_conditions"] = patient.additional_conditions + new_conds

        if updates:
            return patient.model_copy(update=updates)
        return patient

    async def _semantic_rank(self, pool: dict, patient: PatientProfile, settings) -> dict:
        """Stage 3 (Gemma): re-rank trial pool by semantic similarity to patient.

        Only runs when enabled and pool is large enough to benefit from
        re-ranking. For small pools (<50), the API's native relevance
        ordering is usually better than shallow embedding similarity.
        Returns pool unchanged on failure (no regression).
        """
        if not settings.gemma_stage3_enabled or len(pool) < 50:
            return pool
        try:
            from semantic_recall import rank_trials_by_similarity

            trials_list = list(pool.values())
            patient_dict = patient.model_dump()
            ranked = await rank_trials_by_similarity(patient_dict, trials_list, top_n=len(trials_list))
            # Rebuild dict in ranked order
            ranked_pool = {}
            for trial, score in ranked:
                nct_id = trial["nct_id"]
                trial["_semantic_score"] = score
                ranked_pool[nct_id] = trial
            logger.info(
                "matching.stage3_ranked",
                pool_size=len(ranked_pool),
                top_score=ranked[0][1] if ranked else 0,
            )
            return ranked_pool
        except Exception as e:
            logger.warning("matching.stage3_failed", error=str(e))
            return pool

    async def _get_cached_criteria(self, nct_id: str, eligibility_text: str, settings) -> dict | None:
        """Stage 4: check for Gemma-extracted criteria cached during nightly sync.

        Returns parsed criteria dict (same shape as parse_eligibility_criteria output)
        or None if cache miss or disabled.
        """
        if not settings.gemma_stage4_enabled:
            return None
        try:
            from semantic_recall import text_hash

            _hash = text_hash(eligibility_text)  # noqa: F841 — will be used when DB query is wired
            # TODO: query trial_cache DB for structured_criteria where
            # eligibility_text_hash == _hash. For now, return None
            # until nightly sync populates the cache.
            return None
        except Exception as e:
            logger.warning("matching.stage4_cache_failed", error=str(e), nct_id=nct_id)
            return None

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
    """Adaptive agent: deep eligibility analysis for a single trial.

    Analyzes one specific trial's eligibility criteria against the patient profile.
    Each trial gets its own dossier task and gate for independent review.

    Workflow: workflows/dossier.md
    """

    agent_type: ClassVar[str] = "dossier"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = DossierInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        settings = get_settings()
        nct_id = inputs.nct_id
        match = inputs.match

        trial_summary = f"- {nct_id}: {match.get('brief_title', '?')[:60]} (score: {match.get('match_score', '?')})"

        scratchpad = Scratchpad(
            state={
                "patient_data": inputs.patient,
                "matches": {nct_id: match},
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
                "matches_summary": trial_summary,
            },
            action_handlers=handlers,
            scratchpad=scratchpad,
            emit=ctx.emit,
            tool_definitions=DOSSIER_TOOLS,
        )

        # Assemble dossier from completed analysis
        sections = list(scratchpad.state.get("sections", {}).values())
        total_tokens = scratchpad.total_token_usage
        dossier = {
            "patient_summary": inputs.patient_summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "nct_id": nct_id,
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
            gate_request=GateRequest(
                gate_type="dossier_review",
                requested_data={"dossier": dossier, "nct_id": nct_id},
            ),
        )

    async def _handle_deep_analyze(
        self, decision: AgentDecision, scratchpad: Scratchpad, budget: AgentBudget
    ) -> tuple[str, bool]:
        nct_id = decision.params.get("nct_id", "")
        match = scratchpad.state["matches"].get(nct_id)
        if not match:
            return f"Trial {nct_id} not in top matches", False

        # Guard: don't re-analyze a trial that's already been analyzed
        if nct_id in scratchpad.state["sections"]:
            existing = scratchpad.state["sections"][nct_id]
            score = existing.get("revised_score", "?")
            return (
                f"Already analyzed {nct_id} (revised score: {score}). Use investigate_criterion for follow-up or finish.",
                True,
            )

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
