import { useState, useEffect, useCallback } from "react";
import IntakeForm from "./components/IntakeForm";
import TrialResults from "./components/TrialResults";
import TrialDetail from "./components/TrialDetail";
import { matchTrials } from "./api";

const LOADING_MESSAGES = [
  "Searching ClinicalTrials.gov for recruiting studies...",
  "Found potential matches. Analyzing eligibility criteria...",
  "Reviewing inclusion and exclusion criteria against your profile...",
  "Evaluating biomarker and treatment history requirements...",
  "Calculating distances to trial sites near you...",
  "Ranking trials by match confidence...",
  "Almost there -- finalizing your personalized results...",
];

export default function App() {
  const [view, setView] = useState("intake"); // intake | loading | results | detail
  const [results, setResults] = useState(null);
  const [selectedTrial, setSelectedTrial] = useState(null);
  const [error, setError] = useState(null);
  const [loadingMsgIndex, setLoadingMsgIndex] = useState(0);

  useEffect(() => {
    if (view !== "loading") return;
    setLoadingMsgIndex(0);
    const interval = setInterval(() => {
      setLoadingMsgIndex((prev) =>
        prev < LOADING_MESSAGES.length - 1 ? prev + 1 : prev
      );
    }, 4000);
    return () => clearInterval(interval);
  }, [view]);

  const handleSubmit = async (patient) => {
    setView("loading");
    setError(null);
    try {
      const data = await matchTrials(patient);
      setResults(data);
      setView("results");
    } catch (err) {
      setError(err.message);
      setView("intake");
    }
  };

  const handleRetry = useCallback(() => {
    setError(null);
  }, []);

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
    setView("intake");
  };

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
          <button className="btn btn-secondary btn-sm" onClick={handleRetry}>
            Dismiss
          </button>
        </div>
      )}

      <div className={`view-container ${view}`}>
        {view === "intake" && <IntakeForm onSubmit={handleSubmit} />}

        {view === "loading" && (
          <div className="loading" role="status" aria-live="polite">
            <h2>Searching for your matches</h2>
            <div className="spinner" aria-hidden="true">
              <div className="spinner-ring" />
              <div className="spinner-ring spinner-ring-2" />
            </div>
            <p className="loading-message" key={loadingMsgIndex}>
              {LOADING_MESSAGES[loadingMsgIndex]}
            </p>
            <div className="loading-progress">
              <div className="loading-progress-bar" style={{
                width: `${((loadingMsgIndex + 1) / LOADING_MESSAGES.length) * 100}%`
              }} />
            </div>
            <p className="loading-patience">This typically takes 30-60 seconds</p>
          </div>
        )}

        {view === "results" && results && (
          <TrialResults data={results} onSelect={handleSelectTrial} onBack={handleStartOver} />
        )}

        {view === "detail" && selectedTrial && (
          <TrialDetail trial={selectedTrial} onBack={handleBackToResults} />
        )}
      </div>
    </div>
  );
}
