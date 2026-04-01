import { useState, useEffect, useCallback } from "react";
import IntakeForm from "./components/IntakeForm";
import TrialResults from "./components/TrialResults";
import TrialDetail from "./components/TrialDetail";
import DossierView from "./components/DossierView";
import { startMatch, startDossier, getTask, resolveGate } from "./api";
import useTaskPoller from "./hooks/useTaskPoller";

const FALLBACK_MESSAGES = [
  "Searching ClinicalTrials.gov for recruiting studies...",
  "Found potential matches. Analyzing eligibility criteria...",
  "Reviewing inclusion and exclusion criteria against your profile...",
  "Evaluating biomarker and treatment history requirements...",
  "Calculating distances to trial sites near you...",
  "Ranking trials by match confidence...",
  "Almost there -- finalizing your personalized results...",
];

function progressMessage(events) {
  if (!events || events.length === 0) return null;
  const last = [...events].reverse().find((e) => e.event_type === "progress");
  if (!last) return null;
  const d = last.data || last;
  if (d.step === "searching_trials") return "Searching ClinicalTrials.gov for recruiting studies...";
  if (d.step === "analyzing_trial")
    return `Analyzing trial ${d.trial_index} of ${d.total}...`;
  if (d.step === "deep_analysis")
    return `Starting deep analysis of ${d.trial_count} trial${d.trial_count !== 1 ? "s" : ""}...`;
  return null;
}

const DISCLAIMER =
  "These results are for informational purposes only and do not constitute medical advice. " +
  "Please discuss all findings with your oncologist before making any treatment decisions.";

