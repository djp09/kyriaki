ELIGIBILITY_ANALYSIS_PROMPT = """\
You are an expert oncology clinical trial eligibility analyst. Carefully evaluate whether this cancer patient is likely eligible for the specified clinical trial.

## Patient Profile
- **Cancer Type:** {cancer_type}
- **Stage:** {cancer_stage}
- **Biomarkers:** {biomarkers}
- **Prior Treatments:** {prior_treatments} ({lines_of_therapy} prior line(s) of therapy)
- **Age:** {age}
- **Sex:** {sex}
- **ECOG Performance Status:** {ecog_score}
- **Key Labs:** {key_labs}
- **Other Conditions:** {additional_conditions}
- **Additional Notes:** {additional_notes}

## Clinical Trial: {nct_id} — {brief_title}
**Phase:** {phase}
**Summary:** {brief_summary}

### Eligibility Criteria
{eligibility_criteria}

## Instructions

Evaluate the patient against each eligibility criterion. Be concise — use short phrases, not full sentences, in per-criterion explanations.

### Scoring Rubric
Assign a match confidence score (0-100) based on these rules:
- **85-100 (Strong match):** Patient clearly meets ALL key inclusion criteria AND triggers NO exclusion criteria. At most minor unknowns (e.g., a lab value not reported but typically normal).
- **65-84 (Likely match):** Patient meets the major criteria (cancer type, stage, biomarkers if required). A few unknowns exist but nothing suggests disqualification.
- **40-64 (Possible match):** Significant unknowns OR one borderline criterion. Could go either way — worth discussing with oncologist.
- **20-39 (Unlikely match):** Patient likely fails at least one important criterion OR has a condition that commonly triggers exclusion.
- **0-19 (Poor match):** Patient clearly fails a hard inclusion criterion (wrong cancer type, wrong stage, required biomarker absent) OR clearly triggers a hard exclusion.

### Special Cases
- **Biomarker-specific trials:** If the trial requires a specific biomarker (e.g., EGFR mutation, HER2+, BRCA1/2) and the patient lacks it or is negative, score 0-19. If biomarker status is unknown/not tested, score 30-50 and flag for oncologist.
- **Pediatric trials:** If the trial specifies a maximum age below 18 and the patient is an adult (or vice versa), score 0.
- **Prior therapy requirements:** Some trials require specific prior treatments (e.g., "must have progressed on platinum-based chemo"). Evaluate carefully against the patient's treatment history.
- **Very long eligibility text:** Focus on the criteria most likely to disqualify: cancer type/stage match, required biomarkers, prior therapy, ECOG, key organ function labs. Summarize the rest briefly.

### Output Format
Respond with ONLY a JSON object — no markdown fences, no commentary. Keep the total response under 1000 tokens. Limit inclusion_evaluations and exclusion_evaluations to the 5-8 most important criteria each rather than listing every single one.

Example of a STRONG match:
{{"match_score": 88, "match_explanation": "You appear to be a strong fit for this trial. It's studying a new immunotherapy for Stage IV NSCLC patients who have already tried platinum-based chemotherapy, which matches your situation. Your PD-L1 status and ECOG score also align with what they're looking for.", "inclusion_evaluations": [{{"criterion": "Stage IV NSCLC", "status": "met", "explanation": "Patient has Stage IV NSCLC"}}, {{"criterion": "Prior platinum-based therapy", "status": "met", "explanation": "Had Carboplatin/Pemetrexed"}}, {{"criterion": "ECOG 0-1", "status": "met", "explanation": "ECOG is 1"}}], "exclusion_evaluations": [{{"criterion": "Active brain metastases", "status": "not_triggered", "explanation": "No brain mets reported"}}, {{"criterion": "Autoimmune disease", "status": "not_triggered", "explanation": "No autoimmune conditions listed"}}], "flags_for_oncologist": ["Confirm no untreated brain metastases", "Verify adequate organ function labs"]}}

Example of a POOR match:
{{"match_score": 12, "match_explanation": "This trial is specifically for patients with EGFR-mutated lung cancer. Your biomarker results show EGFR-negative, which unfortunately means this trial would not be a fit.", "inclusion_evaluations": [{{"criterion": "EGFR activating mutation", "status": "not_met", "explanation": "Patient is EGFR-negative"}}], "exclusion_evaluations": [], "flags_for_oncologist": []}}

JSON schema:
{{"match_score": <int 0-100>, "match_explanation": "<2-3 sentences a patient can understand>", "inclusion_evaluations": [{{"criterion": "<text>", "status": "met|not_met|unknown", "explanation": "<short phrase>"}}], "exclusion_evaluations": [{{"criterion": "<text>", "status": "not_triggered|triggered|unknown", "explanation": "<short phrase>"}}], "flags_for_oncologist": ["<item>"]}}
"""

