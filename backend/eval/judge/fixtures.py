"""Tier 3 — LLM-judge faithfulness fixtures.

Each fixture pairs a set of per-criterion evaluations with a plain-language
explanation (Stage 6 output). The judge checks whether the explanation
accurately reflects the evaluations — no unsupported claims.

For CI: frozen explanation + evaluations, judge mocked.
For live: judge runs on Claude Opus.
"""

from __future__ import annotations

FAITHFULNESS_FIXTURES: list[dict] = [
    # -------------------------------------------------------------------
    # 1. Faithful explanation — all claims supported
    # -------------------------------------------------------------------
    {
        "id": "faithful_strong_match",
        "description": "All claims in explanation match criterion evaluations",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Confirmed NSCLC",
                "reasoning": "Patient has NSCLC.",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "EGFR activating mutation",
                "reasoning": "EGFR L858R confirmed.",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "ECOG 0-1",
                "reasoning": "ECOG 1.",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "status": "NOT_TRIGGERED",
                "criterion_text": "Prior EGFR TKI",
                "reasoning": "No prior EGFR TKI.",
            },
        ],
        "explanation": "This trial appears to be a strong fit for you. You have confirmed NSCLC with an EGFR L858R mutation, which is exactly what this trial is looking for. Your ECOG performance status of 1 meets the requirement, and you have not previously received an EGFR TKI, so the exclusion criterion does not apply.",
        "expected_unsupported_claims": 0,
    },
    # -------------------------------------------------------------------
    # 2. Faithful excluded explanation
    # -------------------------------------------------------------------
    {
        "id": "faithful_excluded",
        "description": "Explanation correctly states exclusion reason",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Confirmed NSCLC",
                "reasoning": "Patient has NSCLC.",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "status": "TRIGGERED",
                "criterion_text": "Prior EGFR TKI therapy",
                "reasoning": "Patient received osimertinib.",
            },
        ],
        "explanation": "Unfortunately, this trial is not a match because you have previously received osimertinib, which is an EGFR TKI. The trial excludes patients with prior EGFR TKI therapy.",
        "expected_unsupported_claims": 0,
    },
    # -------------------------------------------------------------------
    # 3. Faithful with unknowns
    # -------------------------------------------------------------------
    {
        "id": "faithful_with_unknowns",
        "description": "Explanation correctly notes what needs oncologist verification",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Confirmed TNBC",
                "reasoning": "Patient has TNBC.",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "status": "INSUFFICIENT_INFO",
                "criterion_text": "Adequate organ function",
                "reasoning": "Lab values not provided.",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "status": "INSUFFICIENT_INFO",
                "criterion_text": "Active autoimmune disease",
                "reasoning": "Not confirmed.",
            },
        ],
        "explanation": "This trial could be a good option for your triple-negative breast cancer. However, we need your lab results to confirm you meet the organ function requirements. Your oncologist should also confirm you don't have active autoimmune disease.",
        "expected_unsupported_claims": 0,
    },
    # -------------------------------------------------------------------
    # 4. UNFAITHFUL — claims a criterion is met when it's unknown
    # -------------------------------------------------------------------
    {
        "id": "unfaithful_claims_met_when_unknown",
        "description": "Explanation says labs are fine but they were INSUFFICIENT_INFO",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Confirmed CRC",
                "reasoning": "Patient has CRC.",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "MSI-H status",
                "reasoning": "MSI-H confirmed.",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "status": "INSUFFICIENT_INFO",
                "criterion_text": "Adequate hepatic function",
                "reasoning": "Liver function tests not provided.",
            },
        ],
        "explanation": "This trial is a great match. You have MSI-H colorectal cancer, and your liver function is within normal limits. You meet all the key criteria.",
        "expected_unsupported_claims": 1,
    },
    # -------------------------------------------------------------------
    # 5. UNFAITHFUL — omits a triggered exclusion
    # -------------------------------------------------------------------
    {
        "id": "unfaithful_omits_exclusion",
        "description": "Explanation doesn't mention a triggered exclusion",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Confirmed melanoma",
                "reasoning": "Patient has melanoma.",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "BRAF V600E",
                "reasoning": "BRAF V600E confirmed.",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "status": "TRIGGERED",
                "criterion_text": "Prior BRAF inhibitor",
                "reasoning": "Patient received dabrafenib.",
            },
        ],
        "explanation": "This trial is a strong match for your BRAF V600E melanoma. You meet the key inclusion criteria including confirmed melanoma and BRAF mutation.",
        "expected_unsupported_claims": 1,
    },
    # -------------------------------------------------------------------
    # 6. UNFAITHFUL — invents a criterion that wasn't evaluated
    # -------------------------------------------------------------------
    {
        "id": "unfaithful_invents_criterion",
        "description": "Explanation mentions PD-L1 which wasn't in evaluations",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Stage IV NSCLC",
                "reasoning": "Patient has Stage IV NSCLC.",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "ECOG 0-1",
                "reasoning": "ECOG 0.",
            },
        ],
        "explanation": "This trial is a good fit. You have Stage IV NSCLC with ECOG 0, and your high PD-L1 expression makes you an ideal candidate for this immunotherapy trial.",
        "expected_unsupported_claims": 1,
    },
    # -------------------------------------------------------------------
    # 7. UNFAITHFUL — wrong polarity on exclusion
    # -------------------------------------------------------------------
    {
        "id": "unfaithful_wrong_exclusion_status",
        "description": "Explanation says exclusion doesn't apply when it does",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Advanced solid tumor",
                "reasoning": "Patient has advanced cancer.",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "status": "TRIGGERED",
                "criterion_text": "Active brain metastases",
                "reasoning": "Patient has new brain metastases.",
            },
        ],
        "explanation": "This trial accepts patients with advanced solid tumors. You don't have any brain metastases, so the exclusion criteria don't apply. This could be a good option to discuss with your doctor.",
        "expected_unsupported_claims": 1,
    },
    # -------------------------------------------------------------------
    # 8. Faithful partial match
    # -------------------------------------------------------------------
    {
        "id": "faithful_partial",
        "description": "Explanation accurately reflects mixed results",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Pancreatic cancer",
                "reasoning": "Confirmed.",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "status": "NOT_MET",
                "criterion_text": "ECOG 0-1",
                "reasoning": "Patient has ECOG 2.",
            },
            {
                "criterion_id": "I3",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Prior systemic therapy",
                "reasoning": "2 prior lines.",
            },
        ],
        "explanation": "This trial is a partial match. You have the right cancer type and prior treatment history, but the trial requires ECOG 0-1 and your current performance status is ECOG 2. Discuss with your oncologist whether your functional status might improve or if an exception could apply.",
        "expected_unsupported_claims": 0,
    },
    # -------------------------------------------------------------------
    # 9. Faithful with drug knowledge
    # -------------------------------------------------------------------
    {
        "id": "faithful_drug_knowledge",
        "description": "Explanation correctly identifies drug class",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Prostate cancer",
                "reasoning": "Confirmed mCRPC.",
            },
            {
                "criterion_id": "E1",
                "type": "exclusion",
                "status": "TRIGGERED",
                "criterion_text": "Prior PARP inhibitor",
                "reasoning": "Patient received olaparib.",
            },
        ],
        "explanation": "This trial is not a match because you have previously received olaparib, which is a PARP inhibitor. The trial excludes patients with prior PARP inhibitor therapy.",
        "expected_unsupported_claims": 0,
    },
    # -------------------------------------------------------------------
    # 10. UNFAITHFUL — understates severity of NOT_MET
    # -------------------------------------------------------------------
    {
        "id": "unfaithful_understates_not_met",
        "description": "Explanation says 'might qualify' when critical criterion is NOT_MET",
        "evaluations": [
            {
                "criterion_id": "I1",
                "type": "inclusion",
                "status": "NOT_MET",
                "criterion_text": "Age >= 18 years",
                "reasoning": "Patient is 8 years old.",
            },
            {
                "criterion_id": "I2",
                "type": "inclusion",
                "status": "MET",
                "criterion_text": "Solid tumor",
                "reasoning": "Patient has neuroblastoma.",
            },
        ],
        "explanation": "You might qualify for this trial. You have a solid tumor which meets one criterion. The age requirement is 18+ and you're 8, but some trials make exceptions for pediatric patients.",
        "expected_unsupported_claims": 1,
    },
]

FAITHFUL_FIXTURES = [f for f in FAITHFULNESS_FIXTURES if f["expected_unsupported_claims"] == 0]
UNFAITHFUL_FIXTURES = [f for f in FAITHFULNESS_FIXTURES if f["expected_unsupported_claims"] > 0]
