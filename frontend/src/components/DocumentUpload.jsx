import { useState, useRef, useCallback } from "react";
import { uploadDocument } from "../api";

const ACCEPTED = ".pdf,.png,.jpg,.jpeg,.gif,.webp";
const MAX_SIZE_MB = 10;

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function docTypeLabel(type) {
  const labels = {
    pathology_report: "Pathology Report",
    treatment_summary: "Treatment Summary",
    lab_results: "Lab Results",
    radiology_report: "Radiology Report",
    clinical_note: "Clinical Note",
    other: "Medical Document",
  };
  return labels[type] || "Document";
}

export default function DocumentUpload({ onExtracted, onSkip }) {
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  const handleFile = useCallback(async (f) => {
    if (f.size > MAX_SIZE_MB * 1024 * 1024) {
      setError(`File too large (${formatFileSize(f.size)}). Maximum is ${MAX_SIZE_MB}MB.`);
      return;
    }
    setFile(f);
    setError(null);
    setResult(null);
    setUploading(true);

    try {
      const data = await uploadDocument(f);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, [handleFile]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleInputChange = useCallback((e) => {
    const f = e.target.files[0];
    if (f) handleFile(f);
  }, [handleFile]);

  const handleUseResults = () => {
    if (result?.extracted) {
      onExtracted(result.extracted, result.document_type);
    }
  };

  const handleRetry = () => {
    setFile(null);
    setResult(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  // Show extraction results
  if (result) {
    const ext = result.extracted || {};
    const confidence = result.confidence || 0;
    const fieldsFound = Object.entries(ext).filter(
      ([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0) && !(typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0)
    );

    return (
      <div className="doc-upload">
        <div className="doc-result">
          <div className="doc-result-header">
            <svg viewBox="0 0 20 20" fill="currentColor" width="24" height="24" className="doc-result-icon">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd" />
            </svg>
            <div>
              <h3>{docTypeLabel(result.document_type)} Analyzed</h3>
              <p className="doc-confidence">
                Confidence: <strong>{Math.round(confidence * 100)}%</strong>
                {confidence < 0.5 && <span className="doc-low-confidence"> -- Review carefully</span>}
              </p>
            </div>
          </div>

          <div className="doc-fields">
            <h4>Extracted Information ({fieldsFound.length} fields)</h4>
            <dl className="doc-field-list">
              {ext.cancer_type && (
                <div className="doc-field-row">
                  <dt>Cancer Type</dt>
                  <dd>{ext.cancer_type}</dd>
                </div>
              )}
              {ext.cancer_stage && (
                <div className="doc-field-row">
                  <dt>Stage</dt>
                  <dd>{ext.cancer_stage}</dd>
                </div>
              )}
              {ext.biomarkers?.length > 0 && (
                <div className="doc-field-row">
                  <dt>Biomarkers</dt>
                  <dd>{ext.biomarkers.join(", ")}</dd>
                </div>
              )}
              {ext.prior_treatments?.length > 0 && (
                <div className="doc-field-row">
                  <dt>Prior Treatments</dt>
                  <dd>{ext.prior_treatments.join(", ")}</dd>
                </div>
              )}
              {ext.lines_of_therapy != null && (
                <div className="doc-field-row">
                  <dt>Lines of Therapy</dt>
                  <dd>{ext.lines_of_therapy}</dd>
                </div>
              )}
              {ext.age != null && (
                <div className="doc-field-row">
                  <dt>Age</dt>
                  <dd>{ext.age}</dd>
                </div>
              )}
              {ext.sex && (
                <div className="doc-field-row">
                  <dt>Sex</dt>
                  <dd>{ext.sex}</dd>
                </div>
              )}
              {ext.ecog_score != null && (
                <div className="doc-field-row">
                  <dt>ECOG Score</dt>
                  <dd>{ext.ecog_score}</dd>
                </div>
              )}
              {ext.key_labs && Object.keys(ext.key_labs).length > 0 && (
                <div className="doc-field-row">
                  <dt>Lab Values</dt>
                  <dd>{Object.entries(ext.key_labs).map(([k, v]) => `${k}: ${v}`).join(", ")}</dd>
                </div>
              )}
              {ext.additional_conditions?.length > 0 && (
                <div className="doc-field-row">
                  <dt>Other Conditions</dt>
                  <dd>{ext.additional_conditions.join(", ")}</dd>
                </div>
              )}
            </dl>
            {result.extraction_notes && (
              <p className="doc-notes">{result.extraction_notes}</p>
            )}
          </div>

          <div className="doc-actions">
            <button className="btn btn-primary" onClick={handleUseResults}>
              Use These Results
            </button>
            <button className="btn btn-secondary" onClick={handleRetry}>
              Upload Different Document
            </button>
          </div>
          <p className="doc-disclaimer">
            Please review and correct any extracted information before proceeding. AI extraction may not be 100% accurate.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="doc-upload">
      <h2 className="step-heading">Upload Medical Records</h2>
      <p className="step-description">
        Speed up your intake by uploading a pathology report, treatment summary, or lab results.
        We will extract your information automatically.
      </p>

      <div
        className={`doc-dropzone ${dragOver ? "doc-dropzone-active" : ""} ${uploading ? "doc-dropzone-uploading" : ""}`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => !uploading && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Upload document"
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          onChange={handleInputChange}
          className="doc-file-input"
          aria-hidden="true"
          tabIndex={-1}
        />

        {uploading ? (
          <div className="doc-uploading">
            <div className="spinner" aria-hidden="true">
              <div className="spinner-ring" />
              <div className="spinner-ring spinner-ring-2" />
            </div>
            <p>Analyzing {file?.name}...</p>
            <p className="doc-upload-hint">This typically takes 5-10 seconds</p>
          </div>
        ) : (
          <div className="doc-idle">
            <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48" className="doc-upload-icon">
              <path d="M24 32V16m0 0l-6 6m6-6l6 6" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M8 32v4a4 4 0 004 4h24a4 4 0 004-4v-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <p className="doc-upload-label">
              <strong>Drop a file here</strong> or click to browse
            </p>
            <p className="doc-upload-hint">
              PDF, PNG, JPG up to {MAX_SIZE_MB}MB
            </p>
          </div>
        )}
      </div>

      {error && (
        <div className="doc-error" role="alert">
          <strong>Upload failed:</strong> {error}
          <button className="btn btn-secondary btn-sm" onClick={handleRetry} style={{ marginLeft: "0.5rem" }}>
            Try Again
          </button>
        </div>
      )}

      <div className="doc-skip">
        <button className="btn btn-secondary" onClick={onSkip}>
          Skip -- I will enter my information manually
        </button>
      </div>
    </div>
  );
}