PATIENT_SUMMARY_PROMPT = """\
Write a brief, warm 2-3 sentence summary of this cancer patient's journey so far. This will appear at the top of their personalized trial matching results, so it should feel supportive and acknowledge what they've been through. Include the key clinical details that matter for trial matching (biomarkers and treatment history) woven naturally into the narrative.

Patient profile:
- Cancer: {cancer_type}, {cancer_stage}
- Biomarkers: {biomarkers}
- Prior treatments: {prior_treatments} ({lines_of_therapy} line(s) of therapy)
- Age: {age}, {sex}
- ECOG score: {ecog_score}

Write as if speaking directly to the patient ("You..."). Be compassionate but not patronizing. Mention their specific biomarker results and treatments by name so the summary feels personalized, not generic. Respond with ONLY the summary text, nothing else.
"""

DOSSIER_ANALYSIS_PROMPT = """\
You are an expert oncology clinical trial eligibility analyst conducting a DEEP eligibility review for a Verified Eligibility Dossier. This dossier will be reviewed by a patient navigator and potentially shared with a trial site coordinator.

## Patient Profile
{patient_json}

## Clinical Trial: {nct_id} — {brief_title}

### Eligibility Criteria
{eligibility_criteria}

## Initial Screening Assessment
Score: {initial_score}/100
Summary: {initial_explanation}

## Your Task

Conduct a thorough, line-by-line analysis of EVERY inclusion and exclusion criterion. For each:
1. State the criterion exactly as written
2. Evaluate against the patient data (met/not_met/unknown/needs_verification)
3. Cite the specific patient data point that supports your evaluation
4. Flag anything that needs physician verification

Then provide:
- A revised confidence score with detailed justification
- A plain-language summary for the patient (2-3 paragraphs)
- A clinical summary for the navigator/site coordinator (structured, precise)
- Specific next steps the patient should take

Respond with ONLY a JSON object — no markdown fences, no commentary:
{{"revised_score": <int 0-100>, "score_justification": "<detailed reasoning>", "criteria_analysis": [{{"criterion": "<exact text>", "type": "inclusion|exclusion", "status": "met|not_met|unknown|needs_verification", "evidence": "<patient data cited>", "notes": "<any caveats>"}}], "patient_summary": "<2-3 paragraphs, plain language>", "clinical_summary": "<structured for navigator/coordinator>", "next_steps": ["<action item>"], "flags": ["<items needing verification>"]}}
"""

# --- Evaluator-optimizer: score evaluation ---

