# Enrollment Workflow

## Objective
Generate a complete enrollment packet for a specific trial: screening checklist for the site coordinator, preparation guide for the patient, and a draft outreach message.

## Required Inputs
- `patient`: dict (patient profile data)
- `dossier`: dict (from DossierAgent output, contains sections)
- `trial_nct_id`: str (the specific trial to enroll in)

## Steps

### 1. Locate Dossier Section
- Find the section in dossier.sections where nct_id == trial_nct_id
- If not found: return error immediately

### 2. Fetch Fresh Trial Data
**Tool:** `fetch_trial`
- Input: trial_nct_id
- Output: full trial data with current site/contact info
- Extract nearest site for location context

### 3. Generate Enrollment Packet
**Tool:** `render_prompt` → `claude_json_call`
- Prompt: `enrollment_packet`
- Input: patient JSON, trial info, dossier section analysis
- Output: JSON with patient_demographics, screening_checklist, match_rationale
- Emit: `progress` → `{"step": "generating_packet"}`

### 4. Generate Patient Prep Guide
**Tool:** `render_prompt` → `claude_json_call`
- Prompt: `patient_prep`
- Input: patient basics, trial info, site info, screening checklist from Step 3
- Output: JSON with what_to_expect, documents_to_bring, questions_to_ask
- Emit: `progress` → `{"step": "generating_prep_guide"}`

### 5. Generate Outreach Draft
**Tool:** `render_prompt` → `claude_json_call`
- Prompt: `outreach_message`
- Input: trial info, site info, contact name, patient clinical summary, match details
- Output: JSON with subject_line, message_body, follow_up_notes
- Emit: `progress` → `{"step": "generating_outreach_draft"}`

### 6. Request Human Gate
- Gate type: `enrollment_review`
- Requested data: full enrollment output (packet + prep guide + outreach draft)
- Task status transitions to `blocked`

## Expected Output
```json
{
  "patient_packet": {...},
  "patient_prep_guide": {...},
  "outreach_draft": {...},
  "trial_nct_id": "NCT...",
  "trial_title": "string"
}
```

## Edge Cases
- **Dossier section not found:** Return error, don't proceed
- **Trial fetch fails:** Use empty site info, generate packet anyway
- **Any Claude call fails:** That component gets `{"error": "Failed to generate"}`
- **Steps 3-5 are sequential:** Prep guide depends on screening checklist from packet
- **Navigator approves:** Auto-chains to OutreachAgent
