"""Tests for the PHI boundary: phi.boundary.to_external_llm."""

from __future__ import annotations

import pytest

from phi.boundary import PHIBoundaryViolation, to_external_llm


def test_string_content_is_scrubbed() -> None:
    payload = to_external_llm(
        model="claude-sonnet-4-6",
        max_tokens=100,
        messages=[{"role": "user", "content": "Patient Name: John Smith, MRN: 001234"}],
    )
    content = payload.messages[0]["content"]
    assert "John Smith" not in content
    assert "001234" not in content
    assert "[NAME]" in content
    assert payload.redaction_report["name"] == 1
    assert payload.redaction_report["labeled_id"] == 1


def test_list_text_blocks_are_scrubbed() -> None:
    payload = to_external_llm(
        model="m",
        max_tokens=10,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Dr. Alice Walker 555-123-4567"},
                    {"type": "text", "text": "Email: foo@bar.com"},
                ],
            }
        ],
    )
    blocks = payload.messages[0]["content"]
    assert "Alice Walker" not in blocks[0]["text"]
    assert "foo@bar.com" not in blocks[1]["text"]
    assert payload.redaction_report["name"] >= 1
    assert payload.redaction_report["phone"] >= 1
    assert payload.redaction_report["email"] >= 1


def test_image_block_rejected_by_default() -> None:
    with pytest.raises(PHIBoundaryViolation, match="Binary content block"):
        to_external_llm(
            model="m",
            max_tokens=10,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "data": "..."}},
                    ],
                }
            ],
        )


def test_document_block_rejected_by_default() -> None:
    with pytest.raises(PHIBoundaryViolation):
        to_external_llm(
            model="m",
            max_tokens=10,
            messages=[
                {"role": "user", "content": [{"type": "document", "source": {}}]},
            ],
        )


def test_binary_allowed_with_explicit_flag() -> None:
    payload = to_external_llm(
        model="m",
        max_tokens=10,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "data": "..."}},
                    {"type": "text", "text": "Patient Name: Jane Doe"},
                ],
            }
        ],
        allow_binary=True,
    )
    # Binary block passes through
    assert payload.messages[0]["content"][0]["type"] == "image"
    # Text still scrubbed
    assert "Jane Doe" not in payload.messages[0]["content"][1]["text"]
    assert payload.redaction_report["binary_passthrough"] == 1
    assert payload.redaction_report["name"] == 1


def test_unknown_block_type_raises() -> None:
    with pytest.raises(PHIBoundaryViolation, match="Unknown content block type"):
        to_external_llm(
            model="m",
            max_tokens=10,
            messages=[{"role": "user", "content": [{"type": "mystery", "data": "x"}]}],
        )


def test_unsupported_content_type_raises() -> None:
    with pytest.raises(PHIBoundaryViolation, match="Unsupported message content type"):
        to_external_llm(
            model="m",
            max_tokens=10,
            messages=[{"role": "user", "content": 42}],
        )


def test_clean_text_passes_through_unchanged() -> None:
    msg = "Stage IV NSCLC with EGFR L858R mutation, on osimertinib."
    payload = to_external_llm(
        model="m",
        max_tokens=10,
        messages=[{"role": "user", "content": msg}],
    )
    assert payload.messages[0]["content"] == msg
    assert payload.redaction_report == {}


def test_tools_are_passed_through() -> None:
    tools = [{"name": "search", "description": "search trials"}]
    payload = to_external_llm(
        model="m",
        max_tokens=10,
        messages=[{"role": "user", "content": "hello"}],
        tools=tools,
    )
    assert payload.tools == tools


def test_model_and_max_tokens_preserved() -> None:
    payload = to_external_llm(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert payload.model == "claude-opus-4-6"
    assert payload.max_tokens == 2048


def test_messages_must_be_list() -> None:
    with pytest.raises(PHIBoundaryViolation, match="messages must be a list"):
        to_external_llm(model="m", max_tokens=10, messages="oops")  # type: ignore[arg-type]


def test_none_content_allowed() -> None:
    # assistant messages sometimes have content=None during tool flows
    payload = to_external_llm(
        model="m",
        max_tokens=10,
        messages=[{"role": "assistant", "content": None, "tool_calls": []}],
    )
    assert payload.messages[0]["content"] is None


def test_tool_result_block_text_scrubbed() -> None:
    payload = to_external_llm(
        model="m",
        max_tokens=10,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "abc",
                        "content": "Patient name is John Smith per record.",
                    }
                ],
            }
        ],
    )
    cleaned = payload.messages[0]["content"][0]["content"]
    assert "John Smith" not in cleaned
    assert "[NAME]" in cleaned
