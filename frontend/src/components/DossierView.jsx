function statusIcon(status) {
  if (status === "met") return { symbol: "\u2713", cls: "status-met" };
  if (status === "not_met") return { symbol: "\u2717", cls: "status-not-met" };
  if (status === "needs_verification") return { symbol: "!", cls: "status-verify" };
  return { symbol: "?", cls: "status-unknown" };
}

function scoreBadgeClass(score) {
  if (score >= 70) return "score-badge score-high";
  if (score >= 40) return "score-badge score-medium";
  return "score-badge score-low";
}

export default function DossierView({ dossier, nctId, onBack, onProceedToEnrollment, approvalStatus }) {
  if (!dossier) return null;

  return (
    <div className="dossier-view fade-in">
      <button className="back-link" onClick={onBack}>
        <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
          <path fillRule="evenodd" d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z" clipRule="evenodd" />
        </svg>
        Back to results
      </button>

      <div className="dossier-header">
        <h2>Eligibility Dossier</h2>
        <p className="dossier-subtitle">
          Deep analysis by Kyriaki's clinical reasoning agent. Review with your oncologist.
        </p>
        {dossier.generated_at && (
          <span className="dossier-timestamp">
            Generated {new Date(dossier.generated_at).toLocaleString()}
          </span>
        )}
      </div>

      {dossier.sections.map((section, idx) => (
        <div key={section.nct_id || idx} className="dossier-section">
          <div className="dossier-section-header">
            <div>
              <h3>{section.brief_title}</h3>
              <span className="meta-tag">{section.nct_id}</span>
            </div>
            {section.revised_score != null && (
              <div className={scoreBadgeClass(section.revised_score)}>
                {section.revised_score}%
              </div>
            )}
          </div>

          {section.analysis_error ? (
            <div className="dossier-error">
              Analysis could not be completed for this trial. Please review manually with your oncologist.
            </div>
          ) : (
            <>
              {section.score_justification && (
                <div className="dossier-justification">
                  <h4>Score Justification</h4>
                  <p>{section.score_justification}</p>
                </div>
              )}

              {section.patient_summary && (
                <div className="dossier-patient-summary">
                  <h4>What This Means For You</h4>
                  <p>{section.patient_summary}</p>
                </div>
              )}

              {section.criteria_analysis && section.criteria_analysis.length > 0 && (
                <div className="dossier-criteria">
                  <h4>Criterion-by-Criterion Analysis</h4>
                  <div className="criteria-list">
                    {section.criteria_analysis.map((c, i) => {
                      const icon = statusIcon(c.status);
                      return (
                        <div key={i} className="criterion-row">
                          <div className={`criterion-status ${icon.cls}`}>
                            {icon.symbol}
                          </div>
                          <div className="criterion-detail">
                            <div className="criterion-text">
                              <span className="criterion-type-tag">{c.type}</span>
                              {c.criterion}
                            </div>
                            <div className="criterion-evidence">{c.evidence}</div>
                            {c.notes && <div className="criterion-notes">{c.notes}</div>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {section.clinical_summary && (
                <div className="dossier-clinical">
                  <h4>Clinical Summary (for Navigator/Coordinator)</h4>
                  <p>{section.clinical_summary}</p>
                </div>
              )}

              {section.next_steps && section.next_steps.length > 0 && (
                <div className="dossier-next-steps">
                  <h4>Recommended Next Steps</h4>
                  <ol>
                    {section.next_steps.map((step, i) => (
                      <li key={i}>{step}</li>
                    ))}
                  </ol>
                </div>
              )}

              {section.flags && section.flags.length > 0 && (
                <div className="dossier-flags">
                  <h4>Items Needing Verification</h4>
                  <ul>
                    {section.flags.map((flag, i) => (
                      <li key={i}>{flag}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      ))}

      <div className="dossier-footer">
        <div className="disclaimer" role="note">
          <svg className="disclaimer-icon" viewBox="0 0 20 20" fill="currentColor" width="18" height="18" aria-hidden="true">
            <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
          </svg>
          <span>
            This dossier is generated by AI and is for informational purposes only.
            All findings must be verified by your oncologist before taking any action.
          </span>
        </div>
        {approvalStatus === "approved" ? (
          <div className="approval-badge" style={{ marginTop: "1rem" }}>
            <span className="criterion-status status-met" style={{ display: "inline-flex", width: "22px", height: "22px", fontSize: "0.7rem", verticalAlign: "middle", marginRight: "0.5rem" }}>{"\u2713"}</span>
            <strong>Enrollment started</strong>
          </div>
        ) : onProceedToEnrollment && (
          <button
            className="btn btn-primary"
            onClick={onProceedToEnrollment}
            disabled={approvalStatus === "approving"}
            style={{ marginTop: "1rem" }}
          >
            {approvalStatus === "approving" ? "Starting enrollment..." : "Proceed to Enrollment"}
          </button>
        )}
        <button className="btn btn-secondary" onClick={onBack} style={{ marginTop: "1rem", marginLeft: "0.75rem" }}>
          Back to Results
        </button>
      </div>
    </div>
  );
}
