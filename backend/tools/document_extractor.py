"""Tool: Medical document extraction using Claude vision.

Extracts structured patient data from uploaded pathology reports,
treatment summaries, and lab results. Supports PDF (first pages)
and images (PNG, JPG).
"""

from __future__ import annotations

import base64
from typing import Any

from config import get_settings
from logging_config import get_logger
from tools import ToolResult, ToolSpec, register_tool
from tools.claude_api import _extract_token_usage, call_claude_with_retry, get_claude_client, parse_json_response

logger = get_logger("kyriaki.tools.document_extractor")

EXTRACTION_PROMPT = """\
You are an expert oncology medical records analyst. Extract structured patient data from this medical document.

Extract ALL of the following fields that are present in the document. If a field is not mentioned, use null.

## Fields to Extract

- **cancer_type**: The specific cancer diagnosis (e.g., "Non-Small Cell Lung Cancer", "Triple Negative Breast Cancer")
- **cancer_stage**: TNM stage or clinical stage (e.g., "Stage IV", "Stage IIIB", "T2N1M0")
- **biomarkers**: List of biomarker results with status (e.g., ["EGFR L858R+", "PD-L1 80%", "ALK-", "KRAS G12C"])
- **prior_treatments**: List of treatments the patient has received (e.g., ["Carboplatin/Pemetrexed x4 cycles", "Pembrolizumab"])
- **lines_of_therapy**: Number of distinct treatment lines (integer)
- **age**: Patient age (integer)
- **sex**: "male" or "female"
- **ecog_score**: ECOG performance status (0-4)
- **key_labs**: Dictionary of lab values with units (e.g., {"wbc": 5.2, "platelets": 180, "creatinine": 0.9})
- **additional_conditions**: List of comorbidities (e.g., ["Type 2 Diabetes", "Hypertension"])
- **additional_notes**: Any other clinically relevant information not captured above

## Document Type Detection
Also identify what type of document this is:
- "pathology_report" — biopsy/surgical pathology
- "treatment_summary" — treatment history or plan
- "lab_results" — laboratory test results
- "radiology_report" — imaging results
- "clinical_note" — physician notes
- "other" — anything else

## Important Rules
- Extract biomarker results exactly as stated (preserve +/- notation)
- For lab values, include the numeric value without units in the dict
- If you see a treatment regimen, list each drug in the regimen
- Count lines of therapy based on distinct treatment regimens, not individual drugs
- If the document mentions dates, note them in additional_notes
- Be conservative: only extract what's clearly stated, don't infer

Respond with ONLY a JSON object:
{"document_type": "<type>", "confidence": <0.0-1.0>, "extracted": {"cancer_type": "<str or null>", "cancer_stage": "<str or null>", "biomarkers": [<str>], "prior_treatments": [<str>], "lines_of_therapy": <int or null>, "age": <int or null>, "sex": "<str or null>", "ecog_score": <int or null>, "key_labs": {<str: number>}, "additional_conditions": [<str>], "additional_notes": "<str or null>"}, "extraction_notes": "<brief notes about what was found/missing>"}
"""

# Supported MIME types
SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
SUPPORTED_PDF_TYPE = "application/pdf"
SUPPORTED_TYPES = SUPPORTED_IMAGE_TYPES | {SUPPORTED_PDF_TYPE}

# Max file size: 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024


def _validate_upload(content_type: str, file_size: int) -> str | None:
    """Validate file type and size. Returns error message or None."""
    if content_type not in SUPPORTED_TYPES:
        return f"Unsupported file type: {content_type}. Supported: PDF, PNG, JPG, GIF, WEBP"
    if file_size > MAX_FILE_SIZE:
        return f"File too large: {file_size / 1024 / 1024:.1f}MB. Maximum: 10MB"
    return None


def _build_content_blocks(
    file_bytes: bytes,
    content_type: str,
) -> list[dict[str, Any]]:
    """Build Claude API content blocks for the document."""
    b64_data = base64.standard_b64encode(file_bytes).decode("utf-8")

    if content_type == SUPPORTED_PDF_TYPE:
        return [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": b64_data,
                },
            },
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]

    # Image types
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": content_type,
                "data": b64_data,
            },
        },
        {"type": "text", "text": EXTRACTION_PROMPT},
    ]


async def extract_from_document(
    file_bytes: bytes,
    content_type: str,
    filename: str = "",
) -> ToolResult:
    """Extract structured patient data from a medical document.

    Args:
        file_bytes: Raw file content
        content_type: MIME type (application/pdf, image/png, etc.)
        filename: Original filename for logging

    Returns:
        ToolResult with data={document_type, confidence, extracted, extraction_notes}
    """
    # Validate
    error = _validate_upload(content_type, len(file_bytes))
    if error:
        return ToolResult(success=False, error=error)

    settings = get_settings()
    content_blocks = _build_content_blocks(file_bytes, content_type)

    logger.info(
        "document.extract_start",
        filename=filename,
        content_type=content_type,
        size_kb=len(file_bytes) // 1024,
    )

    try:
        # Bypass the adaptive concurrency limiter — this is a user-facing
        # upload, not a batch analysis call. The limiter is shared with the
        # matching agent and can block uploads when agents are running.
        response = await call_claude_with_retry(
            get_claude_client(),
            model=settings.claude_model,
            max_tokens=2000,
            messages=[{"role": "user", "content": content_blocks}],
        )
        tokens = _extract_token_usage(response)
        text = response.content[0].text.strip()
        result = parse_json_response(text)

        if result is None:
            return ToolResult(
                success=False,
                error="Failed to parse extraction result from Claude",
                token_usage=tokens,
            )

        # Validate expected shape
        extracted = result.get("extracted", {})
        if not extracted:
            return ToolResult(
                success=False,
                error="Extraction returned empty results",
                token_usage=tokens,
            )

        logger.info(
            "document.extract_complete",
            filename=filename,
            document_type=result.get("document_type", "unknown"),
            confidence=result.get("confidence", 0),
            fields_found=sum(1 for v in extracted.values() if v is not None and v != [] and v != {}),
        )

        return ToolResult(success=True, data=result, token_usage=tokens)

    except Exception as e:
        logger.error("document.extract_failed", filename=filename, error=str(e))
        return ToolResult(success=False, error=f"Extraction failed: {type(e).__name__}: {e}")


# --- Register tool ---

register_tool(
    "extract_from_document",
    extract_from_document,
    ToolSpec(
        name="extract_from_document",
        description="Extract structured patient data from a medical document (PDF, image).",
        parameters={
            "file_bytes": "Raw file content as bytes",
            "content_type": "MIME type (application/pdf, image/png, image/jpeg, etc.)",
            "filename": "Original filename for logging",
        },
        returns="Dict with document_type, confidence, extracted fields, extraction_notes",
        edge_cases=[
            "Returns error if file type unsupported or > 10MB",
            "Confidence < 0.5 means extraction is unreliable — flag for manual review",
            "PDF extraction uses first pages only — very long reports may be truncated",
        ],
    ),
)
