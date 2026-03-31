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

export default function TrialDetail({ trial, onBack }) {
  return (
    <div className="trial-detail">
      <span className="back-link" onClick={onBack}>&larr; Back to results</span>

      <h2>{trial.brief_title}</h2>
      <div className="trial-meta" style={{ marginBottom: "1rem" }}>
        <span>{trial.nct_id}</span>
        <span>{trial.phase}</span>
        <span>{trial.overall_status}</span>
        {trial.nearest_site && (
          <span>{trial.nearest_site.facility} &mdash; {trial.nearest_site.city}, {trial.nearest_site.state}</span>
        )}
        {trial.distance_miles != null && <span>{trial.distance_miles} mi away</span>}
      </div>

      <div className="patient-summary" style={{ background: "#e8f5e9" }}>
        <strong>Match Score: {trial.match_score}%</strong> &mdash; {trial.match_explanation}
      </div>

      <div className="detail-section">
        <h3>About This Trial</h3>
        <p style={{ fontSize: "0.93rem", color: "#444" }}>{trial.brief_summary}</p>
      </div>

      {trial.interventions.length > 0 && (
        <div className="detail-section">
          <h3>Treatments Involved</h3>
          <ul style={{ marginLeft: "1.25rem" }}>
            {trial.interventions.map((int, i) => (
              <li key={i} style={{ fontSize: "0.9rem", marginBottom: "0.25rem" }}>{int}</li>
            ))}
          </ul>
        </div>
      )}

      {trial.inclusion_evaluations.length > 0 && (
        <div className="detail-section">
          <h3>Inclusion Criteria</h3>
          <ul className="criteria-list">
            {trial.inclusion_evaluations.map((ev, i) => (
              <li key={i}>
                <span className={statusClass(ev.status)}>[{statusLabel(ev.status)}]</span>{" "}
                {ev.criterion}
                <div style={{ fontSize: "0.85rem", color: "#666", marginTop: "0.15rem" }}>{ev.explanation}</div>
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
              <li key={i}>
                <span className={statusClass(ev.status)}>[{statusLabel(ev.status)}]</span>{" "}
                {ev.criterion}
                <div style={{ fontSize: "0.85rem", color: "#666", marginTop: "0.15rem" }}>{ev.explanation}</div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {trial.flags_for_oncologist.length > 0 && (
        <div className="detail-section">
          <div className="flags">
            <h3 style={{ marginBottom: "0.5rem" }}>Discuss With Your Oncologist</h3>
            <ul>
              {trial.flags_for_oncologist.map((flag, i) => (
                <li key={i}>{flag}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="detail-section" style={{ textAlign: "center" }}>
        <a
          href={`https://clinicaltrials.gov/study/${trial.nct_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-primary"
          style={{ display: "inline-block", textDecoration: "none" }}
        >
          View on ClinicalTrials.gov
        </a>
      </div>
    </div>
  );
}
