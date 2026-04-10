"""Tool: Claude API interaction.

Handles all Claude API calls with retry logic, rate-limit pacing,
JSON response parsing, and truncated-JSON repair.

This is the single place where Claude SDK calls happen.
"""

from __future__ import annotations

import asyncio
import json
import re

import anthropic

from config import get_settings
from logging_config import get_logger
from phi.boundary import to_external_llm
from tools import TokenUsage, ToolResult, ToolSpec, register_tool

logger = get_logger("kyriaki.tools.claude_api")


# --- Client ---


def get_claude_client() -> anthropic.AsyncAnthropic:
    """Create an async Anthropic client using configured API key."""
    settings = get_settings()
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


# --- Retry + pacing ---


async def call_claude_with_retry(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    max_tokens: int,
    messages: list,
    max_retries: int = 3,
    tools: list | None = None,
    allow_binary: bool = False,
    system: str | list[dict] | None = None,
    temperature: float | None = None,
) -> anthropic.types.Message:
    """Call Claude with exponential backoff on rate limits.

    All outgoing payloads are routed through ``phi.boundary.to_external_llm``
    which enforces HIPAA Safe Harbor de-identification. See ADR-004.

    When *system* is provided it is sent as the ``system`` parameter to the
    Anthropic API with ``cache_control: {"type": "ephemeral"}`` on the last
    block, enabling prompt caching for repeated calls that share the same
    system prompt.
    """
    payload = to_external_llm(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        tools=tools,
        allow_binary=allow_binary,
        system=system,
    )
    if payload.redaction_report:
        logger.info("phi.boundary.redacted", **payload.redaction_report)

    # Apply cache_control to the last system block for Anthropic prompt caching
    system_blocks = None
    if payload.system:
        system_blocks = [dict(b) for b in payload.system]
        system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

    for attempt in range(max_retries):
        try:
            create_kwargs = {
                "model": payload.model,
                "max_tokens": payload.max_tokens,
                "messages": payload.messages,
            }
            if temperature is not None:
                create_kwargs["temperature"] = temperature
            if payload.tools:
                create_kwargs["tools"] = payload.tools
            if system_blocks:
                create_kwargs["system"] = system_blocks
            return await client.messages.create(**create_kwargs)
        except anthropic.RateLimitError:
            if attempt == max_retries - 1:
                raise
            wait_time = 2**attempt * 2
            logger.warning("claude.rate_limited", attempt=attempt + 1, max_retries=max_retries, wait_s=wait_time)
            await asyncio.sleep(wait_time)
        except anthropic.APIStatusError as e:
            if e.status_code == 429:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2**attempt * 2
                logger.warning("claude.rate_limited", attempt=attempt + 1, max_retries=max_retries, wait_s=wait_time)
                await asyncio.sleep(wait_time)
            else:
                raise
    raise RuntimeError("Exhausted retries without success or exception")


