const BASE = "/api";

async function request(url, options) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("Request was cancelled.");
    }
    throw new Error(
      "Could not connect to the server. Please check your internet connection and try again."
    );
  }

  if (!res.ok) {
    let detail;
    try {
      const body = await res.json();
      detail = body.detail;
    } catch {
      // response wasn't JSON
    }

    if (res.status === 429) {
      throw new Error("Too many requests. Please wait a moment and try again.");
    }
    if (res.status >= 500) {
      throw new Error(
        detail || "The server encountered an error. Please try again in a moment."
      );
    }
    throw new Error(detail || `Request failed (${res.status}).`);
  }

  return res.json();
}

export async function submitIntake(patient) {
  return request(`${BASE}/intake`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patient),
  });
}

export async function matchTrials(patient, maxResults = 10) {
  return request(`${BASE}/match`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient, max_results: maxResults }),
  });
}

export async function getTrialDetail(nctId) {
  return request(`${BASE}/trials/${nctId}`);
}

// --- Agent endpoints ---

export async function agentMatch(patient, maxResults = 10) {
  const task = await request(`${BASE}/agents/match`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient, max_results: maxResults }),
  });
  // Convert agent task response to the same shape as /api/match
  return {
    patient_summary: task.output_data?.patient_summary || "",
    matches: task.output_data?.matches || [],
    total_trials_screened: task.output_data?.total_trials_screened || 0,
    task_id: task.task_id,
    disclaimer:
      "These results are for informational purposes only and do not constitute medical advice. " +
      "Please discuss all findings with your oncologist before making any treatment decisions.",
  };
}

export async function agentDossier(matchingTaskId, nctId) {
  return request(`${BASE}/agents/dossier`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ matching_task_id: matchingTaskId, nct_id: nctId }),
  });
}

export async function getTask(taskId) {
  return request(`${BASE}/agents/tasks/${taskId}`);
}

export async function resolveGate(gateId, status, resolvedBy, notes = null, chainToTrial = null) {
  const body = { status, resolved_by: resolvedBy, notes };
  if (chainToTrial) body.chain_to_trial = chainToTrial;
  return request(`${BASE}/agents/gates/${gateId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Phase 2B: Async dispatch + queries ---

export async function startMatch(patient, maxResults = 10) {
  return request(`${BASE}/agents/match`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient, max_results: maxResults }),
  });
}

export async function startDossier(matchingTaskId, nctId) {
  return request(`${BASE}/agents/dossier`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ matching_task_id: matchingTaskId, nct_id: nctId }),
  });
}

export async function getTaskEvents(taskId) {
  return request(`${BASE}/agents/tasks/${taskId}/events`);
}

export async function listGates(status = "pending") {
  return request(`${BASE}/agents/gates?status=${encodeURIComponent(status)}`);
}

// --- Document upload ---

export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append("file", file);

  let res;
  try {
    res = await fetch(`${BASE}/upload/document`, {
      method: "POST",
      body: formData,
    });
  } catch (err) {
    throw new Error("Could not connect to the server. Please try again.");
  }

  if (!res.ok) {
    let detail;
    try {
      const body = await res.json();
      detail = body.detail || body.message;
    } catch {
      // not JSON
    }
    throw new Error(detail || `Upload failed (${res.status}).`);
  }

  return res.json();
}