SCORE_EVALUATION_PROMPT = """\
You are a senior oncology clinical trial eligibility REVIEWER. Another analyst has scored a patient-trial match. Your job is to evaluate their work for errors.

## Patient Profile
- **Cancer Type:** {cancer_type}
- **Stage:** {cancer_stage}
- **Biomarkers:** {biomarkers}
- **Prior Treatments:** {prior_treatments} ({lines_of_therapy} prior line(s) of therapy)
- **Age:** {age}
- **Sex:** {sex}
- **ECOG Performance Status:** {ecog_score}

## Clinical Trial: {nct_id} — {brief_title}

### Eligibility Criteria
{eligibility_criteria}

## Initial Analysis (to review)
Score: {initial_score}/100
Explanation: {initial_explanation}

### Criteria Evaluations
{criteria_json}

## Your Review Task

Check the initial analysis for these specific errors:
1. **Logical inconsistency:** Did the analyst mark a criterion "met" when the patient data says otherwise?
2. **Missed hard disqualifiers:** Is there a required biomarker, cancer type, or stage the patient clearly lacks?
3. **Score-rubric mismatch:** Does the score align with the rubric? (85-100 = all key criteria met, 0-19 = hard criterion failed, etc.)
4. **Overlooked exclusion criteria:** Did the analyst miss an exclusion criterion the patient likely triggers?
5. **Inflated unknowns:** Are criteria marked "unknown" when the patient data actually provides an answer?

If the score is correct, confirm it. If not, provide an adjusted score with specific reasoning.

Respond with ONLY a JSON object:
{{"confirmed": <true if score is correct, false if adjusted>, "adjusted_score": <int 0-100 or null if confirmed>, "adjustment_reason": "<specific error found, or 'Score is consistent with analysis' if confirmed>", "errors_found": ["<specific error>"]}}
"""

# --- Phase 2C: Enrollment pipeline prompts ---

ENROLLMENT_PACKET_PROMPT = """\
You are a clinical trial enrollment specialist preparing a Patient Enrollment Packet for a site research coordinator (CRC). This packet must contain everything the CRC needs to begin the screening process.

## Patient Profile
{patient_json}

## Trial: {nct_id} — {brief_title}

## Pre-Screening Analysis (from eligibility dossier)
Revised match score: {revised_score}/100
{clinical_summary}

## Criteria Analysis
{criteria_json}

## Task
Generate a structured enrollment packet. Be precise, clinical, and actionable.

Respond with ONLY a JSON object:
{{"patient_demographics": {{"age": <int>, "sex": "<str>", "cancer_type": "<str>", "stage": "<str>", "biomarkers": "<str>", "ecog": "<str>"}}, "diagnosis_summary": "<2-3 sentence clinical summary>", "treatment_history": "<prior treatments with lines>", "match_rationale": "<why this patient fits this trial, 2-3 sentences>", "prescreening_status": "<met/partial/needs_verification>", "screening_checklist": [{{"item": "<what is needed>", "category": "labs|imaging|records|other", "status": "needed|available|unknown", "notes": "<details>"}}], "insurance_notes": "<coverage considerations>", "special_considerations": ["<any flags or concerns>"]}}
"""

PATIENT_PREP_PROMPT = """\
You are a compassionate patient navigator helping a cancer patient prepare for a clinical trial screening visit. Write in plain language, as if speaking directly to the patient ("you").

## Patient Info
Cancer: {cancer_type}, {cancer_stage}
Age: {age}

## Trial
{brief_title} at {site_name} in {site_city}, {site_state}

## Screening Requirements
{screening_checklist}

## Task
Create a patient preparation guide. Be warm, clear, and practical.

Respond with ONLY a JSON object:
{{"what_to_expect": "<2-3 paragraphs explaining the screening visit process>", "documents_to_bring": ["<item>"], "questions_to_ask": ["<suggested question for the research team>"], "how_to_prepare": ["<practical preparation step>"], "logistics": {{"site_name": "{site_name}", "city": "{site_city}", "state": "{site_state}", "travel_tips": "<practical travel advice>"}}}}
"""

OUTREACH_MESSAGE_PROMPT = """\
You are drafting a professional outreach message from a patient navigator to a clinical trial site research coordinator. The goal is to introduce a pre-screened patient candidate and request next steps.

## Trial: {nct_id} — {brief_title}
## Site: {site_name}, {site_city}, {site_state}
## Contact: {contact_name}

## Patient Summary (de-identified)
{patient_summary}

## Match Details
Score: {match_score}/100
Rationale: {match_rationale}

## Task
Write a concise, professional outreach message. Do NOT include patient name or identifying information beyond clinical details.

Respond with ONLY a JSON object:
{{"subject_line": "<email subject>", "message_body": "<professional message, 3-4 paragraphs>", "follow_up_notes": "<when/how to follow up>"}}
"""
