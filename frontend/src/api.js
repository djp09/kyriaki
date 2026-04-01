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
