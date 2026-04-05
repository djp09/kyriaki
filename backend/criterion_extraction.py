"""Stage 4 — Criterion extraction (local Gemma).

Parses free-text eligibility criteria from ClinicalTrials.gov into structured
criterion objects. Used for cache-warming during nightly trial sync; the
rule-based parser in tools/criteria_parser.py is the fast fallback for
real-time cache misses.

PHI note: trial eligibility text is public data (not PHI), but running
extraction locally avoids Claude API cost for ~50 trials per patient search.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from gemma_client import get_gemma_client


class Criterion(BaseModel):
    """A single parsed eligibility criterion."""

    type: Literal["inclusion", "exclusion"]
    text: str = Field(..., description="The criterion as stated in the protocol, lightly cleaned.")
    category: str = Field(
        ...,
        description=(
            "One of: diagnosis, stage, biomarker, prior_therapy, demographic, "
            "performance, labs, comorbidity, washout, disease_status, consent, other"
        ),
    )


class ExtractedCriteria(BaseModel):
    """Structured output from criterion extraction."""

    criteria: list[Criterion] = Field(default_factory=list)
    extraction_notes: str = Field(
        default="",
        description="Any ambiguity or issues encountered during extraction.",
    )


CRITERION_EXTRACTION_PROMPT = """\
You are an oncology clinical trial eligibility criteria parser. Extract EVERY \
individual criterion from the eligibility text below into a structured list.

## Rules

1. **Split compound criteria.** If a single bullet contains multiple independent \
requirements, split them. Example:
   "Age >= 18 years with histologically confirmed NSCLC" → TWO criteria:
   - (inclusion, demographic) "Age >= 18 years"
   - (inclusion, diagnosis) "Histologically confirmed NSCLC"

2. **Preserve clinical precision.** Keep drug names, lab thresholds, and timeframes \
exactly as written. Do NOT paraphrase or simplify.

3. **Type assignment:**
   - Criteria under "Inclusion Criteria" headers → type: "inclusion"
   - Criteria under "Exclusion Criteria" headers → type: "exclusion"
   - If no clear header, default to "inclusion" for positive requirements \
("must have", "required") and "exclusion" for negative requirements \
("must not have", "no history of").

4. **Category assignment** — choose exactly ONE per criterion:
   | Category | Matches |
   |---|---|
   | diagnosis | Histology, pathology, confirmed disease type |
   | stage | Disease stage, locally advanced, metastatic, recurrent, refractory |
   | biomarker | Gene mutations, expression levels, receptor status, molecular markers |
   | prior_therapy | Prior treatments, lines of therapy, treatment-naive, resistance |
   | demographic | Age, sex, pregnancy, contraception |
   | performance | ECOG, Karnofsky, functional status |
   | labs | Lab values, organ function, blood counts |
   | comorbidity | Comorbid conditions, infections, autoimmune, cardiac |
   | washout | Time since last treatment, half-lives, washout periods |
   | disease_status | Measurable disease, CNS metastases, lesion requirements |
   | consent | Informed consent, willingness, compliance, follow-up |
   | other | Anything that doesn't fit above |

5. **Skip non-criteria.** Ignore section headers, preambles ("Patients must meet \
ALL of the following"), and empty lines.

6. **Do NOT add criteria that aren't in the text.** Only extract what is written.

## Eligibility Text
{eligibility_text}
"""


async def extract_criteria(
    eligibility_text: str,
) -> ExtractedCriteria:
    """Extract structured criteria from free-text eligibility block using Gemma.

    Args:
        eligibility_text: Raw eligibility criteria text from ClinicalTrials.gov.

    Returns:
        ExtractedCriteria with typed, categorized criteria list.
    """
    if not eligibility_text or not eligibility_text.strip():
        return ExtractedCriteria(
            criteria=[],
            extraction_notes="Empty eligibility text provided.",
        )

    prompt = CRITERION_EXTRACTION_PROMPT.format(
        eligibility_text=eligibility_text.strip(),
    )

    client = get_gemma_client()
    result = await client.generate(prompt, schema=ExtractedCriteria, max_tokens=4096)
    assert isinstance(result, ExtractedCriteria)
    return result
