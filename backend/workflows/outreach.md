# Outreach Workflow

## Objective
Finalize and personalize the outreach message for a trial site coordinator, with full contact information extracted from the trial record.

## Required Inputs
- `outreach_draft`: dict (from EnrollmentAgent, contains message_body and subject_line)
- `trial_nct_id`: str
- `patient`: dict (patient profile, for context)

## Steps

### 1. Extract Contacts
**Tool:** `fetch_trial` → `extract_contacts`
- Fetch fresh trial data
- Extract contacts from up to 5 nearest sites
- Emit: `progress` → `{"step": "extracting_contacts"}`

### 2. Personalize Message
**Tool:** `claude_json_call` (if contacts available with a name)
- Only if primary contact has a name
- Input: original message + contact name + facility
- Output: personalized message_body
- Emit: `progress` → `{"step": "finalizing_message"}`
- If no contacts or personalization fails: use original draft as-is

### 3. Request Human Gate
- Gate type: `outreach_review`
- Requested data: contacts, final_message, subject_line, outreach_status
- Task status transitions to `blocked`

## Expected Output
```json
{
  "contacts": [{"name": "", "role": "", "phone": "", "email": "", "facility": "", "city": "", "state": ""}],
  "final_message": "string",
  "subject_line": "string",
  "outreach_status": "ready_for_review"
}
```

## Edge Cases
- **Trial fetch fails:** Empty contacts list, use draft message as-is
- **No contacts with names:** Skip personalization, use draft
- **Personalization parse fails:** Fall back to original draft message
