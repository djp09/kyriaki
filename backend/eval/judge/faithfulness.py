"""Tier 3 LLM-judge — checks faithfulness of Stage 6 explanations.

Uses Opus to verify that match_explanation text is fully supported by
the criterion evaluations. An "unsupported claim" is any assertion in the
explanation that cannot be traced to a specific criterion evaluation.

Gate metric: unsupported_claim_rate < 2%.
"""

from __future__ import annotations

from tools.claude_api import get_claude_client, paced_claude_call, parse_json_response

JUDGE_PROMPT = """\
You are an expert auditor for a clinical trial matching system. Your job is to
check whether a patient-facing explanation is **faithful** to the underlying
criterion evaluations.

## Criterion evaluations (ground truth)

{evaluations_text}

## Explanation under review

"{explanation}"

## Task

1. List every factual claim in the explanation (a "claim" is any assertion about
   the patient's eligibility, a specific criterion, or the trial).
2. For each claim, determine whether it is **SUPPORTED** (traceable to one or
   more criterion evaluations above), **UNSUPPORTED** (not traceable — invented,
   exaggerated, or contradicted), or **BENIGN** (generic framing like "discuss
   with your oncologist" that needs no evidence).
3. Return JSON:

```json
{{
  "claims": [
    {{
      "claim_text": "...",
      "verdict": "SUPPORTED" | "UNSUPPORTED" | "BENIGN",
      "linked_criterion_id": "I1" or null,
      "reason": "brief justification"
    }}
  ],
  "total_claims": <int>,
  "unsupported_count": <int>,
  "summary": "one-line overall assessment"
}}
```

Be strict: if the explanation says "you meet the biomarker requirement" but
no criterion evaluation confirms a biomarker MET status, that is UNSUPPORTED.
"""


def _format_evaluations(evaluations: list[dict]) -> str:
    """Format criterion evaluations into readable text for the judge."""
    lines = []
    for e in evaluations:
        crit_id = e.get("criterion_id", e.get("id", "?"))
        crit_type = e.get("type", "?")
        category = e.get("category", "?")
        status = e.get("status", "?")
        confidence = e.get("confidence", "?")
        text = e.get("criterion_text", e.get("criterion", "?"))
        reasoning = e.get("reasoning", e.get("explanation", ""))
        lines.append(
            f"[{crit_id}] {crit_type.upper()} ({category}) — {status} (confidence: {confidence})\n"
            f"  Criterion: {text}\n"
            f"  Reasoning: {reasoning}"
        )
    return "\n\n".join(lines)


async def judge_explanation(
    evaluations: list[dict],
    explanation: str,
    model: str = "claude-opus-4-6",
) -> dict:
    """Run the LLM judge on a single match result.

    Returns the parsed judge response with claims, unsupported_count, etc.
    """
    evaluations_text = _format_evaluations(evaluations)
    prompt = JUDGE_PROMPT.format(
        evaluations_text=evaluations_text,
        explanation=explanation,
    )

    client = get_claude_client()
    response = await paced_claude_call(
        client,
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    result = parse_json_response(text)

    if not result:
        return {
            "claims": [],
            "total_claims": 0,
            "unsupported_count": 0,
            "summary": "Judge failed to return valid JSON",
            "parse_error": True,
        }

    return result
