"""Tool: PDF report generation for patient dossiers.

Renders a Verified Eligibility Dossier as a PDF that patients can bring
to their oncologist. Uses fpdf2 for lightweight PDF generation.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from logging_config import get_logger
from tools import ToolResult, ToolSpec, register_tool

logger = get_logger("kyriaki.tools.pdf_renderer")

# Brand colors
_BRAND_BLUE = (30, 58, 138)
_HEADER_BG = (239, 246, 255)
_LIGHT_GRAY = (245, 245, 245)
_DARK_TEXT = (31, 41, 55)
_GREEN = (22, 163, 74)
_YELLOW = (202, 138, 4)
_RED = (220, 38, 38)


def _score_color(score: int) -> tuple:
    if score >= 65:
        return _GREEN
    if score >= 40:
        return _YELLOW
    return _RED


class DossierPDF(FPDF):
    """Custom PDF with Kyriaki header/footer."""

    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_BRAND_BLUE)
        self.cell(0, 8, "KYRIAKI", new_x=XPos.RIGHT, new_y=YPos.TOP, align="L")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Verified Eligibility Dossier", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
        self.set_draw_color(*_BRAND_BLUE)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-20)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(130, 130, 130)
        self.cell(0, 5, "This document is for informational purposes only and does not constitute medical advice.", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.cell(
            0, 5,
            f"Generated {datetime.now(timezone.utc).strftime('%B %d, %Y')}  |  Page {self.page_no()}/{{nb}}",
            align="C",
        )

    def section_title(self, title: str):
        self.set_fill_color(*_HEADER_BG)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*_BRAND_BLUE)
        self.cell(0, 8, f"  {title}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(2)

    def body_text(self, text: str):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK_TEXT)
        self.multi_cell(0, 5, text)
        self.ln(2)

    def label_value(self, label: str, value: str):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(80, 80, 80)
        self.cell(50, 5, label, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK_TEXT)
        self.cell(0, 5, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def render_dossier_pdf(
    dossier: dict[str, Any],
    patient_data: dict[str, Any] | None = None,
) -> ToolResult:
    """Render a dossier as a PDF. Returns ToolResult with data=bytes."""
    try:
        pdf = DossierPDF()
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=25)
        pdf.add_page()

        # Title
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(*_BRAND_BLUE)
        pdf.cell(0, 12, "Verified Eligibility Dossier", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.ln(2)

        # Patient summary
        patient_summary = dossier.get("patient_summary", "")
        if patient_summary:
            pdf.section_title("Patient Summary")
            pdf.body_text(patient_summary)

        # Patient demographics (if available)
        if patient_data:
            pdf.section_title("Patient Profile")
            pdf.label_value("Cancer Type:", patient_data.get("cancer_type", "N/A"))
            pdf.label_value("Stage:", patient_data.get("cancer_stage", "N/A"))
            pdf.label_value("Age / Sex:", f"{patient_data.get('age', '?')} / {patient_data.get('sex', '?')}")
            biomarkers = patient_data.get("biomarkers", [])
            if biomarkers:
                pdf.label_value("Biomarkers:", ", ".join(biomarkers) if isinstance(biomarkers, list) else str(biomarkers))
            treatments = patient_data.get("prior_treatments", [])
            if treatments:
                pdf.label_value("Prior Treatments:", ", ".join(treatments) if isinstance(treatments, list) else str(treatments))
            pdf.label_value("Lines of Therapy:", str(patient_data.get("lines_of_therapy", "N/A")))
            ecog = patient_data.get("ecog_score")
            if ecog is not None:
                pdf.label_value("ECOG Score:", str(ecog))
            pdf.ln(3)

        # Trial sections
        sections = dossier.get("sections", [])
        for i, section in enumerate(sections):
            if i > 0:
                pdf.add_page()

            nct_id = section.get("nct_id", "Unknown")
            brief_title = section.get("brief_title", "Untitled Trial")
            revised_score = section.get("revised_score", section.get("match_score", "?"))

            # Trial header
            pdf.section_title(f"Trial {i + 1}: {nct_id}")
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*_DARK_TEXT)
            pdf.multi_cell(0, 5, brief_title)
            pdf.ln(2)

            # Score badge
            if isinstance(revised_score, (int, float)):
                color = _score_color(int(revised_score))
                pdf.set_font("Helvetica", "B", 12)
                pdf.set_text_color(*color)
                pdf.cell(0, 7, f"Match Score: {revised_score}/100", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)

            # Score justification
            justification = section.get("score_justification", "")
            if justification:
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(0, 5, "Score Justification:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.body_text(justification)

            # Clinical summary
            clinical_summary = section.get("clinical_summary", "")
            if clinical_summary:
                pdf.section_title("Clinical Summary")
                pdf.body_text(clinical_summary)

            # Patient-facing summary
            patient_section_summary = section.get("patient_summary", "")
            if patient_section_summary:
                pdf.section_title("What This Means for You")
                pdf.body_text(patient_section_summary)

            # Criteria analysis table
            criteria = section.get("criteria_analysis", [])
            if criteria:
                pdf.section_title("Eligibility Criteria Analysis")
                _render_criteria_table(pdf, criteria)

            # Next steps
            next_steps = section.get("next_steps", [])
            if next_steps:
                pdf.section_title("Next Steps")
                for step in next_steps:
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(*_DARK_TEXT)
                    # Use a simple bullet
                    pdf.cell(5, 5, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 5, f"- {step}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(2)

            # Flags for oncologist
            flags = section.get("flags", [])
            if flags:
                pdf.section_title("Items for Your Oncologist")
                for flag in flags:
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(*_YELLOW)
                    pdf.cell(5, 5, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 5, f"! {flag}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(2)

        # Disclaimer page
        pdf.add_page()
        pdf.section_title("Important Disclaimer")
        pdf.body_text(
            "This Verified Eligibility Dossier was generated by Kyriaki, an AI-powered clinical trial "
            "matching system. It is intended to help you and your oncologist evaluate potential clinical "
            "trial options."
        )
        pdf.body_text(
            "This document does NOT constitute medical advice, a diagnosis, or a treatment recommendation. "
            "Clinical trial eligibility is ultimately determined by the trial site's research team after "
            "a formal screening process."
        )
        pdf.body_text(
            "Please share this document with your oncologist or care team to discuss whether any of "
            "these trials may be appropriate for your situation."
        )

        # Output
        buf = io.BytesIO()
        pdf.output(buf)
        pdf_bytes = buf.getvalue()
        logger.info("pdf.rendered", sections=len(sections), size_kb=len(pdf_bytes) // 1024)
        return ToolResult(success=True, data=pdf_bytes)

    except Exception as e:
        logger.error("pdf.render_failed", error=str(e))
        return ToolResult(success=False, error=f"PDF render failed: {e}")


def _render_criteria_table(pdf: DossierPDF, criteria: list[dict]):
    """Render the criteria analysis as a formatted table."""
    # Column widths
    col_criterion = 80
    col_type = 20
    col_status = 25
    col_evidence = 55

    # Header
    pdf.set_fill_color(*_BRAND_BLUE)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(col_criterion, 6, "  Criterion", fill=True)
    pdf.cell(col_type, 6, "Type", fill=True, align="C")
    pdf.cell(col_status, 6, "Status", fill=True, align="C")
    pdf.cell(col_evidence, 6, "Evidence", fill=True)
    pdf.ln()

    # Rows
    pdf.set_font("Helvetica", "", 8)
    for i, c in enumerate(criteria):
        bg = _LIGHT_GRAY if i % 2 == 0 else (255, 255, 255)
        pdf.set_fill_color(*bg)

        status = c.get("status", "unknown")
        if status in ("met", "not_triggered"):
            pdf.set_text_color(*_GREEN)
            status_display = status.replace("_", " ").title()
        elif status in ("not_met", "triggered"):
            pdf.set_text_color(*_RED)
            status_display = status.replace("_", " ").title()
        else:
            pdf.set_text_color(*_YELLOW)
            status_display = status.replace("_", " ").title()

        criterion_text = c.get("criterion", "")[:60]
        evidence_text = c.get("evidence", c.get("notes", ""))[:45]

        pdf.set_text_color(*_DARK_TEXT)
        pdf.cell(col_criterion, 5, f"  {criterion_text}", fill=True)
        pdf.cell(col_type, 5, c.get("type", "")[:10], fill=True, align="C")

        # Status with color
        if status in ("met", "not_triggered"):
            pdf.set_text_color(*_GREEN)
        elif status in ("not_met", "triggered"):
            pdf.set_text_color(*_RED)
        else:
            pdf.set_text_color(*_YELLOW)
        pdf.cell(col_status, 5, status_display, fill=True, align="C")

        pdf.set_text_color(*_DARK_TEXT)
        pdf.cell(col_evidence, 5, evidence_text, fill=True)
        pdf.ln()

    pdf.ln(3)


# --- Register tool ---

register_tool(
    "render_dossier_pdf",
    render_dossier_pdf,
    ToolSpec(
        name="render_dossier_pdf",
        description="Render a Verified Eligibility Dossier as a PDF for the patient.",
        parameters={
            "dossier": "Dossier dict with patient_summary, sections, generated_at",
            "patient_data": "Optional patient profile dict for demographics section",
        },
        returns="PDF bytes",
    ),
)
