const BASE = "/api";

export async function submitIntake(patient) {
  const res = await fetch(`${BASE}/intake`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patient),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to validate intake");
  }
  return res.json();
}

export async function matchTrials(patient, maxResults = 10) {
  const res = await fetch(`${BASE}/match`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient, max_results: maxResults }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Matching failed");
  }
  return res.json();
}

export async function getTrialDetail(nctId) {
  const res = await fetch(`${BASE}/trials/${nctId}`);
  if (!res.ok) throw new Error("Trial not found");
  return res.json();
}
