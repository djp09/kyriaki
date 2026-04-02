"""Adaptive agent execution loop — ReAct (Reason-Act-Observe) pattern.

The core execution engine for all agents. Each agent provides:
- An orchestrator prompt (domain-specific strategy)
- An action handler (maps decisions to tool calls)
- A result builder (assembles final output from scratchpad)

The loop handles planning, budget enforcement, and error recovery.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from config import get_settings
from logging_config import get_logger
from tools.claude_api import claude_json_call

logger = get_logger("kyriaki.agent_loop")


@dataclass
class ScratchpadEntry:
    """A single step in the agent's reasoning history."""

    iteration: int
    action: str
    reasoning: str
    params: dict
    result_summary: str
    success: bool


@dataclass
class Scratchpad:
    """Accumulates the agent's observations across iterations."""

    entries: list[ScratchpadEntry] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)  # Agent-specific accumulated state

    def add(self, iteration: int, action: str, reasoning: str, params: dict, result_summary: str, success: bool):
        self.entries.append(ScratchpadEntry(iteration, action, reasoning, params, result_summary, success))

    def format_for_prompt(self) -> str:
        if not self.entries:
            return "No actions taken yet. This is iteration 1."
        lines = []
        for e in self.entries:
            status = "OK" if e.success else "FAILED"
            lines.append(f"Step {e.iteration}: [{status}] {e.action}({e.params}) → {e.result_summary}")
            lines.append(f"  Reasoning: {e.reasoning}")
        return "\n".join(lines)


@dataclass
class AgentBudget:
    """Resource limits for the agent loop."""

    max_iterations: int = 5
    max_search_calls: int = 3
    max_analysis_calls: int = 20
    iterations_used: int = 0
    search_calls_used: int = 0
    analysis_calls_used: int = 0

    @property
    def iterations_remaining(self) -> int:
        return self.max_iterations - self.iterations_used

    @property
    def searches_remaining(self) -> int:
        return self.max_search_calls - self.search_calls_used

    @property
    def analyses_remaining(self) -> int:
        return self.max_analysis_calls - self.analysis_calls_used

    @property
    def exhausted(self) -> bool:
        return self.iterations_used >= self.max_iterations


@dataclass
class AgentDecision:
    """What the agent decided to do next."""

    action: str
    reasoning: str
    params: dict[str, Any]


# Type alias for action handlers
ActionHandler = Callable[
    [AgentDecision, Scratchpad, "AgentBudget"],
    Coroutine[Any, Any, tuple[str, bool]],  # (result_summary, success)
]


async def run_agent_loop(
    *,
    orchestrator_prompt_template: str,
    prompt_vars: dict[str, Any],
    action_handlers: dict[str, ActionHandler],
    scratchpad: Scratchpad | None = None,
    budget: AgentBudget | None = None,
    emit: Callable | None = None,
    valid_actions: list[str] | None = None,
) -> Scratchpad:
    """Run the adaptive ReAct loop.

    Args:
        orchestrator_prompt_template: The prompt template with {scratchpad},
            {iterations_remaining}, etc. placeholders.
        prompt_vars: Static variables for the prompt (patient profile, etc.)
        action_handlers: Map of action name → async handler function.
            Each handler receives (decision, scratchpad, budget) and returns
            (result_summary, success).
        scratchpad: Optional pre-populated scratchpad (for resumption).
        budget: Resource limits. Defaults from config.
        emit: Optional event emitter for progress updates.
        valid_actions: If provided, restrict decisions to these actions.

    Returns:
        The final scratchpad with all observations.
    """
    settings = get_settings()
    if scratchpad is None:
        scratchpad = Scratchpad()
    if budget is None:
        budget = AgentBudget(
            max_iterations=settings.agent_max_iterations,
            max_search_calls=settings.agent_max_search_calls,
            max_analysis_calls=settings.agent_max_analysis_calls,
        )

    for iteration in range(budget.max_iterations):
        budget.iterations_used = iteration + 1

        # 1. PLAN: Ask Claude what to do next
        decision = await _get_next_action(orchestrator_prompt_template, prompt_vars, scratchpad, budget)

        # Validate action
        all_valid = list(action_handlers.keys()) + ["finish"]
        if valid_actions:
            all_valid = valid_actions + ["finish"]
        if decision.action not in all_valid:
            logger.warning(
                "agent.invalid_action",
                action=decision.action,
                valid=all_valid,
                iteration=iteration,
            )
            decision = AgentDecision(action="finish", reasoning="Invalid action, stopping", params={})

        logger.info(
            "agent.decision",
            iteration=iteration,
            action=decision.action,
            reasoning=decision.reasoning[:100],
        )

        if emit:
            await emit(
                "progress",
                {
                    "step": f"agent_{decision.action}",
                    "iteration": iteration + 1,
                    "reasoning": decision.reasoning,
                },
            )

        # 2. CHECK: If agent said "finish", record and break
        if decision.action == "finish":
            scratchpad.add(iteration, "finish", decision.reasoning, decision.params, "Agent decided to stop.", True)
            break

        # 3. ACT: Execute the chosen action
        handler = action_handlers.get(decision.action)
        if handler is None:
            scratchpad.add(
                iteration,
                decision.action,
                decision.reasoning,
                decision.params,
                f"No handler for action '{decision.action}'",
                False,
            )
            continue

        try:
            result_summary, success = await handler(decision, scratchpad, budget)
        except Exception as e:
            result_summary = f"Error: {type(e).__name__}: {e}"
            success = False
            logger.error("agent.action_error", action=decision.action, error=result_summary, iteration=iteration)

        # 4. OBSERVE: Record results
        scratchpad.add(iteration, decision.action, decision.reasoning, decision.params, result_summary, success)

        # 5. BUDGET CHECK
        if budget.exhausted:
            logger.info("agent.budget_exhausted", iteration=iteration)
            scratchpad.add(iteration + 1, "finish", "Budget exhausted", {}, "Forced stop — budget limit reached.", True)
            break

    return scratchpad


async def _get_next_action(
    prompt_template: str,
    prompt_vars: dict[str, Any],
    scratchpad: Scratchpad,
    budget: AgentBudget,
) -> AgentDecision:
    """Ask Claude to decide the next action."""
    full_vars = {
        **prompt_vars,
        "scratchpad": scratchpad.format_for_prompt(),
        "iterations_remaining": budget.iterations_remaining,
        "max_iterations": budget.max_iterations,
        "searches_remaining": budget.searches_remaining,
        "max_searches": budget.max_search_calls,
        "analyses_remaining": budget.analyses_remaining,
        "max_analyses": budget.max_analysis_calls,
        "analyses_done": budget.analysis_calls_used,
    }

    # Render the prompt, handling missing vars gracefully
    try:
        prompt = prompt_template.format(**full_vars)
    except KeyError as e:
        logger.error("agent.prompt_render_failed", missing_key=str(e))
        return AgentDecision(action="finish", reasoning=f"Prompt render failed: {e}", params={})

    result = await claude_json_call(prompt, max_tokens=500)
    if not result.success:
        logger.warning("agent.planning_failed", error=result.error)
        return AgentDecision(action="finish", reasoning=f"Planning call failed: {result.error}", params={})

    data = result.data
    return AgentDecision(
        action=data.get("action", "finish"),
        reasoning=data.get("reasoning", "No reasoning provided"),
        params=data.get("params", {}),
    )
