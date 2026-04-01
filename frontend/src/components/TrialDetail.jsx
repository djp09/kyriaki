function statusClass(status) {
  if (status === "met" || status === "not_triggered") return "status-met";
  if (status === "not_met" || status === "triggered") return "status-not-met";
  return "status-unknown";
}

function statusLabel(status) {
  const labels = {
    met: "Met",
    not_met: "Not Met",
    unknown: "Unknown",
    not_triggered: "Clear",
    triggered: "Triggered",
  };
  return labels[status] || status;
}

function statusIcon(status) {
  if (status === "met" || status === "not_triggered") return "\u2713";
  if (status === "not_met" || status === "triggered") return "\u2717";
  return "?";
}

export default function TrialDetail({ trial, onBack }) {
  return (
    <div className="trial-detail fade-in">
      <button
        className="back-link"
        onClick={onBack}
        type="button"
        aria-label="Back to results"
      >
        <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16" aria-hidden="true">
          <path fillRule="evenodd" d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z" clipRule="evenodd" />
        </svg>
        Back to results
      </button>

      <h2>{trial.brief_title}</h2>
      <div className="trial-meta detail-meta">
        <span className="meta-tag">{trial.nct_id}</span>
        <span className="meta-tag">{trial.phase}</span>
        <span className="meta-tag">{trial.overall_status}</span>
        {trial.nearest_site && (
          <span className="meta-tag">{trial.nearest_site.facility} -- {trial.nearest_site.city}, {trial.nearest_site.state}</span>
        )}
        {trial.distance_miles != null && <span className="meta-tag">{trial.distance_miles} mi away</span>}
      </div>

      <div className="match-score-banner">
        <div className="match-score-number">
          <span className="match-score-value">{trial.match_score}%</span>
          <span className="match-score-label">Match Score</span>
        </div>
        <p className="match-score-explanation">{trial.match_explanation}</p>
      </div>

      <div className="detail-section">
        <h3>About This Trial</h3>
        <p className="detail-body">{trial.brief_summary}</p>
      </div>

      {trial.interventions.length > 0 && (
        <div className="detail-section">
          <h3>Treatments Involved</h3>
          <ul className="intervention-list">
            {trial.interventions.map((int, i) => (
              <li key={i}>{int}</li>
            ))}
          </ul>
        </div>
      )}

      {trial.inclusion_evaluations.length > 0 && (
        <div className="detail-section">
          <h3>Inclusion Criteria</h3>
          <ul className="criteria-list">
            {trial.inclusion_evaluations.map((ev, i) => (
              <li key={i} className="criteria-item">
                <span className={`criteria-status ${statusClass(ev.status)}`} aria-label={statusLabel(ev.status)}>
                  {statusIcon(ev.status)}
                </span>
                <div className="criteria-content">
                  <div className="criteria-criterion">{ev.criterion}</div>
                  <div className="criteria-explanation">{ev.explanation}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {trial.exclusion_evaluations.length > 0 && (
        <div className="detail-section">
          <h3>Exclusion Criteria</h3>
          <ul className="criteria-list">
            {trial.exclusion_evaluations.map((ev, i) => (
              <li key={i} className="criteria-item">
                <span className={`criteria-status ${statusClass(ev.status)}`} aria-label={statusLabel(ev.status)}>
                  {statusIcon(ev.status)}
                </span>
                <div className="criteria-content">
                  <div className="criteria-criterion">{ev.criterion}</div>
                  <div className="criteria-explanation">{ev.explanation}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {trial.flags_for_oncologist.length > 0 && (
        <div className="detail-section">
          <div className="flags">
            <h3>Discuss With Your Oncologist</h3>
            <ul>
              {trial.flags_for_oncologist.map((flag, i) => (
                <li key={i}>{flag}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="detail-actions">
        <a
          href={`https://clinicaltrials.gov/study/${trial.nct_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-primary"
        >
          View on ClinicalTrials.gov
          <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14" aria-hidden="true" style={{ marginLeft: "0.4rem" }}>
            <path fillRule="evenodd" d="M4.25 5.5a.75.75 0 00-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 00.75-.75v-4a.75.75 0 011.5 0v4A2.25 2.25 0 0112.75 17h-8.5A2.25 2.25 0 012 14.75v-8.5A2.25 2.25 0 014.25 4h5a.75.75 0 010 1.5h-5zm7.5-2.25a.75.75 0 01.75-.75h4.5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0V5.56l-5.22 5.22a.75.75 0 11-1.06-1.06l5.22-5.22h-2.69a.75.75 0 01-.75-.75z" clipRule="evenodd" />
          </svg>
        </a>
        <button className="btn btn-secondary" onClick={onBack} type="button">
          Back to results
        </button>
      </div>
    </div>
  );
}