export default function App() {
  const [view, setView] = useState("intake"); // intake | loading | results | detail | dossier
  const [results, setResults] = useState(null);
  const [selectedTrial, setSelectedTrial] = useState(null);
  const [error, setError] = useState(null);
  const [fallbackMsgIndex, setFallbackMsgIndex] = useState(0);

  // Async task tracking
  const [matchTaskId, setMatchTaskId] = useState(null);
  const [dossierTaskId, setDossierTaskId] = useState(null);
  const [dossierData, setDossierData] = useState(null);
  const [dossierStatus, setDossierStatus] = useState(null); // null | "loading" | "done" | "error"
  const [gateId, setGateId] = useState(null);
  const [approvalStatus, setApprovalStatus] = useState(null); // null | "approving" | "approved"

  const matchPoller = useTaskPoller(matchTaskId, { enabled: view === "loading" });
  const dossierPoller = useTaskPoller(dossierTaskId, { enabled: dossierStatus === "loading" });

  // Fallback message cycling (when no real events arrive)
  useEffect(() => {
    if (view !== "loading") return;
    setFallbackMsgIndex(0);
    const interval = setInterval(() => {
      setFallbackMsgIndex((prev) =>
        prev < FALLBACK_MESSAGES.length - 1 ? prev + 1 : prev
      );
    }, 4000);
    return () => clearInterval(interval);
  }, [view]);

  // When matching task completes, extract results
  useEffect(() => {
    if (!matchPoller.isComplete || !matchPoller.task) return;

    if (matchPoller.isError) {
      setError(matchPoller.task?.error || "Matching failed. Please try again.");
      setView("intake");
      setMatchTaskId(null);
      return;
    }

    // Fetch final task data to get output_data
    getTask(matchPoller.task.task_id || matchTaskId).then((t) => {
      const out = t.output_data || {};
      setResults({
        patient_summary: out.patient_summary || "",
        matches: out.matches || [],
        total_trials_screened: out.total_trials_screened || 0,
        task_id: t.task_id,
        disclaimer: DISCLAIMER,
      });
      setView("results");
      setMatchTaskId(null);
    }).catch((err) => {
      setError(err.message);
      setView("intake");
      setMatchTaskId(null);
    });
  }, [matchPoller.isComplete, matchPoller.isError, matchPoller.task, matchTaskId]);

  // When dossier task completes (blocked = gate created)
  useEffect(() => {
    if (!dossierPoller.isComplete || !dossierPoller.task) return;

    if (dossierPoller.isError) {
      setDossierStatus("error");
      setError("Dossier generation failed: " + (dossierPoller.task?.error || "unknown error"));
      setDossierTaskId(null);
      return;
    }

    getTask(dossierPoller.task.task_id || dossierTaskId).then((t) => {
      setDossierData(t.output_data?.dossier || null);
      // Extract gate ID from task detail response
      if (t.gates && t.gates.length > 0) {
        setGateId(t.gates[0].gate_id);
      }
      setDossierStatus("done");
      setDossierTaskId(null);
    }).catch((err) => {
      setDossierStatus("error");
      setError(err.message);
      setDossierTaskId(null);
    });
  }, [dossierPoller.isComplete, dossierPoller.isError, dossierPoller.task, dossierTaskId]);

  const handleSubmit = async (patient) => {
    setView("loading");
    setError(null);
    setDossierStatus(null);
    setDossierData(null);
    setGateId(null);
    setApprovalStatus(null);

    try {
      const task = await startMatch(patient);
      // If backend returned a completed task (sync fallback), handle immediately
      if (task.status === "completed" && task.output_data) {
        const out = task.output_data;
        setResults({
          patient_summary: out.patient_summary || "",
          matches: out.matches || [],
          total_trials_screened: out.total_trials_screened || 0,
          task_id: task.task_id,
          disclaimer: DISCLAIMER,
        });
        setView("results");
      } else {
        setMatchTaskId(task.task_id);
      }
    } catch (err) {
      setError(err.message);
      setView("intake");
    }
  };

  const handleDossier = async () => {
    if (!results?.task_id) return;
    setDossierStatus("loading");
    try {
      const task = await startDossier(results.task_id, 3);
      if (task.status === "blocked" && task.output_data) {
        // Sync fallback — already complete
        setDossierData(task.output_data?.dossier || null);
        if (task.gates && task.gates.length > 0) setGateId(task.gates[0].gate_id);
        setDossierStatus("done");
      } else {
        setDossierTaskId(task.task_id);
      }
    } catch (err) {
      setDossierStatus("error");
      setError("Dossier generation failed: " + err.message);
    }
  };

  const handleViewDossier = () => {
    if (dossierData) setView("dossier");
  };

  const handleApprove = async () => {
    if (!gateId) return;
    setApprovalStatus("approving");
    try {
      await resolveGate(gateId, "approved", "Navigator", "Reviewed and approved");
      setApprovalStatus("approved");
    } catch (err) {
      setApprovalStatus(null);
      setError("Failed to approve: " + err.message);
    }
  };

  const handleRetry = useCallback(() => setError(null), []);

  const handleSelectTrial = (trial) => {
    setSelectedTrial(trial);
    setView("detail");
  };

  const handleBackToResults = () => {
    setSelectedTrial(null);
    setView("results");
  };

  const handleStartOver = () => {
    setResults(null);
    setSelectedTrial(null);
    setError(null);
    setDossierStatus(null);
    setDossierData(null);
    setMatchTaskId(null);
    setDossierTaskId(null);
    setGateId(null);
    setApprovalStatus(null);
    setView("intake");
  };

  // Derive loading message from real events or fallback
  const realMsg = progressMessage(matchPoller.events);
  const loadingMessage = realMsg || FALLBACK_MESSAGES[fallbackMsgIndex];
  const progressPct = realMsg
    ? null // indeterminate when we have real events (SSE drives it)
    : ((fallbackMsgIndex + 1) / FALLBACK_MESSAGES.length) * 100;

  return (
    <div className="app">
      <header>
        <h1>Kyriaki</h1>
        <p className="header-subtitle">Find clinical trials matched to you</p>
      </header>

      {error && (
        <div className="error-banner" role="alert">
          <div className="error-banner-content">
            <svg className="error-icon" viewBox="0 0 20 20" fill="currentColor" width="20" height="20" aria-hidden="true">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
            </svg>
            <div className="error-text">
              <strong>Something went wrong</strong>
              <span>{error}</span>
            </div>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={handleRetry}>Dismiss</button>
        </div>
      )}

      <div className={`view-container ${view}`}>
        {view === "intake" && <IntakeForm onSubmit={handleSubmit} />}

        {view === "loading" && (
          <div className="loading" role="status" aria-live="polite">
            <h2>Searching for your matches</h2>
            <div className="agent-badge">
              <span className="agent-dot" />
              MatchingAgent running
              {matchTaskId && <span className="agent-task-id">{matchTaskId.slice(0, 8)}</span>}
            </div>
            <div className="spinner" aria-hidden="true">
              <div className="spinner-ring" />
              <div className="spinner-ring spinner-ring-2" />
            </div>
            <p className="loading-message" key={loadingMessage}>
              {loadingMessage}
            </p>
            <div className="loading-progress">
              <div
                className={`loading-progress-bar ${progressPct == null ? "progress-indeterminate" : ""}`}
                style={progressPct != null ? { width: `${progressPct}%` } : {}}
              />
            </div>
            <p className="loading-patience">This typically takes 15-30 seconds</p>
          </div>
        )}

        {view === "results" && results && (
          <TrialResults
            data={results}
            onSelect={handleSelectTrial}
            onBack={handleStartOver}
            onDossier={handleDossier}
            onViewDossier={handleViewDossier}
            dossierStatus={dossierStatus}
          />
        )}

        {view === "detail" && selectedTrial && (
          <TrialDetail trial={selectedTrial} onBack={handleBackToResults} />
        )}

        {view === "dossier" && dossierData && (
          <DossierView
            dossier={dossierData}
            onBack={handleBackToResults}
            onApprove={gateId ? handleApprove : null}
            approvalStatus={approvalStatus}
          />
        )}
      </div>
    </div>
  );
}
