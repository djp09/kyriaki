import { useState, useRef, useEffect } from "react";

const CANCER_TYPES = [
  "Non-Small Cell Lung Cancer",
  "Small Cell Lung Cancer",
  "Triple-Negative Breast Cancer",
  "HER2+ Breast Cancer",
  "Hormone Receptor+ Breast Cancer",
  "Colorectal Cancer",
  "Pancreatic Cancer",
  "Acute Lymphoblastic Leukemia",
  "Neuroblastoma",
  "Wilms Tumor",
  "Osteosarcoma",
  "Ewing Sarcoma",
  "Rhabdomyosarcoma",
];

const STAGES = ["Stage I", "Stage II", "Stage IIA", "Stage IIB", "Stage III", "Stage IIIA", "Stage IIIB", "Stage IV", "Stage IVA", "Stage IVB", "Recurrent", "Metastatic"];

const INITIAL = {
  cancer_type: "",
  cancer_stage: "",
  biomarkers: "",
  prior_treatments: "",
  lines_of_therapy: 0,
  age: "",
  sex: "",
  ecog_score: "",
  key_labs_wbc: "",
  key_labs_platelets: "",
  key_labs_hemoglobin: "",
  key_labs_creatinine: "",
  location_zip: "",
  willing_to_travel_miles: 50,
  additional_conditions: "",
  additional_notes: "",
};

function validate(form, step) {
  const errors = {};
  if (step === 0) {
    if (!form.cancer_type) errors.cancer_type = "Please select a cancer type.";
    if (!form.cancer_stage) errors.cancer_stage = "Please select a stage.";
  }
  if (step === 2) {
    if (!form.age) {
      errors.age = "Age is required.";
    } else {
      const ageNum = parseInt(form.age, 10);
      if (isNaN(ageNum) || ageNum < 0 || ageNum > 120) {
        errors.age = "Enter a valid age (0-120).";
      }
    }
    if (!form.sex) errors.sex = "Please select sex.";
  }
  if (step === 3) {
    if (form.key_labs_wbc && (isNaN(parseFloat(form.key_labs_wbc)) || parseFloat(form.key_labs_wbc) < 0)) {
      errors.key_labs_wbc = "Enter a valid number.";
    }
    if (form.key_labs_platelets && (isNaN(parseFloat(form.key_labs_platelets)) || parseFloat(form.key_labs_platelets) < 0)) {
      errors.key_labs_platelets = "Enter a valid number.";
    }
    if (form.key_labs_hemoglobin && (isNaN(parseFloat(form.key_labs_hemoglobin)) || parseFloat(form.key_labs_hemoglobin) < 0)) {
      errors.key_labs_hemoglobin = "Enter a valid number.";
    }
    if (form.key_labs_creatinine && (isNaN(parseFloat(form.key_labs_creatinine)) || parseFloat(form.key_labs_creatinine) < 0)) {
      errors.key_labs_creatinine = "Enter a valid number.";
    }
  }
  if (step === 4) {
    if (!form.location_zip) {
      errors.location_zip = "ZIP code is required.";
    } else if (!/^\d{5}(-\d{4})?$/.test(form.location_zip.trim())) {
      errors.location_zip = "Enter a valid 5-digit ZIP code.";
    }
    if (form.willing_to_travel_miles && parseInt(form.willing_to_travel_miles) < 0) {
      errors.willing_to_travel_miles = "Distance must be positive.";
    }
  }
  return errors;
}

