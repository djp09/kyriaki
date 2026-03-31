import { useState } from "react";
import IntakeForm from "./components/IntakeForm";
import TrialResults from "./components/TrialResults";
import TrialDetail from "./components/TrialDetail";
import { matchTrials } from "./api";

export default function App() {
  const [view, setView] = useState("intake"); // intake | loading | results | detail
  const [results, setResults] = useState(null);
  const [selectedTrial, setSelectedTrial] = useState(null);
  const [error, setError] = useState(null);

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
        <p>Find clinical trials matched to you</p>
      </header>

      {error && <div className="error">{error}</div>}

      {view === "intake" && <IntakeForm onSubmit={handleSubmit} />}

      {view === "loading" && (
        <div className="loading">
          <h2>Searching for your matches...</h2>
          <div className="spinner" />
          <p>We are searching active clinical trials and analyzing eligibility criteria for you. This may take a minute.</p>
        </div>
      )}

      {view === "results" && results && (
        <TrialResults data={results} onSelect={handleSelectTrial} onBack={handleStartOver} />
      )}

      {view === "detail" && selectedTrial && (
        <TrialDetail trial={selectedTrial} onBack={handleBackToResults} />
      )}
    </div>
  );
}
