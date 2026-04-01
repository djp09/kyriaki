function scoreBadgeClass(score) {
  if (score >= 70) return "score-badge score-high";
  if (score >= 40) return "score-badge score-medium";
  return "score-badge score-low";
}

function scoreLabel(score) {
  if (score >= 70) return "Strong match";
  if (score >= 40) return "Possible match";
  return "Low match";
}

export default function TrialResults({ data, onSelect, onBack, onDossier, onViewDossier, dossierStatus }) {
  return (
    <div className="results fade-in">
      <div className="results-header">
        <h2>Your Trial Matches</h2>
        <div className="patient-summary">{data.patient_summary}</div>
        <div className="stats">
          {data.total_trials_screened} trials screened &middot; {data.matches.length} match{data.matches.length !== 1 ? "es" : ""} found
        </div>
      </div>

      <div className="disclaimer" role="note">
        <svg className="disclaimer-icon" viewBox="0 0 20 20" fill="currentColor" width="18" height="18" aria-hidden="true">
          <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
        </svg>
        <span>{data.disclaimer}</span>
      </div>

      {data.matches.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48">
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
          </div>
          <h3>No matching trials found</h3>
          <p>We could not find trials within your travel range that match your profile. You can try:</p>
          <ul className="empty-state-suggestions">
            <li>Increasing your travel distance</li>
            <li>Checking if all profile details are accurate</li>
            <li>Asking your oncologist about other options</li>
          </ul>
          <button className="btn btn-primary" onClick={onBack} style={{ marginTop: "1.5rem" }}>
            Start New Search
          </button>
        </div>
      ) : (
        <>
          {data.matches.map((trial, index) => (
            <div
              key={trial.nct_id}
              className="trial-card"
              onClick={() => onSelect(trial)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(trial); } }}
              role="button"
              tabIndex={0}
              aria-label={`${trial.brief_title}, ${trial.match_score}% match. Click for details.`}
              style={{ animationDelay: `${index * 0.05}s` }}
            >
              <div className="trial-card-header">
                <div className="trial-title">{trial.brief_title}</div>
                <div className={scoreBadgeClass(trial.match_score)} title={scoreLabel(trial.match_score)}>
                  {trial.match_score}%
                </div>
              </div>
              <div className="trial-meta">
                <span className="meta-tag">{trial.nct_id}</span>
                <span className="meta-tag">{trial.phase}</span>
                {trial.nearest_site && (
                  <span className="meta-tag">{trial.nearest_site.city}, {trial.nearest_site.state}</span>
                )}
                {trial.distance_miles != null && (
                  <span className="meta-tag">{trial.distance_miles} mi away</span>
                )}
              </div>
              <div className="trial-explanation">{trial.match_explanation}</div>
              <div className="trial-card-cta" aria-hidden="true">
                View details
                <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
                  <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
                </svg>
              </div>
            </div>
          ))}

          <div className="results-footer">
            {data.task_id && onDossier && dossierStatus !== "done" && (
              <button
                className="btn btn-primary"
                onClick={onDossier}
                disabled={dossierStatus === "loading"}
              >
                {dossierStatus === "loading"
                  ? "Generating deep analysis..."
                  : "Generate Eligibility Dossier"}
              </button>
            )}
            {dossierStatus === "done" && onViewDossier && (
              <button className="btn btn-primary" onClick={onViewDossier}>
                View Eligibility Dossier
              </button>
            )}
            <button className="btn btn-secondary" onClick={onBack}>Start New Search</button>
          </div>
        </>
      )}
    </div>
  );
}
