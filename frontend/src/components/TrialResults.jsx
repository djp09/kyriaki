function scoreBadgeClass(score) {
  if (score >= 70) return "score-badge score-high";
  if (score >= 40) return "score-badge score-medium";
  return "score-badge score-low";
}

export default function TrialResults({ data, onSelect, onBack }) {
  return (
    <div className="results">
      <div className="results-header">
        <h2>Your Trial Matches</h2>
        <div className="patient-summary">{data.patient_summary}</div>
        <div className="stats">
          {data.total_trials_screened} trials screened &middot; {data.matches.length} match{data.matches.length !== 1 ? "es" : ""} found
        </div>
      </div>

      <div className="disclaimer">{data.disclaimer}</div>

      {data.matches.length === 0 && (
        <div style={{ textAlign: "center", padding: "2rem", color: "#666" }}>
          <p>No matching trials found within your travel range. Try increasing your travel distance or broadening your search.</p>
        </div>
      )}

      {data.matches.map((trial) => (
        <div key={trial.nct_id} className="trial-card" onClick={() => onSelect(trial)}>
          <div className="trial-card-header">
            <div className="trial-title">{trial.brief_title}</div>
            <div className={scoreBadgeClass(trial.match_score)}>{trial.match_score}%</div>
          </div>
          <div className="trial-meta">
            <span>{trial.nct_id}</span>
            <span>{trial.phase}</span>
            {trial.nearest_site && (
              <span>{trial.nearest_site.city}, {trial.nearest_site.state}</span>
            )}
            {trial.distance_miles != null && (
              <span>{trial.distance_miles} mi away</span>
            )}
          </div>
          <div className="trial-explanation">{trial.match_explanation}</div>
        </div>
      ))}

      <div style={{ textAlign: "center", marginTop: "2rem" }}>
        <button className="btn btn-secondary" onClick={onBack}>Start New Search</button>
      </div>
    </div>
  );
}
