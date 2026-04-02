# Monitor Workflow

## Objective
Check trial status changes and new site additions for a patient's watched trials. Run periodically or on-demand.

## Required Inputs
- `watches`: list[dict] — each with nct_id, last_status, last_site_count

## Steps

### 1. Check Each Trial
**Tool:** `fetch_trial` (per watch)
- Emit: `progress` → `{"step": "checking_trials", "count": N}`
- For each watch entry:
  - Fetch current trial data
  - Compare current overall_status to last_status
  - Compare current site count to last_site_count
  - Record any changes
  - Emit: `progress` → `{"step": "checked_trial", "nct_id": "..."}`

### 2. Collect Changes
- Aggregate all detected changes:
  - `status_changed`: old_status → new_status
  - `sites_added`: old_count → new_count
  - `not_found`: trial no longer available

## Expected Output
```json
{
  "changes": [{"nct_id": "", "change_type": "status_changed|sites_added|not_found", ...}],
  "trials_checked": int,
  "checked_at": "ISO timestamp"
}
```

## Edge Cases
- **Trial not found:** Record as `not_found` change, continue checking others
- **No changes detected:** Return empty changes array (still successful)
- **Network error on one trial:** Log warning, skip that trial, continue
