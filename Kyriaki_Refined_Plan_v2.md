# Kyriaki — Refined Plan (v2)

**Updated:** March 31, 2026
**Founder:** djp09
**Mission:** Save lives by transforming the clinical trial "paperwork marathon" into a seamless, agent-led connection to the medicine of tomorrow.

---

## 1. What Kyriaki Is

Kyriaki is a mission-driven LLC that builds an AI-powered patient agent for oncology clinical trial enrollment. The agent does the hard work — finding trials, analyzing eligibility, pulling records, preparing paperwork — so that cancer patients and their families can focus on fighting, not on bureaucracy.

**What changed from v1:** We've dropped the speculative tech (OpenClaw local gateway, browser automation of legacy portals, Digital Power of Attorney) and tightened around what's buildable, valuable, and legally sound today.

---

## 2. The Model: Maximum AI, Human at the Gates

Kyriaki operates as a **concierge hybrid.** The AI handles everything it legally and feasibly can. Humans (the patient, and optionally a navigator) sign off only at critical gates.

### What the AI Does Autonomously

- Ingests and normalizes patient medical history from uploaded documents, patient questionnaires, and (eventually) FHIR/TEFCA data feeds
- Parses full trial protocols — all inclusion/exclusion criteria, lines-of-therapy requirements, biomarker requirements, scheduling demands
- Cross-references patient data against every open trial for their cancer type and stage
- Generates a ranked list of matched trials with plain-language explanations of why each is or isn't a fit
- Prepares a **Verified Eligibility Dossier** — a structured document that a trial site coordinator can review quickly
- Drafts the enrollment paperwork (consent forms, screening questionnaires, required authorizations)
- Flags financial assistance programs, travel support, and logistical resources for each matched trial

### Where Humans Sign Off

- **Patient confirms** their medical information is accurate before matching begins
- **Patient selects** which trials they want to pursue from the AI's ranked recommendations
- **Patient reviews and signs** all enrollment documents (biometric / e-signature)
- **Patient navigator** (Phase 2) reviews the eligibility dossier before it goes to the trial site — catches edge cases the AI might miss

This keeps the agent doing 90%+ of the labor while respecting patient autonomy and staying clearly within regulatory bounds.

---

## 3. What We're Building — Phased for a Solo Founder

Everything below is scoped for evenings/weekends. Each phase has a clear deliverable and a clear "stop or go" decision point before the next.

### Phase 0: Foundation (Weeks 1–4)

**Goal:** Stand up the LLC and the basic project infrastructure.

- Register "Kyriaki LLC" (your state, mission statement in operating agreement)
- Set up a simple landing page explaining the mission — start collecting emails from interested patients/caregivers/advocates
- Create the project repository and development environment
- Set up a HIPAA-compliant cloud environment (AWS with BAA, or similar)
- Draft a privacy policy and terms of service (template-based for now; attorney review later)

**Decision gate:** Do you have at least 20 email signups or 3 conversations with cancer patients/caregivers confirming interest? → Go to Phase 1.

### Phase 1: The Matching Engine MVP (Weeks 5–12)

**Goal:** Build the core AI that matches a patient profile to open clinical trials — and prove it works.

**Data sources for trials:**
- ClinicalTrials.gov API (free, comprehensive, 400K+ trials)
- NCI Cancer Information Service data
- Focus initially on: Stage 4 lung cancer, rare pediatric cancers, triple-negative breast cancer (high urgency, high unmet need)

**Patient input (MVP — no health record integration yet):**
- A structured intake form: cancer type, stage, biomarkers, prior treatments, key labs, location, willingness to travel
- Optional: upload existing medical documents (pathology reports, treatment summaries) for AI extraction

**What the AI produces:**
- A ranked list of eligible trials with plain-language summaries
- For each trial: location, phase, what's involved, why the patient likely qualifies, any potential disqualifiers to discuss with their doctor
- A shareable PDF the patient can bring to their oncologist

**Tech stack (lean):**
- Backend: Python (FastAPI)
- AI: Claude API (Sonnet for intake processing, Opus for protocol reasoning)
- Database: PostgreSQL
- Trial data: ClinicalTrials.gov API, refreshed nightly
- Frontend: Simple React app or even a well-designed multi-step web form
- Hosting: HIPAA-eligible cloud (AWS/GCP with BAA)

**Decision gate:** Can the AI reliably match 10 real patient profiles to appropriate trials with >80% accuracy (validated by an oncologist or trial coordinator)? → Go to Phase 2.

### Phase 2: The Eligibility Dossier (Weeks 13–20)

**Goal:** Go beyond matching to actual enrollment preparation.

- Add structured **Verified Eligibility Dossier** generation — a document that maps a specific patient's data against a specific trial's full I/E criteria, line by line
- Add enrollment paperwork drafting — pre-fill what can be pre-filled from the patient's intake data
- Add a simple patient dashboard: track which trials you've been matched to, where each is in the process, what's needed next
- Begin TEFCA/FHIR integration research and sandbox testing — goal is to eventually pull records directly rather than relying on patient uploads

