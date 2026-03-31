import { useState } from "react";

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

export default function IntakeForm({ onSubmit }) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState(INITIAL);

  const steps = [
    { title: "Cancer Information", fields: ["cancer_type", "cancer_stage", "biomarkers"] },
    { title: "Treatment History", fields: ["prior_treatments", "lines_of_therapy"] },
    { title: "About You", fields: ["age", "sex", "ecog_score", "additional_conditions"] },
    { title: "Lab Values (Optional)", fields: ["key_labs_wbc", "key_labs_platelets", "key_labs_hemoglobin", "key_labs_creatinine"] },
    { title: "Location & Preferences", fields: ["location_zip", "willing_to_travel_miles", "additional_notes"] },
  ];

  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });

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
      location_zip: form.location_zip,
      willing_to_travel_miles: parseInt(form.willing_to_travel_miles) || 50,
      additional_conditions: form.additional_conditions ? form.additional_conditions.split(",").map((s) => s.trim()).filter(Boolean) : [],
      additional_notes: form.additional_notes || null,
    };
  };

  const canAdvance = () => {
    if (step === 0) return form.cancer_type && form.cancer_stage;
    if (step === 2) return form.age && form.sex;
    if (step === 4) return form.location_zip.length >= 5;
    return true;
  };

  const handleSubmit = () => {
    onSubmit(buildPayload());
  };

  return (
    <div className="intake-form">
      <div className="step-indicator">
        {steps.map((_, i) => (
          <div key={i} className={`step-dot ${i === step ? "active" : i < step ? "done" : ""}`} />
        ))}
      </div>

      <div className="form-step">
        <h2>{steps[step].title}</h2>

        {step === 0 && (
          <>
            <div className="field">
              <label>Cancer Type</label>
              <select value={form.cancer_type} onChange={set("cancer_type")}>
                <option value="">Select cancer type...</option>
                {CANCER_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Stage</label>
              <select value={form.cancer_stage} onChange={set("cancer_stage")}>
                <option value="">Select stage...</option>
                {STAGES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Biomarkers</label>
              <input type="text" placeholder="e.g., EGFR+, PD-L1 80%, ALK-" value={form.biomarkers} onChange={set("biomarkers")} />
              <div className="hint">Comma-separated. Leave blank if unknown.</div>
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <div className="field">
              <label>Prior Treatments</label>
              <textarea rows={3} placeholder="e.g., Carboplatin/Pemetrexed, Pembrolizumab" value={form.prior_treatments} onChange={set("prior_treatments")} />
              <div className="hint">Comma-separated list of treatments you have received.</div>
            </div>
            <div className="field">
              <label>Lines of Therapy</label>
              <select value={form.lines_of_therapy} onChange={set("lines_of_therapy")}>
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
              <div className="field">
                <label>Age</label>
                <input type="number" min="0" max="120" value={form.age} onChange={set("age")} />
              </div>
              <div className="field">
                <label>Sex</label>
                <select value={form.sex} onChange={set("sex")}>
                  <option value="">Select...</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                </select>
              </div>
            </div>
            <div className="field">
              <label>ECOG Performance Status</label>
              <select value={form.ecog_score} onChange={set("ecog_score")}>
                <option value="">Not sure / skip</option>
                <option value="0">0 — Fully active</option>
                <option value="1">1 — Restricted but ambulatory</option>
                <option value="2">2 — Ambulatory, capable of self-care</option>
                <option value="3">3 — Limited self-care, confined to bed/chair 50%+</option>
                <option value="4">4 — Completely disabled</option>
              </select>
              <div className="hint">Your doctor can help you determine this. It is ok to skip.</div>
            </div>
            <div className="field">
              <label>Other Medical Conditions</label>
              <input type="text" placeholder="e.g., diabetes, hypertension" value={form.additional_conditions} onChange={set("additional_conditions")} />
              <div className="hint">Comma-separated. These may affect trial eligibility.</div>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <p style={{ marginBottom: "1rem", fontSize: "0.9rem", color: "#666" }}>
              If you have recent lab results, entering them can improve match accuracy. All fields are optional.
            </p>
            <div className="field-row">
              <div className="field">
                <label>WBC (10^3/uL)</label>
                <input type="number" step="0.1" placeholder="e.g., 5.2" value={form.key_labs_wbc} onChange={set("key_labs_wbc")} />
              </div>
              <div className="field">
                <label>Platelets (10^3/uL)</label>
                <input type="number" step="1" placeholder="e.g., 180" value={form.key_labs_platelets} onChange={set("key_labs_platelets")} />
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <label>Hemoglobin (g/dL)</label>
                <input type="number" step="0.1" placeholder="e.g., 12.5" value={form.key_labs_hemoglobin} onChange={set("key_labs_hemoglobin")} />
              </div>
              <div className="field">
                <label>Creatinine (mg/dL)</label>
                <input type="number" step="0.1" placeholder="e.g., 1.0" value={form.key_labs_creatinine} onChange={set("key_labs_creatinine")} />
              </div>
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <div className="field-row">
              <div className="field">
                <label>ZIP Code</label>
                <input type="text" maxLength={10} placeholder="e.g., 10001" value={form.location_zip} onChange={set("location_zip")} />
              </div>
              <div className="field">
                <label>Willing to Travel (miles)</label>
                <input type="number" min="0" value={form.willing_to_travel_miles} onChange={set("willing_to_travel_miles")} />
              </div>
            </div>
            <div className="field">
              <label>Anything Else?</label>
              <textarea rows={3} placeholder="Any other details you'd like us to consider..." value={form.additional_notes} onChange={set("additional_notes")} />
            </div>
          </>
        )}
      </div>

      <div className="form-nav">
        {step > 0 ? (
          <button className="btn btn-secondary" onClick={() => setStep(step - 1)}>Back</button>
        ) : (
          <div />
        )}
        {step < steps.length - 1 ? (
          <button className="btn btn-primary" disabled={!canAdvance()} onClick={() => setStep(step + 1)}>Continue</button>
        ) : (
          <button className="btn btn-primary" disabled={!canAdvance()} onClick={handleSubmit}>Find My Trials</button>
        )}
      </div>
    </div>
  );
}