export default function IntakeForm({ onSubmit, prefill }) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState(INITIAL);
  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState({});
  const [direction, setDirection] = useState(1); // 1 = forward, -1 = backward
  const [prefillApplied, setPrefillApplied] = useState(false);
  const stepRef = useRef(null);

  // Apply prefill from document extraction (once)
  useEffect(() => {
    if (!prefill || prefillApplied) return;
    const next = { ...INITIAL };
    if (prefill.cancer_type) next.cancer_type = prefill.cancer_type;
    if (prefill.cancer_stage) next.cancer_stage = prefill.cancer_stage;
    if (Array.isArray(prefill.biomarkers) && prefill.biomarkers.length > 0) {
      next.biomarkers = prefill.biomarkers.join(", ");
    }
    if (Array.isArray(prefill.prior_treatments) && prefill.prior_treatments.length > 0) {
      next.prior_treatments = prefill.prior_treatments.join(", ");
    }
    if (prefill.lines_of_therapy != null) next.lines_of_therapy = prefill.lines_of_therapy;
    if (prefill.age != null) next.age = String(prefill.age);
    if (prefill.sex) next.sex = prefill.sex;
    if (prefill.ecog_score != null) next.ecog_score = String(prefill.ecog_score);
    if (prefill.key_labs) {
      if (prefill.key_labs.wbc) next.key_labs_wbc = String(prefill.key_labs.wbc);
      if (prefill.key_labs.platelets) next.key_labs_platelets = String(prefill.key_labs.platelets);
      if (prefill.key_labs.hemoglobin) next.key_labs_hemoglobin = String(prefill.key_labs.hemoglobin);
      if (prefill.key_labs.creatinine) next.key_labs_creatinine = String(prefill.key_labs.creatinine);
    }
    if (Array.isArray(prefill.additional_conditions) && prefill.additional_conditions.length > 0) {
      next.additional_conditions = prefill.additional_conditions.join(", ");
    }
    if (prefill.additional_notes) next.additional_notes = prefill.additional_notes;
    setForm(next);
    setPrefillApplied(true);
  }, [prefill, prefillApplied]);

  const steps = [
    { title: "Cancer Information", description: "Tell us about your diagnosis.", fields: ["cancer_type", "cancer_stage", "biomarkers"] },
    { title: "Treatment History", description: "What treatments have you received so far?", fields: ["prior_treatments", "lines_of_therapy"] },
    { title: "About You", description: "Basic information to match eligibility criteria.", fields: ["age", "sex", "ecog_score", "additional_conditions"] },
    { title: "Lab Values", description: "Recent lab results improve match accuracy. All fields are optional.", fields: ["key_labs_wbc", "key_labs_platelets", "key_labs_hemoglobin", "key_labs_creatinine"] },
    { title: "Location & Preferences", description: "Where should we look for trials?", fields: ["location_zip", "willing_to_travel_miles", "additional_notes"] },
  ];

  // Focus the step heading when step changes for accessibility
  useEffect(() => {
    if (stepRef.current) {
      stepRef.current.focus();
    }
  }, [step]);

  const set = (field) => (e) => {
    setForm({ ...form, [field]: e.target.value });
    // Clear error for this field on change
    if (errors[field]) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  };

  const handleBlur = (field) => () => {
    setTouched((prev) => ({ ...prev, [field]: true }));
    const stepErrors = validate(form, step);
    if (stepErrors[field]) {
      setErrors((prev) => ({ ...prev, [field]: stepErrors[field] }));
    }
  };

  const buildPayload = () => {
    const labs = {};
    if (form.key_labs_wbc) labs.wbc = parseFloat(form.key_labs_wbc);
    if (form.key_labs_platelets) labs.platelets = parseFloat(form.key_labs_platelets);
    if (form.key_labs_hemoglobin) labs.hemoglobin = parseFloat(form.key_labs_hemoglobin);
    if (form.key_labs_creatinine) labs.creatinine = parseFloat(form.key_labs_creatinine);

    return {
      cancer_type: form.cancer_type,
      cancer_stage: form.cancer_stage,
      biomarkers: form.biomarkers ? form.biomarkers.split(",").map((s) => s.trim()).filter(Boolean) : [],
      prior_treatments: form.prior_treatments ? form.prior_treatments.split(",").map((s) => s.trim()).filter(Boolean) : [],
      lines_of_therapy: parseInt(form.lines_of_therapy) || 0,
      age: parseInt(form.age),
      sex: form.sex,
      ecog_score: form.ecog_score !== "" ? parseInt(form.ecog_score) : null,
      key_labs: Object.keys(labs).length > 0 ? labs : null,
      location_zip: form.location_zip.trim(),
      willing_to_travel_miles: parseInt(form.willing_to_travel_miles) || 50,
      additional_conditions: form.additional_conditions ? form.additional_conditions.split(",").map((s) => s.trim()).filter(Boolean) : [],
      additional_notes: form.additional_notes || null,
    };
  };

  const canAdvance = () => {
    const stepErrors = validate(form, step);
    return Object.keys(stepErrors).length === 0;
  };

  const handleNext = () => {
    const stepErrors = validate(form, step);
    if (Object.keys(stepErrors).length > 0) {
      setErrors(stepErrors);
      // Mark all fields in this step as touched
      const touchAll = {};
      steps[step].fields.forEach((f) => { touchAll[f] = true; });
      setTouched((prev) => ({ ...prev, ...touchAll }));
      return;
    }
    setDirection(1);
    setStep(step + 1);
  };

  const handlePrev = () => {
    setDirection(-1);
    setStep(step - 1);
  };

  const handleSubmit = () => {
    const stepErrors = validate(form, step);
    if (Object.keys(stepErrors).length > 0) {
      setErrors(stepErrors);
      return;
    }
    onSubmit(buildPayload());
  };

  const fieldError = (field) => {
    if (touched[field] && errors[field]) return errors[field];
    return null;
  };

  const fieldClass = (field) => {
    return fieldError(field) ? "field field-error" : "field";
  };

  const fieldId = (field) => `field-${field}`;
  const errorId = (field) => `error-${field}`;

  return (
    <div className="intake-form">
      <div className="step-indicator" role="navigation" aria-label="Form progress">
        {steps.map((s, i) => (
          <button
            key={i}
            className={`step-dot ${i === step ? "active" : i < step ? "done" : ""}`}
            onClick={i < step ? () => { setDirection(-1); setStep(i); } : undefined}
            disabled={i >= step}
            aria-label={`Step ${i + 1}: ${s.title}${i < step ? " (completed)" : i === step ? " (current)" : ""}`}
            aria-current={i === step ? "step" : undefined}
            type="button"
          />
        ))}
      </div>

      <div className={`form-step ${direction > 0 ? "slide-in-right" : "slide-in-left"}`} key={step}>
        <h2 ref={stepRef} tabIndex={-1} className="step-heading">
          {steps[step].title}
        </h2>
        <p className="step-description">{steps[step].description}</p>

        {step === 0 && (
          <>
            <div className={fieldClass("cancer_type")}>
              <label htmlFor={fieldId("cancer_type")}>Cancer Type</label>
              <select
                id={fieldId("cancer_type")}
                value={form.cancer_type}
                onChange={set("cancer_type")}
                onBlur={handleBlur("cancer_type")}
                aria-required="true"
                aria-invalid={!!fieldError("cancer_type")}
                aria-describedby={fieldError("cancer_type") ? errorId("cancer_type") : undefined}
              >
                <option value="">Select cancer type...</option>
                {CANCER_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              {fieldError("cancer_type") && <div className="field-error-msg" id={errorId("cancer_type")} role="alert">{fieldError("cancer_type")}</div>}
            </div>
            <div className={fieldClass("cancer_stage")}>
              <label htmlFor={fieldId("cancer_stage")}>Stage</label>
              <select
                id={fieldId("cancer_stage")}
                value={form.cancer_stage}
                onChange={set("cancer_stage")}
                onBlur={handleBlur("cancer_stage")}
                aria-required="true"
                aria-invalid={!!fieldError("cancer_stage")}
                aria-describedby={fieldError("cancer_stage") ? errorId("cancer_stage") : undefined}
              >
                <option value="">Select stage...</option>
                {STAGES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              {fieldError("cancer_stage") && <div className="field-error-msg" id={errorId("cancer_stage")} role="alert">{fieldError("cancer_stage")}</div>}
            </div>
            <div className="field">
              <label htmlFor={fieldId("biomarkers")}>Biomarkers</label>
              <input
                id={fieldId("biomarkers")}
                type="text"
                placeholder="e.g., EGFR+, PD-L1 80%, ALK-"
                value={form.biomarkers}
                onChange={set("biomarkers")}
                aria-describedby="hint-biomarkers"
              />
              <div className="hint" id="hint-biomarkers">Comma-separated. Leave blank if unknown.</div>
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <div className="field">
              <label htmlFor={fieldId("prior_treatments")}>Prior Treatments</label>
              <textarea
                id={fieldId("prior_treatments")}
                rows={3}
                placeholder="e.g., Carboplatin/Pemetrexed, Pembrolizumab"
                value={form.prior_treatments}
                onChange={set("prior_treatments")}
                aria-describedby="hint-treatments"
              />
              <div className="hint" id="hint-treatments">Comma-separated list of treatments you have received.</div>
            </div>
            <div className="field">
              <label htmlFor={fieldId("lines_of_therapy")}>Lines of Therapy</label>
              <select id={fieldId("lines_of_therapy")} value={form.lines_of_therapy} onChange={set("lines_of_therapy")}>
                {[0, 1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>{n === 0 ? "None (treatment-naive)" : `${n} line${n > 1 ? "s" : ""}`}</option>
                ))}
              </select>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div className="field-row">
              <div className={fieldClass("age")}>
                <label htmlFor={fieldId("age")}>Age</label>
                <input
                  id={fieldId("age")}
                  type="number"
                  min="0"
                  max="120"
                  value={form.age}
                  onChange={set("age")}
                  onBlur={handleBlur("age")}
                  aria-required="true"
                  aria-invalid={!!fieldError("age")}
                  aria-describedby={fieldError("age") ? errorId("age") : undefined}
                />
                {fieldError("age") && <div className="field-error-msg" id={errorId("age")} role="alert">{fieldError("age")}</div>}
              </div>
              <div className={fieldClass("sex")}>
                <label htmlFor={fieldId("sex")}>Sex</label>
                <select
                  id={fieldId("sex")}
                  value={form.sex}
                  onChange={set("sex")}
                  onBlur={handleBlur("sex")}
                  aria-required="true"
                  aria-invalid={!!fieldError("sex")}
                  aria-describedby={fieldError("sex") ? errorId("sex") : undefined}
                >
                  <option value="">Select...</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                </select>
                {fieldError("sex") && <div className="field-error-msg" id={errorId("sex")} role="alert">{fieldError("sex")}</div>}
              </div>
            </div>
            <div className="field">
              <label htmlFor={fieldId("ecog_score")}>ECOG Performance Status</label>
              <select id={fieldId("ecog_score")} value={form.ecog_score} onChange={set("ecog_score")} aria-describedby="hint-ecog">
                <option value="">Not sure / skip</option>
                <option value="0">0 -- Fully active</option>
                <option value="1">1 -- Restricted but ambulatory</option>
                <option value="2">2 -- Ambulatory, capable of self-care</option>
                <option value="3">3 -- Limited self-care, confined to bed/chair 50%+</option>
                <option value="4">4 -- Completely disabled</option>
              </select>
              <div className="hint" id="hint-ecog">Your doctor can help you determine this. It is ok to skip.</div>
            </div>
            <div className="field">
              <label htmlFor={fieldId("additional_conditions")}>Other Medical Conditions</label>
              <input
                id={fieldId("additional_conditions")}
                type="text"
                placeholder="e.g., diabetes, hypertension"
                value={form.additional_conditions}
                onChange={set("additional_conditions")}
                aria-describedby="hint-conditions"
              />
              <div className="hint" id="hint-conditions">Comma-separated. These may affect trial eligibility.</div>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <div className="field-row">
              <div className={fieldClass("key_labs_wbc")}>
                <label htmlFor={fieldId("key_labs_wbc")}>WBC (10^3/uL)</label>
                <input
                  id={fieldId("key_labs_wbc")}
                  type="number"
                  step="0.1"
                  placeholder="e.g., 5.2"
                  value={form.key_labs_wbc}
                  onChange={set("key_labs_wbc")}
                  onBlur={handleBlur("key_labs_wbc")}
                  aria-invalid={!!fieldError("key_labs_wbc")}
                  aria-describedby={fieldError("key_labs_wbc") ? errorId("key_labs_wbc") : undefined}
                />
                {fieldError("key_labs_wbc") && <div className="field-error-msg" id={errorId("key_labs_wbc")} role="alert">{fieldError("key_labs_wbc")}</div>}
              </div>
              <div className={fieldClass("key_labs_platelets")}>
                <label htmlFor={fieldId("key_labs_platelets")}>Platelets (10^3/uL)</label>
                <input
                  id={fieldId("key_labs_platelets")}
                  type="number"
                  step="1"
                  placeholder="e.g., 180"
                  value={form.key_labs_platelets}
                  onChange={set("key_labs_platelets")}
                  onBlur={handleBlur("key_labs_platelets")}
                  aria-invalid={!!fieldError("key_labs_platelets")}
                  aria-describedby={fieldError("key_labs_platelets") ? errorId("key_labs_platelets") : undefined}
                />
                {fieldError("key_labs_platelets") && <div className="field-error-msg" id={errorId("key_labs_platelets")} role="alert">{fieldError("key_labs_platelets")}</div>}
              </div>
            </div>
            <div className="field-row">
              <div className={fieldClass("key_labs_hemoglobin")}>
                <label htmlFor={fieldId("key_labs_hemoglobin")}>Hemoglobin (g/dL)</label>
                <input
                  id={fieldId("key_labs_hemoglobin")}
                  type="number"
                  step="0.1"
                  placeholder="e.g., 12.5"
                  value={form.key_labs_hemoglobin}
                  onChange={set("key_labs_hemoglobin")}
                  onBlur={handleBlur("key_labs_hemoglobin")}
                  aria-invalid={!!fieldError("key_labs_hemoglobin")}
                  aria-describedby={fieldError("key_labs_hemoglobin") ? errorId("key_labs_hemoglobin") : undefined}
                />
                {fieldError("key_labs_hemoglobin") && <div className="field-error-msg" id={errorId("key_labs_hemoglobin")} role="alert">{fieldError("key_labs_hemoglobin")}</div>}
              </div>
              <div className={fieldClass("key_labs_creatinine")}>
                <label htmlFor={fieldId("key_labs_creatinine")}>Creatinine (mg/dL)</label>
                <input
                  id={fieldId("key_labs_creatinine")}
                  type="number"
                  step="0.1"
                  placeholder="e.g., 1.0"
                  value={form.key_labs_creatinine}
                  onChange={set("key_labs_creatinine")}
                  onBlur={handleBlur("key_labs_creatinine")}
                  aria-invalid={!!fieldError("key_labs_creatinine")}
                  aria-describedby={fieldError("key_labs_creatinine") ? errorId("key_labs_creatinine") : undefined}
                />
                {fieldError("key_labs_creatinine") && <div className="field-error-msg" id={errorId("key_labs_creatinine")} role="alert">{fieldError("key_labs_creatinine")}</div>}
              </div>
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <div className="field-row">
              <div className={fieldClass("location_zip")}>
                <label htmlFor={fieldId("location_zip")}>ZIP Code</label>
                <input
                  id={fieldId("location_zip")}
                  type="text"
                  maxLength={10}
                  placeholder="e.g., 10001"
                  value={form.location_zip}
                  onChange={set("location_zip")}
                  onBlur={handleBlur("location_zip")}
                  aria-required="true"
                  aria-invalid={!!fieldError("location_zip")}
                  aria-describedby={fieldError("location_zip") ? errorId("location_zip") : undefined}
                />
                {fieldError("location_zip") && <div className="field-error-msg" id={errorId("location_zip")} role="alert">{fieldError("location_zip")}</div>}
              </div>
              <div className={fieldClass("willing_to_travel_miles")}>
                <label htmlFor={fieldId("willing_to_travel_miles")}>Willing to Travel (miles)</label>
                <input
                  id={fieldId("willing_to_travel_miles")}
                  type="number"
                  min="0"
                  value={form.willing_to_travel_miles}
                  onChange={set("willing_to_travel_miles")}
                  onBlur={handleBlur("willing_to_travel_miles")}
                  aria-invalid={!!fieldError("willing_to_travel_miles")}
                  aria-describedby={fieldError("willing_to_travel_miles") ? errorId("willing_to_travel_miles") : undefined}
                />
                {fieldError("willing_to_travel_miles") && <div className="field-error-msg" id={errorId("willing_to_travel_miles")} role="alert">{fieldError("willing_to_travel_miles")}</div>}
              </div>
            </div>
            <div className="field">
              <label htmlFor={fieldId("additional_notes")}>Anything Else?</label>
              <textarea
                id={fieldId("additional_notes")}
                rows={3}
                placeholder="Any other details you'd like us to consider..."
                value={form.additional_notes}
                onChange={set("additional_notes")}
              />
            </div>
          </>
        )}
      </div>

      <div className="form-nav">
        {step > 0 ? (
          <button className="btn btn-secondary" onClick={handlePrev} type="button">Back</button>
        ) : (
          <div />
        )}
        {step < steps.length - 1 ? (
          <button className="btn btn-primary" onClick={handleNext} type="button">
            Continue
            <svg className="btn-arrow" viewBox="0 0 20 20" fill="currentColor" width="16" height="16" aria-hidden="true">
              <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
            </svg>
          </button>
        ) : (
          <button className="btn btn-primary" disabled={!canAdvance()} onClick={handleSubmit} type="button">
            Find My Trials
          </button>
        )}
      </div>
    </div>
  );
}
