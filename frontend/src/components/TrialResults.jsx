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

function TrialCardActions({ nctId, pipeline, onAnalyzeTrial, onViewDossier, onProceedToEnrollment, onApproveEnrollment }) {
  if (!pipeline) {
    return (
      <div className="trial-card-actions" onClick={(e) => e.stopPropagation()}>
        <button className="btn btn-primary btn-sm" onClick={() => onAnalyzeTrial(nctId)}>
          Analyze Trial
        </button>
      </div>
    );
  }

  return (
    <div className="trial-card-actions" onClick={(e) => e.stopPropagation()}>
      {pipeline.status === "loading" && (
        <span className="agent-badge" style={{ fontSize: "0.8rem" }}>
          <span className="agent-dot" />
          Analyzing...
        </span>
      )}
      {pipeline.status === "error" && (
        <>
          <span style={{ color: "#ef4444", fontSize: "0.8rem" }}>Analysis failed</span>
          <button className="btn btn-secondary btn-sm" onClick={() => onAnalyzeTrial(nctId)}>
            Retry
          </button>
        </>
      )}
      {pipeline.status === "done" && (
        <>
          <button className="btn btn-secondary btn-sm" onClick={() => onViewDossier(nctId)}>
            View Dossier
          </button>
          {!pipeline.approvalStatus && (
            <button className="btn btn-primary btn-sm" onClick={() => onProceedToEnrollment(nctId)}>
              Proceed to Enrollment
            </button>
          )}
          {pipeline.approvalStatus === "approving" && (
            <span className="agent-badge" style={{ fontSize: "0.8rem" }}>
              <span className="agent-dot" />
              Starting enrollment...
            </span>
          )}
        </>
      )}
      {pipeline.approvalStatus === "approved" && (
        <>
          {pipeline.enrollmentStatus === "loading" && (
            <span className="agent-badge" style={{ fontSize: "0.8rem" }}>
              <span className="agent-dot" />
              Preparing enrollment...
            </span>
          )}
          {pipeline.enrollmentStatus === "done" && (
            <>
              <span className="criterion-status status-met" style={{ display: "inline-flex", width: "18px", height: "18px", fontSize: "0.65rem" }}>{"\u2713"}</span>
              <span style={{ fontSize: "0.8rem", color: "#059669" }}>Enrollment ready</span>
              {pipeline.enrollmentGateId && pipeline.enrollmentStatus !== "approved" && (
                <button className="btn btn-primary btn-sm" onClick={() => onApproveEnrollment(nctId)}>
                  Approve &amp; Send to Site
                </button>
              )}
            </>
          )}
          {pipeline.enrollmentStatus === "approved" && (
            <>
              <span className="criterion-status status-met" style={{ display: "inline-flex", width: "18px", height: "18px", fontSize: "0.65rem" }}>{"\u2713"}</span>
              <span style={{ fontSize: "0.8rem", color: "#059669" }}>Enrollment sent</span>
            </>
          )}
          {pipeline.outreachStatus === "loading" && (
            <span className="agent-badge" style={{ fontSize: "0.8rem" }}>
              <span className="agent-dot" />
              Outreach in progress...
            </span>
          )}
          {pipeline.outreachStatus === "done" && pipeline.outreachData && (
            <>
              <span className="criterion-status status-met" style={{ display: "inline-flex", width: "18px", height: "18px", fontSize: "0.65rem" }}>{"\u2713"}</span>
              <span style={{ fontSize: "0.8rem", color: "#059669" }}>
                Outreach ready ({pipeline.outreachData.contacts?.length || 0} contacts)
              </span>
            </>
          )}
        </>
      )}
    </div>
  );
}

export default function TrialResults({
  data, onSelect, onBack, onAnalyzeTrial, onViewDossier, onProceedToEnrollment,
  onApproveEnrollment, trialPipelines,
}) {
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

              <TrialCardActions
                nctId={trial.nct_id}
                pipeline={trialPipelines[trial.nct_id]}
                onAnalyzeTrial={onAnalyzeTrial}
                onViewDossier={onViewDossier}
                onProceedToEnrollment={onProceedToEnrollment}
                onApproveEnrollment={onApproveEnrollment}
              />
            </div>
          ))}

          <div className="results-footer">
            <button className="btn btn-secondary" onClick={onBack}>Start New Search</button>
          </div>
        </>
      )}
    </div>
  );
}
