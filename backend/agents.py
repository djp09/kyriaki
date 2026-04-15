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
from trials_client import biomarker_search_terms

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
    db_session: Any = None  # optional DB session for patient loading


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


async def load_patient_from_db(patient_id: uuid.UUID, session=None) -> PatientProfile:
    """Load a patient profile from DB by ID. Used by agents to avoid storing PHI in task input_data."""
    from db_service import read_patient_profile

    async def _load(s):
        patient_db = await read_patient_profile(s, patient_id, purpose="agent_execution")
        if patient_db is None:
            raise ValueError(f"Patient {patient_id} not found")
        return PatientProfile(
            cancer_type=patient_db.cancer_type,
            cancer_stage=patient_db.cancer_stage,
            biomarkers=patient_db.biomarkers or [],
            prior_treatments=patient_db.prior_treatments or [],
            lines_of_therapy=patient_db.lines_of_therapy,
            age=patient_db.age,
            sex=patient_db.sex,
            ecog_score=patient_db.ecog_score,
            key_labs=patient_db.key_labs,
            location_zip=patient_db.location_zip,
            willing_to_travel_miles=patient_db.willing_to_travel_miles,
            additional_conditions=patient_db.additional_conditions or [],
            additional_notes=patient_db.additional_notes,
        )

    if session is not None:
        return await _load(session)

    from database import async_session

    async with async_session() as new_session:
        return await _load(new_session)


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

        patient = await load_patient_from_db(ctx.patient_id, session=ctx.db_session)
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

        # Simple + moderate patients: direct pipeline (fast, no planning overhead)
        # Complex patients only: adaptive agent loop with planning
        if route.complexity in ("simple", "moderate"):
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

        analyses = await self._do_prescreen_and_analyze(pool, patient, settings, biomarker_context, max_deep=10)
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
        """Core search logic: biomarker-targeted + broad search, merged and deduplicated.

        The cancer_type is normalized to a canonical search term to avoid
        ClinicalTrials.gov keyword-search misses on subtype-suffixed inputs
        (e.g., "Non-Small Cell Lung Cancer - Adenocarcinoma" returns far
        fewer results than the canonical "Non-Small Cell Lung Cancer").
        """
        from tools.trial_classifier import canonical_search_term

        query_intr, query_term = biomarker_search_terms(patient.biomarkers or [])
        search_cancer_type = canonical_search_term(patient.cancer_type)
        if search_cancer_type != patient.cancer_type:
            logger.info(
                "matching.cancer_type_normalized",
                original=patient.cancer_type,
                canonical=search_cancer_type,
            )

        # If we have actionable biomarkers, run a targeted search AND a broad search
        # concurrently, then merge. This ensures we get biomarker-specific trials
        # (e.g., osimertinib for EGFR+) without missing general cancer-type trials.
        if query_intr:
            import asyncio

            targeted, broad = await asyncio.gather(
                search_and_merge_tool(
                    cancer_type=search_cancer_type,
                    age=patient.age,
                    sex=patient.sex,
                    page_size=20,
                    query_intr=query_intr,
                    query_term=query_term,
                    include_nci=True,
                ),
                search_and_merge_tool(
                    cancer_type=search_cancer_type,
                    age=patient.age,
                    sex=patient.sex,
                    page_size=20,
                    include_nci=True,
                ),
            )
            pool = {}
            # Targeted results first so they appear higher in the pool
            for result in [targeted, broad]:
                if result.success:
                    for trial in result.data:
                        if trial["nct_id"] not in pool:
                            pool[trial["nct_id"]] = trial
            if not pool:
                logger.warning("matching.search_failed", error="Both searches returned empty")
            return pool

        # No actionable biomarkers — single broad search
        result = await search_and_merge_tool(
            cancer_type=search_cancer_type,
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
        """Core prescreen + deep analysis logic. Returns analyses dict.

        Pipeline:
        1. Deterministic pre-filter (cancer type + biomarker alignment) drops mismatches.
        2. Deterministic ranker (rules + BM25) orders candidates — replaces dict
           insertion order which depends on httpx race timing.
        3. LLM prescreen (tool_use, temperature=0) picks HIGH/LOW from top 20.
        4. Deep criterion-level analysis on HIGH-tier (parallel).
        """
        from prompts import PRESCREEN_SYSTEM_PROMPT, PRESCREEN_USER_PROMPT
        from tools.deterministic_rank import rank_candidates
        from tools.trial_classifier import (
            classify_interventions,
            is_biomarker_aligned,
            is_radiation_or_observational_only,
            patient_actionable_genes,
        )

        analyses: dict = {}
        if not pool:
            return analyses

        # --- Stage 0: deterministic pre-filter (drop hard mismatches) ---
        genes = patient_actionable_genes(patient.biomarkers or [])
        filtered: list[dict] = []
        for trial in pool.values():
            # Biomarker–therapy alignment hard filter for actionable patients
            if genes and settings.enable_biomarker_alignment_cap:
                itypes = classify_interventions(trial)
                aligned, _ = is_biomarker_aligned(trial, genes)
                if is_radiation_or_observational_only(itypes) and not aligned:
                    logger.info(
                        "match.pre_filtered_biomarker_mismatch",
                        nct_id=trial.get("nct_id"),
                        itypes=sorted(itypes),
                        genes=sorted(genes),
                    )
                    analyses[trial["nct_id"]] = {
                        "match_score": 0,
                        "match_tier": "EXCLUDED",
                        "match_explanation": (
                            f"Trial does not target patient's actionable biomarkers ({', '.join(sorted(genes))})."
                        ),
                        "inclusion_evaluations": [],
                        "exclusion_evaluations": [],
                        "flags_for_oncologist": [],
                        "criteria_met": 0,
                        "criteria_not_met": 0,
                        "criteria_unknown": 0,
                        "criteria_total": 0,
                    }
                    continue
            filtered.append(trial)

        if not filtered:
            return analyses

        # --- Stage 1: deterministic ranking (replaces dict iteration order) ---
        if settings.enable_deterministic_pre_filter:
            ranked = rank_candidates(patient, filtered, genes)
            ordered_ids = [t["nct_id"] for t, _, _ in ranked]
        else:
            ordered_ids = [t["nct_id"] for t in filtered]

        MAX_PRESCREEN = settings.deterministic_prefilter_top_k
        unanalyzed = {nid: pool[nid] for nid in ordered_ids[:MAX_PRESCREEN] if nid in pool}

        # --- Stage 2: pick trials for deep analysis ---
        # When deterministic ranking is on, the ranker has all the signal we need
        # (cancer type, biomarker alignment, targeted-drug boost, BM25). The LLM
        # prescreen was filtering legitimate matches based on first-line vs
        # later-line nuances that the deep analysis evaluates correctly anyway.
        # Skip the prescreen and deep-analyze the top max_deep directly.
        if settings.enable_deterministic_pre_filter:
            to_analyze = [unanalyzed[nid] for nid in ordered_ids if nid in unanalyzed][:max_deep]
            logger.info(
                "matching.deterministic_skip_prescreen",
                top_k=len(to_analyze),
                first_few=[t["nct_id"] for t in to_analyze[:5]],
            )
        else:
            # Legacy path: LLM prescreen
            trials_list_lines = []
            for nid in ordered_ids:
                if nid not in unanalyzed:
                    continue
                trial = unanalyzed[nid]
                trials_list_lines.append(
                    f"- **{trial['nct_id']}**: {trial['brief_title']}\n"
                    f"  Phase: {trial['phase']} | Conditions: {', '.join(trial.get('conditions', []))}\n"
                    f"  Summary: {trial['brief_summary'][:200]}"
                )

            patient_vars = format_patient_for_prompt(patient)
            prescreen_sys = PRESCREEN_SYSTEM_PROMPT.format(**patient_vars)
            prescreen_user = PRESCREEN_USER_PROMPT.format(trials_list="\n".join(trials_list_lines))

            rankings, high_tier_ids = await self._run_prescreen(
                prescreen_sys, prescreen_user, list(unanalyzed.keys()), max_deep
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

            MIN_DEEP_ANALYZE = 8
            if len(high_tier_ids) < MIN_DEEP_ANALYZE:
                for nct_id in ordered_ids:
                    if nct_id not in high_tier_ids and nct_id in unanalyzed and nct_id not in analyses:
                        high_tier_ids.append(nct_id)
                    if len(high_tier_ids) >= MIN_DEEP_ANALYZE:
                        break

            if not high_tier_ids:
                return analyses

            high_set = set(high_tier_ids)
            to_analyze = [unanalyzed[nid] for nid in ordered_ids if nid in high_set and nid in unanalyzed][:max_deep]

        if not to_analyze:
            return analyses

        # --- Stage 3: Deep analysis on selected trials ---
        # Build system prompt ONCE for all trials (prompt caching)
        sys_prompt = self._build_eligibility_system_prompt(patient, biomarker_context)

        async def analyze_one(trial: dict) -> tuple[str, dict | None]:
            result = await self._analyze_single_trial(
                patient, trial, settings, biomarker_context, system_prompt=sys_prompt
            )
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

        from tools.trial_classifier import canonical_search_term

        patient = scratchpad.state["patient"]
        params = decision.params
        # Normalize cancer_type to canonical form for ClinicalTrials.gov search
        raw_cond = params.get("query_cond", patient.cancer_type)
        result = await search_and_merge_tool(
            cancer_type=canonical_search_term(raw_cond),
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
        """Handle analyze_batch — deterministic pre-filter + two-tier analysis.

        1. Pre-filter biomarker mismatches deterministically.
        2. Rank survivors with deterministic ranker (rules + BM25).
        3. LLM prescreen on top 20 in deterministic order.
        4. Deep criterion-level analysis on HIGH-tier (parallel).
        """
        from prompts import PRESCREEN_SYSTEM_PROMPT, PRESCREEN_USER_PROMPT
        from tools.deterministic_rank import rank_candidates
        from tools.trial_classifier import (
            classify_interventions,
            is_biomarker_aligned,
            is_radiation_or_observational_only,
            patient_actionable_genes,
        )

        pool = scratchpad.state["trials_pool"]
        analyses = scratchpad.state["analyses"]
        patient = scratchpad.state["patient"]
        settings = scratchpad.state["settings"]

        # Find unanalyzed trials
        unanalyzed_raw = {nct_id: trial for nct_id, trial in pool.items() if nct_id not in analyses}
        if not unanalyzed_raw:
            return "No unanalyzed trials in pool", False

        # --- Stage 0: deterministic pre-filter (drop hard mismatches) ---
        genes = patient_actionable_genes(patient.biomarkers or [])
        survivors: list[dict] = []
        pre_filtered = 0
        for trial in unanalyzed_raw.values():
            if genes and settings.enable_biomarker_alignment_cap:
                itypes = classify_interventions(trial)
                aligned, _ = is_biomarker_aligned(trial, genes)
                if is_radiation_or_observational_only(itypes) and not aligned:
                    pre_filtered += 1
                    analyses[trial["nct_id"]] = {
                        "match_score": 0,
                        "match_tier": "EXCLUDED",
                        "match_explanation": (
                            f"Trial does not target patient's actionable biomarkers ({', '.join(sorted(genes))})."
                        ),
                        "inclusion_evaluations": [],
                        "exclusion_evaluations": [],
                        "flags_for_oncologist": [],
                        "criteria_met": 0,
                        "criteria_not_met": 0,
                        "criteria_unknown": 0,
                        "criteria_total": 0,
                    }
                    continue
            survivors.append(trial)

        if pre_filtered:
            logger.info("match.batch_pre_filtered", count=pre_filtered, genes=sorted(genes))

        if not survivors:
            return f"Pre-filtered all {pre_filtered} trials (biomarker mismatch)", True

        # --- Stage 1: deterministic ranking ---
        if settings.enable_deterministic_pre_filter:
            ranked = rank_candidates(patient, survivors, genes)
            ordered_ids = [t["nct_id"] for t, _, _ in ranked]
        else:
            ordered_ids = [t["nct_id"] for t in survivors]

        MAX_PRESCREEN = settings.deterministic_prefilter_top_k
        unanalyzed = {nid: pool[nid] for nid in ordered_ids[:MAX_PRESCREEN] if nid in pool}

        # --- Stage 2: LLM prescreen in deterministic order ---
        trials_list_lines = []
        for nid in ordered_ids:
            if nid not in unanalyzed:
                continue
            trial = unanalyzed[nid]
            trials_list_lines.append(
                f"- **{trial['nct_id']}**: {trial['brief_title']}\n"
                f"  Phase: {trial['phase']} | Conditions: {', '.join(trial.get('conditions', []))}\n"
                f"  Summary: {trial['brief_summary'][:150]}"
            )

        patient_vars = format_patient_for_prompt(patient)
        prescreen_sys = PRESCREEN_SYSTEM_PROMPT.format(**patient_vars)
        prescreen_user = PRESCREEN_USER_PROMPT.format(trials_list="\n".join(trials_list_lines))

        rankings, high_tier_ids = await self._run_prescreen(prescreen_sys, prescreen_user, list(unanalyzed.keys()), 10)
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

        # --- Stage 3: Deep criterion-level analysis on HIGH-tier only ---
        max_deep = min(len(high_tier_ids), budget.analyses_remaining, 10)
        # Stable order: iterate ordered_ids, keep only HIGH set
        high_set = set(high_tier_ids)
        to_analyze = [unanalyzed[nid] for nid in ordered_ids if nid in high_set and nid in unanalyzed][:max_deep]

        biomarker_context = scratchpad.state.get("biomarker_context", "")

        # Build system prompt ONCE for all trials (prompt caching)
        sys_prompt = self._build_eligibility_system_prompt(patient, biomarker_context)

        async def analyze_one(trial: dict) -> tuple[str, dict | None]:
            result = await self._analyze_single_trial(
                patient, trial, settings, biomarker_context, system_prompt=sys_prompt
            )
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

    async def _run_prescreen(
        self,
        system_prompt: str,
        user_prompt: str,
        all_nct_ids: list[str],
        max_deep: int,
    ) -> tuple[list[dict], list[str]]:
        """Run prescreen using tool_use for deterministic structured output.

        Returns (rankings, high_tier_ids). Uses Anthropic tool_use instead of
        free-form JSON — Claude must call the tool with the exact schema,
        producing more consistent outputs across runs.
        """
        prescreen_tool = {
            "name": "submit_rankings",
            "description": "Submit the trial relevance rankings.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "rankings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "nct_id": {"type": "string"},
                                "tier": {"type": "string", "enum": ["HIGH", "LOW"]},
                                "reason": {"type": "string", "description": "5 words max"},
                            },
                            "required": ["nct_id", "tier", "reason"],
                        },
                    }
                },
                "required": ["rankings"],
            },
        }

        try:
            response = await paced_claude_call(
                get_claude_client(),
                model=get_settings().claude_model,
                max_tokens=1200,
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt,
                tools=[prescreen_tool],
                temperature=0.0,
            )

            # Extract tool_use result
            rankings = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "submit_rankings":
                    rankings = block.input.get("rankings", [])
                    break

            if not rankings:
                # Fallback: try parsing text response as JSON
                for block in response.content:
                    if block.type == "text":
                        parsed = parse_json_response(block.text)
                        if parsed:
                            rankings = parsed.get("rankings", [])
                            break

            high_tier_ids = [r["nct_id"] for r in rankings if r.get("tier") == "HIGH"]
            logger.info(
                "matching.prescreen",
                total=len(rankings),
                high=len(high_tier_ids),
                low=len(rankings) - len(high_tier_ids),
            )
            return rankings, high_tier_ids

        except Exception as e:
            logger.warning("matching.prescreen_failed", error=str(e))
            return [], list(all_nct_ids)[:max_deep]

    def _build_eligibility_system_prompt(self, patient: PatientProfile, biomarker_context: str = "") -> list[dict]:
        """Build the two-tier cacheable system prompt for eligibility analysis.

        Returns a list of two text blocks:
          1. Static rules + drug/biomarker glossary — identical across all
             patients. Anthropic caches this after the first call of the day.
          2. Per-patient profile + enriched biomarker context — identical
             across all trials in this patient's run.

        ``call_claude_with_retry`` applies a ``cache_control`` breakpoint to
        each block, giving us two-tier caching: rules reused across every
        patient, patient context reused across every trial in this run.
        """
        from prompts import ELIGIBILITY_PATIENT_PROMPT, ELIGIBILITY_RULES_PROMPT

        patient_vars = format_patient_for_prompt(patient)
        enriched = ""
        if biomarker_context:
            enriched = f"## Enriched Biomarker Context\n{biomarker_context}"
        patient_block = ELIGIBILITY_PATIENT_PROMPT.format(**patient_vars, enriched_context=enriched)
        return [
            {"type": "text", "text": ELIGIBILITY_RULES_PROMPT},
            {"type": "text", "text": patient_block},
        ]

    async def _analyze_single_trial(
        self,
        patient: PatientProfile,
        trial: dict,
        settings,
        biomarker_context: str = "",
        system_prompt: str | list[dict] | None = None,
    ) -> dict | None:
        """Analyze a single trial's eligibility using criterion-level decomposition.

        Pipeline: parse criteria → evaluate per-criterion → score programmatically.
        When system_prompt is provided, uses it for prompt caching (shared across batch).
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
        # When system_prompt is provided (batch mode), use split prompt for caching.
        # The system prompt (patient + rules) is cached by Anthropic after the first call.
        if system_prompt:
            from prompts import ELIGIBILITY_USER_PROMPT

            user_msg = ELIGIBILITY_USER_PROMPT.format(
                nct_id=nct_id,
                brief_title=trial["brief_title"],
                phase=trial["phase"],
                brief_summary=trial["brief_summary"],
                parsed_criteria=parsed_criteria_text,
            )
        else:
            # Fallback: combined prompt (no caching)
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
            user_msg = prompt_result.data

        # Compact output schema (Session 4): each criterion evaluation is
        # ~30-50 tokens (id, status, confidence, reason). 15 criteria fits in
        # ~1200 tokens. We pad to 1500 to give Claude headroom for unusually
        # long reasoning. Was up to 4000 before — that was sized for the
        # bloated schema that repeated criterion_text in every entry.
        analysis_max_tokens = min(1800, max(1000, len(criteria_lines) * 80))

        # Build the parsed-criteria lookup once. Used to hydrate the compact
        # Claude response with the original criterion text and inclusion/
        # exclusion type, and to merge in the parser's category tag for
        # downstream scoring.
        parsed_by_id = {}
        for c in parsed["inclusion_criteria"]:
            parsed_by_id[c["id"]] = {**c, "type": "inclusion"}
        for c in parsed["exclusion_criteria"]:
            parsed_by_id[c["id"]] = {**c, "type": "exclusion"}

        for attempt in range(settings.max_retries + 1):
            try:
                response = await paced_claude_call(
                    get_claude_client(),
                    model=settings.claude_model,
                    max_tokens=analysis_max_tokens,
                    messages=[{"role": "user", "content": user_msg}],
                    system=system_prompt,
                    temperature=0.0,
                )
                text = response.content[0].text.strip()
                result = parse_json_response(text)
                if result is None:
                    logger.warning("analysis.parse_failed", nct_id=nct_id, attempt=attempt + 1, text_preview=text[:200])
                    if attempt < settings.max_retries:
                        continue
                    return None

                # Step 3: Hydrate compact Claude response with parser data,
                # then score programmatically. The compact schema only carries
                # id/status/confidence/reason — we look up text/type/category
                # from parsed_by_id using the id.
                compact_evals = result.get("evals") or result.get("criterion_evaluations") or []
                if not compact_evals:
                    logger.warning("analysis.no_evals", nct_id=nct_id, attempt=attempt + 1, keys=list(result.keys()))
                    if attempt < settings.max_retries:
                        continue
                    return None

                evals = []
                for ev in compact_evals:
                    cid = ev.get("id") or ev.get("criterion_id") or ""
                    parsed_c = parsed_by_id.get(cid)
                    if parsed_c is None:
                        # Claude hallucinated an id we don't recognize — skip.
                        logger.warning("analysis.unknown_criterion_id", nct_id=nct_id, id=cid)
                        continue
                    evals.append(
                        {
                            "criterion_id": cid,
                            "criterion_text": parsed_c.get("text", ""),
                            "type": parsed_c.get("type", "inclusion"),
                            "category": parsed_c.get("category", "other"),
                            "status": ev.get("status", "INSUFFICIENT_INFO"),
                            "confidence": ev.get("confidence", "MEDIUM"),
                            "reasoning": ev.get("reason") or ev.get("reasoning") or "",
                            "patient_data_used": [],
                        }
                    )

                if not evals:
                    logger.warning("analysis.no_valid_evals", nct_id=nct_id, attempt=attempt + 1)
                    if attempt < settings.max_retries:
                        continue
                    return None

                flags = result.get("flags") or result.get("flags_for_oncologist") or []
                # Pass biomarker context to scoring for the −30 penalty + hard cap
                from tools.trial_classifier import (
                    classify_interventions as _classify,
                )
                from tools.trial_classifier import (
                    is_biomarker_aligned as _is_aligned,
                )
                from tools.trial_classifier import (
                    patient_actionable_genes as _genes,
                )

                _patient_genes = _genes(patient.biomarkers or [])
                _itypes = _classify(trial)
                _aligned, _ = _is_aligned(trial, _patient_genes)
                score_result = calculate_match_score(
                    evals,
                    flags,
                    biomarker_aligned=_aligned,
                    intervention_types=_itypes,
                    has_actionable_genes=bool(_patient_genes),
                )
                logger.info("analysis.scored", nct_id=nct_id, score=score_result["score"], tier=score_result["tier"])

                inclusion_evals = [e for e in evals if e["type"] == "inclusion"]
                exclusion_evals = [e for e in evals if e["type"] == "exclusion"]

                return {
                    "match_score": score_result["score"],
                    "match_tier": score_result["tier"],
                    "match_explanation": score_result["match_explanation"],
                    "inclusion_evaluations": [
                        {
                            "criterion": e["criterion_text"],
                            "criterion_id": e["criterion_id"],
                            "type": "inclusion",
                            "status": e["status"],
                            "confidence": e["confidence"],
                            "explanation": e["reasoning"],
                            "patient_data_used": [],
                        }
                        for e in inclusion_evals
                    ],
                    "exclusion_evaluations": [
                        {
                            "criterion": e["criterion_text"],
                            "criterion_id": e["criterion_id"],
                            "type": "exclusion",
                            "status": e["status"],
                            "confidence": e["confidence"],
                            "explanation": e["reasoning"],
                            "patient_data_used": [],
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

        # Stable tiebreaker: highest score first, then nct_id ascending
        matches.sort(key=lambda m: (-m.match_score, m.nct_id))
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
        result = await claude_text_call(prompt_result.data, model=get_settings().summary_model)
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
            from sqlalchemy import select

            from database import async_session
            from db_models import StructuredCriteriaDB
            from semantic_recall import text_hash

            elig_hash = text_hash(eligibility_text)

            async with async_session() as session:
                stmt = (
                    select(StructuredCriteriaDB.criteria_json)
                    .where(
                        StructuredCriteriaDB.eligibility_text_hash == elig_hash,
                    )
                    .limit(1)
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()

            if not row:
                return None

            # Convert cached criteria list to parse_eligibility_criteria shape
            criteria = row if isinstance(row, list) else row.get("criteria", [])
            inclusion = [c for c in criteria if c.get("type") == "inclusion"]
            exclusion = [c for c in criteria if c.get("type") == "exclusion"]
            return {
                "inclusion_criteria": inclusion,
                "exclusion_criteria": exclusion,
                "total_criteria": len(criteria),
            }
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

        patient = await load_patient_from_db(ctx.patient_id, session=ctx.db_session)
        patient_dict = patient.model_dump()

        settings = get_settings()
        nct_id = inputs.nct_id
        match = inputs.match

        trial_summary = f"- {nct_id}: {match.get('brief_title', '?')[:60]} (score: {match.get('match_score', '?')})"

        scratchpad = Scratchpad(
            state={
                "patient_data": patient_dict,
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
                "patient_json": json.dumps(patient_dict, indent=2),
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

        # Two-tier dossier caching (Session 4): rules block (with shared
        # drug/biomarker glossary) is cached cross-patient; patient block is
        # cached cross-trial; only the trial-specific user message is fresh.
        from prompts import DOSSIER_PATIENT_PROMPT, DOSSIER_RULES_PROMPT, DOSSIER_USER_PROMPT
        from tools.criteria_parser import parse_eligibility_criteria

        # Session 5: compact dossier output schema. Parse criteria into a
        # numbered list so Claude can reference them by id instead of
        # restating the full text in every evaluation entry. Hydrated back
        # to the legacy criteria_analysis shape after the call.
        eligibility_text = match.get("eligibility_criteria", "") or ""
        if len(eligibility_text) > 6000:
            eligibility_text = eligibility_text[:6000] + "\n\n[Eligibility text truncated]"
        parse_result = parse_eligibility_criteria(eligibility_text)
        if not parse_result.success or parse_result.data["total_criteria"] == 0:
            parsed_by_id: dict = {}
            parsed_criteria_text = eligibility_text or "Not available"
        else:
            parsed = parse_result.data
            parsed_by_id = {}
            for c in parsed["inclusion_criteria"]:
                parsed_by_id[c["id"]] = {**c, "type": "inclusion"}
            for c in parsed["exclusion_criteria"]:
                parsed_by_id[c["id"]] = {**c, "type": "exclusion"}
            lines = []
            for c in parsed["inclusion_criteria"]:
                lines.append(f"[{c['id']}] INCLUSION ({c['category']}): {c['text']}")
            for c in parsed["exclusion_criteria"]:
                lines.append(f"[{c['id']}] EXCLUSION ({c['category']}): {c['text']}")
            parsed_criteria_text = "\n".join(lines)

        patient_block = DOSSIER_PATIENT_PROMPT.format(patient_json=json.dumps(patient_data, indent=2))
        system_blocks = [
            {"type": "text", "text": DOSSIER_RULES_PROMPT},
            {"type": "text", "text": patient_block},
        ]
        user_msg = DOSSIER_USER_PROMPT.format(
            nct_id=nct_id,
            brief_title=match["brief_title"],
            parsed_criteria=parsed_criteria_text,
            initial_score=match.get("match_score", 0),
            initial_explanation=match.get("match_explanation", ""),
        )

        result = await claude_json_call(
            user_msg,
            model=settings.dossier_model,
            max_tokens=settings.dossier_max_tokens,
            system=system_blocks,
        )

        analysis = result.data if result.success else None
        if analysis is not None and parsed_by_id:
            compact_evals = analysis.pop("evals", None) or analysis.get("criteria_analysis") or []
            hydrated = []
            for ev in compact_evals:
                cid = ev.get("id") or ev.get("criterion_id") or ""
                parsed_c = parsed_by_id.get(cid)
                if parsed_c is None:
                    if ev.get("criterion"):
                        hydrated.append(ev)
                    continue
                hydrated.append(
                    {
                        "criterion": parsed_c.get("text", ""),
                        "type": parsed_c.get("type", "inclusion"),
                        "status": ev.get("status", "unknown"),
                        "evidence": ev.get("evidence", ""),
                        "notes": ev.get("notes", ""),
                    }
                )
            analysis["criteria_analysis"] = hydrated

        section = build_dossier_section(match, analysis)
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
    """Enrollment packet assembler.

    The three artifacts (packet, prep guide, outreach draft) have no data
    dependency on each other beyond the shared patient/site inputs, so we
    bypass the ReAct agent loop and run them in one parallel burst. Wall
    clock drops from ~6s (3 sequential Sonnet calls + planning turns) to
    ~2s (3 parallel Sonnet calls).

    Workflow: workflows/enrollment.md
    """

    agent_type: ClassVar[str] = "enrollment"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            inputs = EnrollmentInput(**ctx.input_data)
        except Exception as e:
            return AgentResult(success=False, error=f"Invalid input: {e}")

        patient = await load_patient_from_db(ctx.patient_id, session=ctx.db_session)
        patient_dict = patient.model_dump()

        dossier = inputs.dossier
        trial_nct_id = inputs.trial_nct_id
        section = next((s for s in dossier.get("sections", []) if s.get("nct_id") == trial_nct_id), None)
        if not section:
            return AgentResult(success=False, error=f"No dossier section found for {trial_nct_id}")

        # Step 1: fetch site info (single sequential call — cheap HTTP).
        await ctx.emit("enrollment.fetch_site_start", {"nct_id": trial_nct_id})
        nearest_site = await self._fetch_nearest_site(trial_nct_id)
        await ctx.emit("enrollment.fetch_site_complete", {"has_site": bool(nearest_site)})

        # Step 2: derive a minimal screening checklist from the dossier's
        # criteria analysis so the prep guide does not need to wait on the
        # packet generation. This decouples the three artifacts.
        criteria_analysis = section.get("criteria_analysis", [])[:10]
        derived_checklist = [
            {
                "item": c.get("criterion", ""),
                "category": "records",
                "status": "needed",
                "notes": c.get("evidence", ""),
            }
            for c in criteria_analysis
            if c.get("criterion")
        ]

        # Step 3: run packet, prep guide, and outreach concurrently.
        await ctx.emit("enrollment.generation_start", {"handlers": ["packet", "prep", "outreach"]})
        packet_task = self._generate_packet(patient_dict, section, trial_nct_id)
        prep_task = self._generate_prep(patient_dict, section, nearest_site, derived_checklist)
        outreach_task = self._generate_outreach(section, dossier, nearest_site, trial_nct_id)
        packet, prep, outreach = await asyncio.gather(packet_task, prep_task, outreach_task)
        await ctx.emit(
            "enrollment.generation_complete",
            {
                "packet_ok": packet is not None,
                "prep_ok": prep is not None,
                "outreach_ok": outreach is not None,
            },
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

    async def _fetch_nearest_site(self, nct_id: str) -> dict:
        """Fetch the trial's first location, or an empty dict on failure."""
        try:
            result = await fetch_trial_tool(nct_id=nct_id)
        except Exception as e:
            logger.warning("enrollment.fetch_site_error", nct_id=nct_id, error=str(e))
            return {}
        if not result.success or not result.data:
            return {}
        locations = result.data.get("locations") or []
        return locations[0] if locations else {}

    async def _generate_packet(self, patient_dict: dict, section: dict, trial_nct_id: str) -> dict | None:
        prompt_result = render_prompt(
            prompt_name="enrollment_packet",
            patient_json=json.dumps(patient_dict, indent=2),
            nct_id=trial_nct_id,
            brief_title=section.get("brief_title", ""),
            revised_score=section.get("revised_score", "?"),
            clinical_summary=section.get("clinical_summary", ""),
            criteria_json=json.dumps(section.get("criteria_analysis", [])[:10], indent=2),
        )
        if not prompt_result.success:
            logger.warning("enrollment.packet_prompt_failed", error=prompt_result.error)
            return None
        result = await claude_json_call(prompt_result.data)
        return result.data if result.success else None

    async def _generate_prep(
        self,
        patient_dict: dict,
        section: dict,
        site: dict,
        derived_checklist: list[dict],
    ) -> dict | None:
        prompt_result = render_prompt(
            prompt_name="patient_prep",
            cancer_type=patient_dict.get("cancer_type", ""),
            cancer_stage=patient_dict.get("cancer_stage", ""),
            age=patient_dict.get("age", ""),
            brief_title=section.get("brief_title", ""),
            site_name=site.get("facility", "Trial site"),
            site_city=site.get("city", ""),
            site_state=site.get("state", ""),
            screening_checklist=json.dumps(derived_checklist, indent=2),
        )
        if not prompt_result.success:
            logger.warning("enrollment.prep_prompt_failed", error=prompt_result.error)
            return None
        result = await claude_json_call(prompt_result.data)
        return result.data if result.success else None

    async def _generate_outreach(
        self,
        section: dict,
        dossier: dict,
        site: dict,
        trial_nct_id: str,
    ) -> dict | None:
        contact_name = "Research Coordinator"
        if site.get("contacts"):
            contact_name = site["contacts"][0].get("name", "Research Coordinator")

        prompt_result = render_prompt(
            prompt_name="outreach_message",
            nct_id=trial_nct_id,
            brief_title=section.get("brief_title", ""),
            site_name=site.get("facility", "Trial site"),
            site_city=site.get("city", ""),
            site_state=site.get("state", ""),
            contact_name=contact_name,
            patient_summary=section.get("clinical_summary", dossier.get("patient_summary", "")),
            match_score=section.get("revised_score", "?"),
            match_rationale=section.get("score_justification", ""),
        )
        if not prompt_result.success:
            logger.warning("enrollment.outreach_prompt_failed", error=prompt_result.error)
            return None
        result = await claude_json_call(prompt_result.data)
        return result.data if result.success else None


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
            model=get_settings().outreach_model,
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
