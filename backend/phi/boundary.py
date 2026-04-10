"""PHI boundary — the sole gate between internal PHI and external LLM APIs.

Every payload bound for an external model MUST flow through ``to_external_llm``.
That function de-identifies free-text content, validates the shape of the
outgoing message blocks, and raises ``PHIBoundaryViolation`` if it detects
anything suspicious.

See ADR-004 (Data security, PHI handling & compliance posture).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from phi.deidentify import Redaction, deidentify


class PHIBoundaryViolation(Exception):
    """Raised when a payload crossing the PHI boundary is not safe to send."""

    def __init__(self, message: str, redactions: list[Redaction] | None = None):
        super().__init__(message)
        self.redactions = redactions or []


@dataclass
class ExternalPayload:
    """A de-identified payload ready for an external LLM call."""

    model: str
    max_tokens: int
    messages: list[dict[str, Any]]
    tools: list[Any] | None = None
    system: list[dict[str, Any]] | None = None
    redaction_report: dict[str, int] = field(default_factory=dict)


def _merge_report(target: dict[str, int], other: dict[str, int]) -> None:
    for k, v in other.items():
        target[k] = target.get(k, 0) + v


def _scrub_text_block(text: str, report: dict[str, int]) -> str:
    result = deidentify(text)
    _merge_report(report, result.redaction_report)
    return result.text


def _scrub_content_blocks(
    content: list[dict[str, Any]],
    report: dict[str, int],
    *,
    allow_binary: bool,
) -> list[dict[str, Any]]:
    new_blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            raise PHIBoundaryViolation(f"Unexpected content block type: {type(block).__name__} (expected dict)")
        block_type = block.get("type")
        if block_type == "text":
            cleaned = _scrub_text_block(block.get("text", ""), report)
            new_blocks.append({**block, "text": cleaned})
        elif block_type in ("image", "document"):
            if not allow_binary:
                raise PHIBoundaryViolation(
                    f"Binary content block ({block_type}) is not allowed through the PHI "
                    "boundary by default. Caller must pass allow_binary=True and be "
                    "responsible for consent/minimisation of the binary payload."
                )
            # Binary payloads can carry PHI (images of scans, scanned pathology
            # reports with names). We cannot scrub them at the text level.
            # Log intent via redaction_report and let them through untouched.
            report["binary_passthrough"] = report.get("binary_passthrough", 0) + 1
            new_blocks.append(block)
        elif block_type == "tool_use" or block_type == "tool_result":
            # Tool blocks may contain text — scrub recursively where applicable.
            new_blocks.append(_scrub_tool_block(block, report, allow_binary=allow_binary))
        else:
            raise PHIBoundaryViolation(
                f"Unknown content block type: {block_type!r}. "
                "The PHI boundary must be updated to handle this block type explicitly."
            )
    return new_blocks


def _scrub_tool_block(
    block: dict[str, Any],
    report: dict[str, int],
    *,
    allow_binary: bool,
) -> dict[str, Any]:
    out = dict(block)
    # tool_result content may be a string or a list of blocks
    content = out.get("content")
    if isinstance(content, str):
        out["content"] = _scrub_text_block(content, report)
    elif isinstance(content, list):
        out["content"] = _scrub_content_blocks(content, report, allow_binary=allow_binary)
    return out


def _scrub_system_blocks(
    system: str | list[dict[str, Any]],
    report: dict[str, int],
) -> list[dict[str, Any]]:
    """Scrub and normalise a system prompt into a list of content blocks.

    Accepts either a plain string or a list of Anthropic-style content blocks.
    Returns a list of text blocks with PHI scrubbed.
    """
    if isinstance(system, str):
        cleaned = _scrub_text_block(system, report)
        return [{"type": "text", "text": cleaned}]

    if not isinstance(system, list):
        raise PHIBoundaryViolation(f"system must be a str or list, got {type(system).__name__}")

    blocks: list[dict[str, Any]] = []
    for block in system:
        if not isinstance(block, dict):
            raise PHIBoundaryViolation(f"System block must be a dict, got {type(block).__name__}")
        if block.get("type") != "text":
            raise PHIBoundaryViolation(
                f"Only text blocks are allowed in system prompts, got {block.get('type')!r}"
            )
        cleaned = _scrub_text_block(block.get("text", ""), report)
        new_block = {**block, "text": cleaned}
        blocks.append(new_block)
    return blocks


def to_external_llm(
    *,
    model: str,
    max_tokens: int,
    messages: list[dict[str, Any]],
    tools: list[Any] | None = None,
    allow_binary: bool = False,
    system: str | list[dict[str, Any]] | None = None,
) -> ExternalPayload:
    """Convert an internal message list into a de-identified external payload.

    This is the ONLY function allowed to construct payloads for Claude API
    (or other external LLM) calls. All direct ``anthropic.messages.create``
    invocations outside ``tools/claude_api.py`` are forbidden and enforced
    by CI (see ``scripts/check-phi-boundary.sh``).

    Args:
        model: model identifier (e.g. "claude-sonnet-4-6").
        max_tokens: max completion tokens.
        messages: Anthropic-style messages list. Each message has ``role``
            and ``content``; content may be a string or a list of blocks.
        tools: optional tool definitions (passed through untouched — they
            describe schemas, not patient data).
        allow_binary: if True, image/document content blocks are permitted
            to pass through unscrubbed. Use only for explicit user-uploaded
            documents where the user has consented and the binary cannot
            be scrubbed at the text layer. Requires an informed caller.
        system: optional system prompt — a plain string or a list of
            Anthropic-style text content blocks. Scrubbed through the PHI
            boundary just like messages.

    Raises:
        PHIBoundaryViolation: if a content block cannot be safely handled.

    Returns:
        ExternalPayload with scrubbed messages and a redaction report.
    """
    if not isinstance(messages, list):
        raise PHIBoundaryViolation(f"messages must be a list, got {type(messages).__name__}")

    report: dict[str, int] = {}
    sanitised: list[dict[str, Any]] = []

    for msg in messages:
        if not isinstance(msg, dict):
            raise PHIBoundaryViolation(f"Each message must be a dict, got {type(msg).__name__}")
        content = msg.get("content")
        if isinstance(content, str):
            cleaned = _scrub_text_block(content, report)
            sanitised.append({**msg, "content": cleaned})
        elif isinstance(content, list):
            cleaned_blocks = _scrub_content_blocks(content, report, allow_binary=allow_binary)
            sanitised.append({**msg, "content": cleaned_blocks})
        elif content is None:
            sanitised.append(dict(msg))
        else:
            raise PHIBoundaryViolation(f"Unsupported message content type: {type(content).__name__}")

    sanitised_system: list[dict[str, Any]] | None = None
    if system is not None:
        sanitised_system = _scrub_system_blocks(system, report)

    return ExternalPayload(
        model=model,
        max_tokens=max_tokens,
        messages=sanitised,
        tools=tools,
        system=sanitised_system,
        redaction_report=report,
    )
