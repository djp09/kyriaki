"""Tests for document upload and AI extraction."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.document_extractor import (
    SUPPORTED_TYPES,
    _build_content_blocks,
    _validate_upload,
    extract_from_document,
)

# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_pdf(self):
        assert _validate_upload("application/pdf", 1000) is None

    def test_valid_png(self):
        assert _validate_upload("image/png", 1000) is None

    def test_valid_jpeg(self):
        assert _validate_upload("image/jpeg", 1000) is None

    def test_unsupported_type(self):
        err = _validate_upload("text/plain", 1000)
        assert err is not None
        assert "Unsupported" in err

    def test_file_too_large(self):
        err = _validate_upload("application/pdf", 15 * 1024 * 1024)
        assert err is not None
        assert "too large" in err

    def test_supported_types_set(self):
        assert "application/pdf" in SUPPORTED_TYPES
        assert "image/png" in SUPPORTED_TYPES
        assert "image/jpeg" in SUPPORTED_TYPES
        assert "image/gif" in SUPPORTED_TYPES
        assert "image/webp" in SUPPORTED_TYPES


# ---------------------------------------------------------------------------
# Content block building tests
# ---------------------------------------------------------------------------


class TestContentBlocks:
    def test_pdf_content_blocks(self):
        blocks = _build_content_blocks(b"fake-pdf-data", "application/pdf")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "document"
        assert blocks[0]["source"]["media_type"] == "application/pdf"
        assert blocks[1]["type"] == "text"

    def test_image_content_blocks(self):
        blocks = _build_content_blocks(b"fake-image-data", "image/png")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "image"
        assert blocks[0]["source"]["media_type"] == "image/png"
        assert blocks[1]["type"] == "text"

    def test_base64_encoding(self):
        import base64

        raw = b"test data"
        blocks = _build_content_blocks(raw, "image/jpeg")
        encoded = blocks[0]["source"]["data"]
        assert base64.standard_b64decode(encoded) == raw


# ---------------------------------------------------------------------------
# Extraction tests (mocked Claude)
# ---------------------------------------------------------------------------


class TestExtraction:
    @pytest.mark.asyncio
    async def test_extract_successful(self):
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "document_type": "pathology_report",
                        "confidence": 0.92,
                        "extracted": {
                            "cancer_type": "Non-Small Cell Lung Cancer",
                            "cancer_stage": "Stage IV",
                            "biomarkers": ["EGFR L858R+", "PD-L1 80%"],
                            "prior_treatments": [],
                            "lines_of_therapy": 0,
                            "age": 62,
                            "sex": "male",
                            "ecog_score": None,
                            "key_labs": {},
                            "additional_conditions": [],
                            "additional_notes": "Diagnosed 2026-01-15",
                        },
                        "extraction_notes": "Pathology report with biomarker panel",
                    }
                )
            )
        ]
        mock_response.usage = MagicMock(input_tokens=500, output_tokens=200)

        with patch("tools.document_extractor.call_claude_with_retry", AsyncMock(return_value=mock_response)):
            result = await extract_from_document(b"fake-pdf", "application/pdf", "report.pdf")

        assert result.success
        assert result.data["document_type"] == "pathology_report"
        assert result.data["confidence"] == 0.92
        assert result.data["extracted"]["cancer_type"] == "Non-Small Cell Lung Cancer"
        assert result.data["extracted"]["biomarkers"] == ["EGFR L858R+", "PD-L1 80%"]
        assert result.token_usage is not None
        assert result.token_usage.input_tokens == 500

    @pytest.mark.asyncio
    async def test_extract_unsupported_type(self):
        result = await extract_from_document(b"data", "text/plain", "file.txt")
        assert not result.success
        assert "Unsupported" in result.error

    @pytest.mark.asyncio
    async def test_extract_file_too_large(self):
        result = await extract_from_document(b"x" * (11 * 1024 * 1024), "application/pdf", "huge.pdf")
        assert not result.success
        assert "too large" in result.error

    @pytest.mark.asyncio
    async def test_extract_parse_failure(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="This is not JSON at all")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with patch("tools.document_extractor.call_claude_with_retry", AsyncMock(return_value=mock_response)):
            result = await extract_from_document(b"fake", "image/png", "scan.png")

        assert not result.success
        assert "parse" in result.error.lower()

    @pytest.mark.asyncio
    async def test_extract_empty_result(self):
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text=json.dumps({"document_type": "other", "confidence": 0.1, "extracted": {}}))
        ]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with patch("tools.document_extractor.call_claude_with_retry", AsyncMock(return_value=mock_response)):
            result = await extract_from_document(b"fake", "image/png", "blank.png")

        assert not result.success
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_extract_api_error(self):
        with patch(
            "tools.document_extractor.call_claude_with_retry",
            AsyncMock(side_effect=RuntimeError("API unavailable")),
        ):
            result = await extract_from_document(b"fake", "application/pdf", "report.pdf")

        assert not result.success
        assert "RuntimeError" in result.error


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestUploadEndpoint:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from main import app

        with TestClient(app) as c:
            yield c

    def test_upload_unsupported_type(self, client):
        resp = client.post(
            "/api/upload/document",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_empty_file(self, client):
        resp = client.post(
            "/api/upload/document",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code == 400

    def test_upload_successful_extraction(self, client):
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "document_type": "lab_results",
                        "confidence": 0.85,
                        "extracted": {
                            "cancer_type": None,
                            "key_labs": {"wbc": 5.2, "platelets": 180},
                            "biomarkers": [],
                            "prior_treatments": [],
                            "additional_conditions": [],
                        },
                        "extraction_notes": "Lab panel only",
                    }
                )
            )
        ]
        mock_response.usage = MagicMock(input_tokens=300, output_tokens=100)

        with patch("tools.document_extractor.call_claude_with_retry", AsyncMock(return_value=mock_response)):
            resp = client.post(
                "/api/upload/document",
                files={"file": ("labs.pdf", b"fake-pdf-content", "application/pdf")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["document_type"] == "lab_results"
        assert data["confidence"] == 0.85
        assert data["extracted"]["key_labs"]["wbc"] == 5.2
        assert data["token_usage"]["total_tokens"] == 400
