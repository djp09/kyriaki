import { useState, useEffect, useCallback, useRef } from "react";
import DocumentUpload from "./components/DocumentUpload";
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
  if (d.step === "analyzing_trial") return `Analyzing trial ${d.trial_index} of ${d.total}...`;
  if (d.step === "deep_analysis") return `Starting deep analysis of ${d.trial_count} trial${d.trial_count !== 1 ? "s" : ""}...`;
  if (d.step === "generating_packet") return "Generating enrollment packet for site coordinator...";
  if (d.step === "generating_prep_guide") return "Creating your preparation guide...";
  if (d.step === "generating_outreach_draft") return "Drafting outreach message to trial site...";
  if (d.step === "extracting_contacts") return "Finding site coordinator contacts...";
  if (d.step === "finalizing_message") return "Personalizing outreach message...";
  return null;
}

const DISCLAIMER =
  "These results are for informational purposes only and do not constitute medical advice. " +
  "Please discuss all findings with your oncologist before making any treatment decisions.";

export default function App() {
  const [view, setView] = useState("upload");
  const [results, setResults] = useState(null);
  const [selectedTrial, setSelectedTrial] = useState(null);
  const [error, setError] = useState(null);
  const [fallbackMsgIndex, setFallbackMsgIndex] = useState(0);
  const [prefill, setPrefill] = useState(null);

  // Task tracking
  const [matchTaskId, setMatchTaskId] = useState(null);

  // Per-trial dossier/enrollment/outreach state
  // Map<nct_id, { taskId, data, status, gateId, approvalStatus,
  //               enrollmentTaskId, enrollmentData, enrollmentStatus, enrollmentGateId,
  //               outreachTaskId, outreachData, outreachStatus }>
  const [trialPipelines, setTrialPipelines] = useState({});
  const [viewingDossierNctId, setViewingDossierNctId] = useState(null);

  const updateTrialPipeline = useCallback((nctId, updates) => {
    setTrialPipelines((prev) => ({
      ...prev,
      [nctId]: { ...prev[nctId], ...updates },
    }));
  }, []);

  // Pollers
  const matchPoller = useTaskPoller(matchTaskId, { enabled: view === "loading" });

  // Fallback message cycling
  useEffect(() => {
    if (view !== "loading") return;
    setFallbackMsgIndex(0);
    const interval = setInterval(() => {
      setFallbackMsgIndex((prev) => (prev < FALLBACK_MESSAGES.length - 1 ? prev + 1 : prev));
    }, 4000);
    return () => clearInterval(interval);
  }, [view]);

  // Match completion
  useEffect(() => {
    if (!matchPoller.isComplete || !matchPoller.task) return;
    if (matchPoller.isError) {
      setError(matchPoller.task?.error || "Matching failed.");
      setView(previousView.current);
      setMatchTaskId(null);
      return;
    }
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
    }).catch((err) => { setError(err?.message || String(err)); setView(previousView.current); setMatchTaskId(null); });
  }, [matchPoller.isComplete, matchPoller.isError, matchPoller.task, matchTaskId]);

  // Per-trial dossier polling
  useEffect(() => {
    const intervals = {};
    Object.entries(trialPipelines).forEach(([nctId, p]) => {
      if (p.status === "loading" && p.taskId) {
        const poll = async () => {
          try {
            const t = await getTask(p.taskId);
            if (["completed", "blocked", "failed"].includes(t.status)) {
              updateTrialPipeline(nctId, {
                data: t.output_data?.dossier || null,
                gateId: t.gates?.[0]?.gate_id || null,
                status: t.status === "failed" ? "error" : "done",
                taskId: null,
              });
            }
          } catch { /* retry on next interval */ }
        };
        intervals[nctId] = setInterval(poll, 2500);
      }
    });
    return () => Object.values(intervals).forEach(clearInterval);
  }, [trialPipelines, updateTrialPipeline]);

  // Per-trial enrollment polling
  useEffect(() => {
    const intervals = {};
    Object.entries(trialPipelines).forEach(([nctId, p]) => {
      if (p.enrollmentStatus === "loading" && p.enrollmentTaskId) {
        const poll = async () => {
          try {
            const t = await getTask(p.enrollmentTaskId);
            if (["completed", "blocked", "failed"].includes(t.status)) {
              updateTrialPipeline(nctId, {
                enrollmentData: t.output_data || null,
                enrollmentGateId: t.gates?.[0]?.gate_id || null,
                enrollmentStatus: t.status === "failed" ? "error" : "done",
                enrollmentTaskId: null,
              });
            }
          } catch { /* retry */ }
        };
        intervals[nctId] = setInterval(poll, 2500);
      }
    });
    return () => Object.values(intervals).forEach(clearInterval);
  }, [trialPipelines, updateTrialPipeline]);

  // Per-trial outreach polling
  useEffect(() => {
    const intervals = {};
    Object.entries(trialPipelines).forEach(([nctId, p]) => {
      if (p.outreachStatus === "loading" && p.outreachTaskId) {
        const poll = async () => {
          try {
            const t = await getTask(p.outreachTaskId);
            if (["completed", "blocked", "failed"].includes(t.status)) {
              updateTrialPipeline(nctId, {
                outreachData: t.output_data || null,
                outreachStatus: t.status === "failed" ? "error" : "done",
                outreachTaskId: null,
              });
            }
          } catch { /* retry */ }
        };
        intervals[nctId] = setInterval(poll, 2500);
      }
    });
    return () => Object.values(intervals).forEach(clearInterval);
  }, [trialPipelines, updateTrialPipeline]);

  // --- Handlers ---

  const previousView = useRef("intake");

  const handleSubmit = async (patient) => {
    previousView.current = view === "upload" ? "upload" : "intake";
    setView("loading");
    setError(null);
    setTrialPipelines({});

    try {
      const task = await startMatch(patient);
      if (task.status === "completed" && task.output_data) {
        const out = task.output_data;
        setResults({ patient_summary: out.patient_summary || "", matches: out.matches || [], total_trials_screened: out.total_trials_screened || 0, task_id: task.task_id, disclaimer: DISCLAIMER });
        setView("results");
      } else {
        setMatchTaskId(task.task_id);
      }
    } catch (err) {
      const msg = err?.message || String(err);
      setError(msg);
      setView(previousView.current);
    }
  };

  const handleAnalyzeTrial = async (nctId) => {
    if (!results?.task_id) return;
    updateTrialPipeline(nctId, { status: "loading" });
    try {
      const task = await startDossier(results.task_id, nctId);
      if ((task.status === "blocked" || task.status === "completed") && task.output_data) {
        updateTrialPipeline(nctId, {
          data: task.output_data?.dossier || null,
          gateId: task.gates?.[0]?.gate_id || null,
          status: "done",
        });
      } else {
        updateTrialPipeline(nctId, { taskId: task.task_id });
      }
    } catch (err) {
      updateTrialPipeline(nctId, { status: "error" });
      setError("Analysis failed: " + err.message);
    }
  };

  const handleViewDossier = (nctId) => {
    const p = trialPipelines[nctId];
    if (p?.data) {
      setViewingDossierNctId(nctId);
      setView("dossier");
    }
  };

  const handleProceedToEnrollment = async (nctId) => {
    const p = trialPipelines[nctId];
    if (!p?.gateId) return;
    updateTrialPipeline(nctId, { approvalStatus: "approving" });
    try {
      await resolveGate(p.gateId, "approved", "Navigator", "Proceed to enrollment", nctId);
      updateTrialPipeline(nctId, { approvalStatus: "approved", enrollmentStatus: "loading" });
      // Poll for auto-chained enrollment task
      setTimeout(async () => {
        try {
          const tasks = await fetch("/api/agents/tasks").then((r) => r.json());
          const enrollTask = tasks.find(
            (t) => t.agent_type === "enrollment" && t.status !== "completed" && t.status !== "failed"
          );
          if (enrollTask) updateTrialPipeline(nctId, { enrollmentTaskId: enrollTask.task_id });
        } catch { /* retry */ }
      }, 2000);
    } catch (err) {
      updateTrialPipeline(nctId, { approvalStatus: null });
      setError("Failed to proceed: " + err.message);
    }
  };

  const handleApproveEnrollment = async (nctId) => {
    const p = trialPipelines[nctId];
    if (!p?.enrollmentGateId) return;
    try {
      await resolveGate(p.enrollmentGateId, "approved", "Navigator", "Packet approved, proceed with outreach");
      updateTrialPipeline(nctId, { enrollmentStatus: "approved", outreachStatus: "loading" });
      setTimeout(async () => {
        try {
          const tasks = await fetch("/api/agents/tasks").then((r) => r.json());
          const outTask = tasks.find(
            (t) => t.agent_type === "outreach" && t.status !== "completed" && t.status !== "failed"
          );
          if (outTask) updateTrialPipeline(nctId, { outreachTaskId: outTask.task_id });
        } catch { /* retry */ }
      }, 2000);
    } catch (err) { setError("Failed to approve enrollment: " + err.message); }
  };

  const handleDocSubmit = async (payload) => {
    // Document extraction produced a complete payload — go straight to matching
    await handleSubmit(payload);
  };

  const handleDocSkip = () => {
    setPrefill(null);
    setView("intake");
  };

  const handleRetry = useCallback(() => setError(null), []);
  const handleSelectTrial = (trial) => { setSelectedTrial(trial); setView("detail"); };
  const handleBackToResults = () => { setSelectedTrial(null); setViewingDossierNctId(null); setView("results"); };

  const handleStartOver = () => {
    setResults(null); setSelectedTrial(null); setError(null); setPrefill(null);
    setMatchTaskId(null); setTrialPipelines({}); setViewingDossierNctId(null);
    setView("upload");
  };

  // Active agent for loading indicator
  const anyLoading = Object.values(trialPipelines).find(
    (p) => p.status === "loading" || p.enrollmentStatus === "loading" || p.outreachStatus === "loading"
  );
  const activeAgent = anyLoading
    ? (anyLoading.outreachStatus === "loading" ? "OutreachAgent"
      : anyLoading.enrollmentStatus === "loading" ? "EnrollmentAgent"
      : "DossierAgent")
    : matchTaskId ? "MatchingAgent" : null;

  const realMsg = progressMessage(matchPoller.events);
  const loadingMessage = realMsg || FALLBACK_MESSAGES[fallbackMsgIndex];
  const progressPct = realMsg ? null : ((fallbackMsgIndex + 1) / FALLBACK_MESSAGES.length) * 100;

  // Current dossier data for DossierView
  const viewingPipeline = viewingDossierNctId ? trialPipelines[viewingDossierNctId] : null;

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

      {/* Pipeline status bar — shows when agents are working in background */}
      {activeAgent && view !== "loading" && (
        <div className="agent-badge" style={{ textAlign: "center", margin: "0 auto 1rem" }}>
          <span className="agent-dot" />
          {activeAgent} running — processing...
        </div>
      )}

      <div className={`view-container ${view}`}>
        {view === "upload" && (
          <DocumentUpload onSubmit={handleDocSubmit} onSkip={handleDocSkip} />
        )}

        {view === "intake" && <IntakeForm onSubmit={handleSubmit} prefill={prefill} />}

        {view === "loading" && (
          <div className="loading" role="status" aria-live="polite">
            <h2>Searching for your matches</h2>
            <div className="agent-badge">
              <span className="agent-dot" />
              {activeAgent || "MatchingAgent"} running
              {matchTaskId && <span className="agent-task-id">{matchTaskId.slice(0, 8)}</span>}
            </div>
            <div className="spinner" aria-hidden="true">
              <div className="spinner-ring" />
              <div className="spinner-ring spinner-ring-2" />
            </div>
            <p className="loading-message" key={loadingMessage}>{loadingMessage}</p>
            <div className="loading-progress">
              <div className={`loading-progress-bar ${progressPct == null ? "progress-indeterminate" : ""}`} style={progressPct != null ? { width: `${progressPct}%` } : {}} />
            </div>
            <p className="loading-patience">This typically takes 1-2 minutes as we analyze each trial's criteria</p>
          </div>
        )}

        {view === "results" && results && (
          <TrialResults
            data={results}
            onSelect={handleSelectTrial}
            onBack={handleStartOver}
            onAnalyzeTrial={handleAnalyzeTrial}
            onViewDossier={handleViewDossier}
            onProceedToEnrollment={handleProceedToEnrollment}
            onApproveEnrollment={handleApproveEnrollment}
            trialPipelines={trialPipelines}
          />
        )}

        {view === "detail" && selectedTrial && (
          <TrialDetail trial={selectedTrial} onBack={handleBackToResults} />
        )}

        {view === "dossier" && viewingPipeline?.data && (
          <DossierView
            dossier={viewingPipeline.data}
            nctId={viewingDossierNctId}
            onBack={handleBackToResults}
            onProceedToEnrollment={
              viewingPipeline.gateId && viewingPipeline.approvalStatus !== "approved"
                ? () => handleProceedToEnrollment(viewingDossierNctId)
                : null
            }
            approvalStatus={viewingPipeline.approvalStatus}
          />
        )}
      </div>
    </div>
  );
}