**Decision gate:** Can you get 3 trial site coordinators to review a Kyriaki-generated dossier and confirm it would actually save them time? → Go to Phase 3.

### Phase 3: Partnerships & Growth (Weeks 21–30)

**Goal:** Move from tool to service. Start building the relationships that make Kyriaki real.

- Partner with 1–2 patient advocacy groups (LUNGevity, Alex's Lemonade Stand, or similar) to offer Kyriaki free to their communities
- Recruit 1–2 volunteer patient navigators (retired oncology nurses, patient advocates) to serve as the human-in-the-loop reviewers
- Explore first revenue conversations: pharma sponsors or CROs willing to pay for high-quality patient referrals
- If traction warrants: begin TEFCA IAS (Individual Access Services) integration for direct patient record pull

---

## 4. Business & Revenue Model (Simplified)

### Near-term: Free for Patients, Always

The matching and eligibility dossier are free for cancer patients. Period. This is the mission.

### Revenue (when ready):

**Primary — Pharma referral fees:**
Trial sponsors and CROs pay when Kyriaki delivers a verified-eligible patient who passes site screening. Target: $5K–$15K per enrolled patient. This is lower than the v1 plan's $15K–$25K, but more realistic for early traction without a track record.

**Secondary — Site efficiency SaaS (Phase 3+):**
Offer trial sites a subscription to receive Kyriaki-prepared dossiers for their open trials. $2K–$5K/month per site. Only pursue this after proving dossier quality.

**Tertiary — Grants and mission-aligned funding:**
Cancer research foundations, NIH SBIR/STTR grants, and patient advocacy group partnerships. A mission-driven LLC with a track record of patient impact is well-positioned here.

### What We're NOT Doing Yet
- No VC fundraising in Phase 0–2. Build proof first.
- No enterprise sales. Too slow for a solo founder.
- No geographic expansion beyond the US until the model is proven.

---

## 5. Regulatory Approach (Simplified)

**Core principle:** Stay clearly in the "clinical decision *support*" lane — not clinical decision *making.*

- Kyriaki provides information and preparation. It does not diagnose, prescribe, or make treatment recommendations.
- All AI outputs are framed as "based on the information you provided, here are trials you may be eligible for — discuss with your oncologist."
- Patient data is handled under standard HIPAA authorization (no novel "Digital Power of Attorney" needed).
- E-signatures for consent use established 21 CFR Part 11-compliant methods.
- The AI never submits anything on behalf of the patient without explicit patient action.

**Legal to-do (Phase 0):**
- 1–2 hour consultation with a health tech attorney to confirm classification and HIPAA obligations
- Execute a BAA with your cloud provider
- Template-based privacy policy and terms of service, attorney-reviewed

---

## 6. Competitive Positioning

Kyriaki doesn't compete with Tempus, IQVIA, or Flatiron head-on. They serve providers and pharma. Kyriaki serves **patients.**

| | Tempus / IQVIA / Flatiron | Massive Bio / Leal Health | **Kyriaki** |
|---|---|---|---|
| **Who it serves** | Providers, pharma, CROs | Mix of patients and pharma | Patients first |
| **What it does** | Identifies candidates in EMR data | Matches patients to trials | Matches + prepares enrollment paperwork + navigates bureaucracy |
| **Patient experience** | Patient doesn't interact with it | Patient searches and browses | Patient is guided through the entire process by an AI agent |
| **Business model** | Enterprise SaaS / data licensing | Pharma fees + patient services | Free for patients; pharma pays for enrolled patients |

**The moat over time:** Trust. If Kyriaki becomes the tool cancer patients tell each other about in support groups and advocacy communities, the patient advocacy network becomes the distribution channel that enterprise competitors can't replicate.

---

## 7. What Success Looks Like

### 6 months (end of Phase 2):
- LLC registered and operational
- Working MVP that matches patients to trials with validated accuracy
- 50+ patients have used the tool
- 3+ trial site coordinators have confirmed the dossier saves them time
- 1+ patient advocacy group conversation in progress

### 12 months (end of Phase 3):
- 500+ patients served
- 2+ advocacy group partnerships live
- First patients successfully connected to trials through Kyriaki
- First revenue (even small) from pharma referral or grant

### The real metric:
**Number of cancer patients who got into a clinical trial they wouldn't have found or completed enrollment for without Kyriaki.** Everything else is a means to that end.

---

## 8. Immediate Next Steps (This Week)

1. **Register the LLC** — your state's online filing, ~$100–200, takes 15 minutes
2. **Set up the landing page** — simple one-pager with email capture (Carrd, Framer, or a static site)
3. **Schedule 2–3 conversations** with cancer patients/caregivers (Reddit r/cancer, r/lungcancer, advocacy group forums — listen first, don't pitch)
4. **Set up the dev environment** — GitHub repo, Python project scaffold, Claude API key
5. **Pull your first ClinicalTrials.gov data** — get comfortable with the API, understand the data model

---

*Previous documents: [Market Validation Report](Kyriaki_Market_Validation_Report.md) | [Original Business Plan](Kyriaki_Business_Plan_2026_1.md)*