class AdaptiveConcurrencyLimiter:
    """Dynamically adjusts concurrency based on rate-limit feedback.

    Starts at max_concurrent, backs off on 429s, ramps up on sustained success.
    """

    def __init__(self, max_concurrent: int = 10, min_concurrent: int = 1):
        self._max = max_concurrent
        self._min = min_concurrent
        self._current = max_concurrent
        self._semaphore: asyncio.Semaphore | None = None
        self._lock: asyncio.Lock | None = None
        self._consecutive_success = 0
        self._ramp_up_threshold = 5  # successful calls before increasing concurrency
        self._last_call_time: float = 0.0

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._current)
        return self._semaphore

    async def on_rate_limit(self) -> None:
        """Called when a 429 is received. Reduces concurrency."""
        async with self._get_lock():
            old = self._current
            self._current = max(self._min, self._current // 2)
            self._consecutive_success = 0
            if old != self._current:
                # Recreate semaphore with lower limit
                self._semaphore = asyncio.Semaphore(self._current)
                logger.info(
                    "adaptive.backoff",
                    old_concurrent=old,
                    new_concurrent=self._current,
                )

    async def on_success(self) -> None:
        """Called on a successful call. May ramp up concurrency."""
        async with self._get_lock():
            self._consecutive_success += 1
            if self._consecutive_success >= self._ramp_up_threshold and self._current < self._max:
                old = self._current
                self._current = min(self._max, self._current + 1)
                self._consecutive_success = 0
                self._semaphore = asyncio.Semaphore(self._current)
                logger.info(
                    "adaptive.ramp_up",
                    old_concurrent=old,
                    new_concurrent=self._current,
                )

    @property
    def current_concurrency(self) -> int:
        return self._current

    async def acquire(self) -> None:
        await self._get_semaphore().acquire()

    def release(self) -> None:
        self._get_semaphore().release()


# Module-level limiter
_limiter: AdaptiveConcurrencyLimiter | None = None


def get_limiter() -> AdaptiveConcurrencyLimiter:
    """Get or create the global adaptive concurrency limiter."""
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = AdaptiveConcurrencyLimiter(
            max_concurrent=settings.max_concurrent_analyses,
        )
    return _limiter


async def paced_claude_call(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    max_tokens: int,
    messages: list,
    tools: list | None = None,
    allow_binary: bool = False,
    system: str | list[dict] | None = None,
    temperature: float | None = None,
) -> anthropic.types.Message:
    """Call Claude with adaptive concurrency limiting.

    Automatically backs off on rate limits and ramps up on sustained success.
    All outgoing payloads are routed through the PHI boundary.
    """
    limiter = get_limiter()
    await limiter.acquire()
    try:
        result = await call_claude_with_retry(
            client,
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            tools=tools,
            allow_binary=allow_binary,
            system=system,
            temperature=temperature,
        )
        await limiter.on_success()
        return result
    except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
        if isinstance(e, anthropic.APIStatusError) and e.status_code != 429:
            raise
        await limiter.on_rate_limit()
        raise
    finally:
        limiter.release()


# --- JSON parsing ---


def repair_truncated_json(text: str) -> str | None:
    """Attempt to close unclosed braces/brackets in truncated JSON."""
    stack = []
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack and stack[-1] == ch:
            stack.pop()

    if not stack:
        return text

    truncated = text

    if in_string:
        truncated += '"'

    truncated = re.sub(r',\s*"[^"]*$', "", truncated)
    truncated = re.sub(r",\s*$", "", truncated)
    truncated = re.sub(r':\s*"[^"]*$', ': ""', truncated)
    truncated = re.sub(r":\s*$", ": null", truncated)

    for closer in reversed(stack):
        truncated += closer

    return truncated


def parse_json_response(text: str) -> dict | None:
    """Parse JSON from Claude's response text, handling markdown fences and truncation."""
    if not text:
        return None

    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace : last_brace + 1])
        except json.JSONDecodeError:
            pass

    if first_brace != -1:
        partial = text[first_brace:]
        repaired = repair_truncated_json(partial)
        if repaired is not None:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    return None


def extract_minimal_result(text: str, nct_id: str) -> dict | None:
    """Extract match_score and explanation via regex when full JSON parse fails."""
    score_match = re.search(r'"match_score"\s*:\s*(\d+)', text)
    explanation_match = re.search(r'"match_explanation"\s*:\s*"([^"]*)"', text)

    if score_match:
        return {
            "match_score": int(score_match.group(1)),
            "match_explanation": explanation_match.group(1)
            if explanation_match
            else "Analysis could not be fully parsed. Please review the trial details with your oncologist.",
            "inclusion_evaluations": [],
            "exclusion_evaluations": [],
            "flags_for_oncologist": [
                "Full eligibility analysis was incomplete — discuss all criteria with your oncologist"
            ],
        }
    return None


# --- Token extraction ---


def _extract_token_usage(response: anthropic.types.Message) -> TokenUsage:
    """Extract token usage from a Claude API response, including cache metrics."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )


# --- High-level tool functions ---


async def claude_json_call(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 1500,
    system: str | list[dict] | None = None,
    temperature: float = 0.0,
) -> ToolResult:
    """Call Claude and parse the response as JSON. Returns ToolResult with token_usage.

    Defaults to temperature=0 for deterministic structured outputs (Anthropic best practice).
    """
    settings = get_settings()
    model = model or settings.claude_model
    try:
        response = await paced_claude_call(
            get_claude_client(),
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            system=system,
            temperature=temperature,
        )
        tokens = _extract_token_usage(response)
        result = parse_json_response(response.content[0].text)
        if result is None:
            return ToolResult(success=False, error="Failed to parse JSON from Claude response", token_usage=tokens)
        return ToolResult(success=True, data=result, token_usage=tokens)
    except Exception as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


async def claude_text_call(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 300,
    system: str | list[dict] | None = None,
) -> ToolResult:
    """Call Claude and return plain text response. Returns ToolResult with token_usage."""
    settings = get_settings()
    model = model or settings.claude_model
    try:
        response = await paced_claude_call(
            get_claude_client(),
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            system=system,
        )
        tokens = _extract_token_usage(response)
        return ToolResult(success=True, data=response.content[0].text.strip(), token_usage=tokens)
    except Exception as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


async def evaluate_score(
    *,
    patient_vars: dict,
    nct_id: str,
    brief_title: str,
    eligibility_criteria: str,
    initial_score: int,
    initial_explanation: str,
    criteria_json: str,
) -> ToolResult:
    """Evaluator-optimizer: review an initial match score for errors.

    Returns ToolResult with data: {confirmed, adjusted_score, adjustment_reason, errors_found}
    """
    from tools.prompt_renderer import render_prompt

    prompt_result = render_prompt(
        prompt_name="score_evaluation",
        **patient_vars,
        nct_id=nct_id,
        brief_title=brief_title,
        eligibility_criteria=eligibility_criteria,
        initial_score=initial_score,
        initial_explanation=initial_explanation,
        criteria_json=criteria_json,
    )
    if not prompt_result.success:
        return ToolResult(success=False, error=f"Prompt render failed: {prompt_result.error}")

    result = await claude_json_call(prompt_result.data, max_tokens=500)
    if not result.success:
        return ToolResult(success=False, error=result.error, token_usage=result.token_usage)

    data = result.data
    # Ensure expected shape
    return ToolResult(
        success=True,
        data={
            "confirmed": data.get("confirmed", True),
            "adjusted_score": data.get("adjusted_score"),
            "adjustment_reason": data.get("adjustment_reason", ""),
            "errors_found": data.get("errors_found", []),
        },
        token_usage=result.token_usage,
    )


# --- Register tools with specs ---

register_tool(
    "claude_json_call",
    claude_json_call,
    ToolSpec(
        name="claude_json_call",
        description="Call Claude and parse the response as JSON.",
        parameters={
            "prompt": "The full prompt text",
            "model": "Model override (default: Sonnet)",
            "max_tokens": "Max response tokens (default: 1500)",
        },
        returns="Parsed JSON dict from Claude's response",
        edge_cases=["Returns success=False if JSON parsing fails", "Handles markdown fences and truncated JSON"],
    ),
)
register_tool(
    "claude_text_call",
    claude_text_call,
    ToolSpec(
        name="claude_text_call",
        description="Call Claude and return plain text response.",
        parameters={
            "prompt": "The full prompt text",
            "model": "Model override",
            "max_tokens": "Max tokens (default: 300)",
        },
        returns="Plain text string",
    ),
)
register_tool(
    "evaluate_score",
    evaluate_score,
    ToolSpec(
        name="evaluate_score",
        description="Re-evaluate a match score for logical errors, missed disqualifiers, and rubric mismatches.",
        parameters={
            "patient_vars": "Formatted patient profile dict",
            "nct_id": "Trial ID",
            "initial_score": "Score to review",
        },
        returns="Dict with confirmed (bool), adjusted_score, adjustment_reason, errors_found",
        edge_cases=["Only useful for borderline scores (30-70)", "Returns confirmed=True if score is correct"],
    ),
)
