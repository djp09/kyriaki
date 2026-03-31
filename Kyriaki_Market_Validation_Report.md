# Kyriaki — Market Validation & Idea Analysis

**Date:** March 31, 2026
**Purpose:** Internal decision-making — validate whether Kyriaki is a viable business before committing to build

---

## 1. Verdict: Is This a Good Idea?

**Yes — with important caveats.** The problem is real, the market is large and growing, and incumbents leave meaningful gaps. But Kyriaki's current plan overestimates how quickly a startup can access patient data and underestimates how entrenched certain competitors already are. The core thesis — an *agent that acts* rather than a *database that lists* — is the right differentiator, but the go-to-market needs sharpening.

Below is the full analysis.

---

## 2. The Problem — Validated

The pain points described in Kyriaki's business plan are well-documented and, if anything, understated:

**Enrollment is broken.** Only 2–8% of adult cancer patients enroll in clinical trials. As many as 20% of trials fail outright due to insufficient enrollment, and 80% miss their enrollment timelines.

**The barriers are structural, not informational.**
- 56% of patients don't enroll because no suitable trial is available at their treatment location.
- 22% are screened out by overly restrictive eligibility criteria.
- Nearly 50% of patients with common metastatic cancers would need to drive 60+ minutes each way to reach a trial site.
- 55% of patients cite personal costs (travel, lodging, lost wages) as a key enrollment factor.
- Nearly 70% of the public never or rarely consider a trial when discussing treatment with their doctor.

**Providers are bottlenecked too.** Physicians cite time constraints, limited awareness of open trials, and non-cooperation from colleagues as persistent barriers. Manual chart review against 200+ exclusion criteria is the norm.

**The cost to pharma is enormous.** Recruitment costs exceed $50,000 per patient, and screen-fail waste (patients who begin screening but don't qualify) is a massive line item for sponsors and CROs.

**Assessment:** The problem is severe, well-documented, and not going away. Kyriaki is targeting real suffering and real economic waste. This passes validation.

---

## 3. Market Size & Trends

### Total Addressable Market

The numbers support a large and growing opportunity:

- **Oncology clinical trials market:** $15.76B in 2026, projected to reach $25.6B by 2035 (5.5% CAGR).
- **Clinical trial patient recruitment services:** $10.99B in 2024, projected to reach $22.85B by 2033.
- **AI in clinical trials:** $2.09B in 2026, projected to reach $18.62B by 2040 (17% CAGR) — this is Kyriaki's most direct market.

### Key Trends Working in Kyriaki's Favor

**AI adoption is accelerating.** AI-powered patient recruitment tools are improving enrollment rates by up to 65%, cutting trial timelines by 30–50%, and reducing costs by up to 40%. 80% of startups in the space now use AI automation.

**TEFCA is becoming real.** As of 2026, 14,214 organizations are live on the TEFCA network, with 11 Qualified Health Information Networks (QHINs) operational — more than double since the December 2023 go-live. Over 607 million documents have been shared. Oracle Health recently received QHIN designation, and as of January 2026, all data must conform to USCDI v3 standards with HL7 FAST security for FHIR transactions. This is the data infrastructure Kyriaki's plan depends on, and it's maturing on schedule.

**Decentralized / hybrid trials are expanding.** COVID permanently shifted expectations around remote participation, and sponsors are increasingly open to decentralized models — which align with Kyriaki's agent-based approach.

**Oncology leads VC interest.** Oncology accounted for 35% of all pharma startup funding in 2025. AI-powered drug discovery startups raised $2.8B in 2025 alone. Investors are looking for clinical evidence, regulatory plans, and interoperability readiness — all things Kyriaki can demonstrate.

**Assessment:** The market is large, growing fast, and the technology environment (TEFCA, AI, FHIR) is maturing at exactly the right time. Strong tailwinds.

---

## 4. Competitive Landscape

This is where Kyriaki needs the most honest reckoning. The space is not empty.

### Tier 1: Entrenched Players

| Competitor | What They Do | Scale | Key Strength | Key Weakness |
|---|---|---|---|---|
| **Tempus AI** | Genomic sequencing + trial matching via TIME Trial Network. Acquired Deep 6 AI in 2025. | 50%+ of US oncologists connected; screens 1M+ patients/day via EMR integrations; 30M+ patients in network | Massive data moat, EMR integration, genomics + clinical data combined | Pharma-facing, not patient-facing. Patients don't "choose" Tempus — their doctor's network does |
| **Flatiron Health** (Roche) | Oncology-specific EHR + real-world evidence platform | 280+ community oncology sites, 800+ sites for research | Deep oncology EHR data, Roche backing | Primarily an RWE/analytics play; trial matching is secondary |
| **IQVIA** | End-to-end CRO with AI-powered patient identification | Global, massive scale | Largest clinical trial data sets globally | Legacy enterprise, slow-moving, not patient-centric |

### Tier 2: Direct Competitors

| Competitor | What They Do | Differentiator | Weakness |
|---|---|---|---|
| **Massive Bio** | AI-powered multi-trial matching (Pre-screen Plus). Searches 19,000+ active interventional cancer trials | Strong eligibility matching across full I/E criteria; expanding beyond matching into drug matching | Still largely a matching *service*, not an autonomous agent |
| **Leal Health** (fka TrialJectory) | AI decision-support for cancer patients; personalized treatment matching | Patient-facing; focuses on patient empowerment and shared decision-making | Primarily advisory/informational rather than action-oriented |
| **Antidote** (fka TrialReach) | Patient recruitment platform + trial search engine for patients | Dual-sided (patients + sponsors); founded 2010, experienced | More of a recruitment marketplace than an intelligent agent |

### Where Kyriaki Fits — The Gap

The critical insight from this competitive analysis: **nobody is doing what Kyriaki describes as end-to-end enrollment automation.** The market breaks down into:

1. **Matchers** (Tempus, Massive Bio, IQVIA): They identify *which* patients *might* qualify. The patient/site still does all the paperwork.
2. **Search engines** (Antidote, Leal Health): They help patients *find* trials. The patient still does everything after that.
3. **Site tools** (Deep 6 AI/Tempus, Flatiron): They help *sites* identify patients in their own EMR. Patients don't interact with them directly.

**Nobody is acting as the patient's agent** — pulling records, verifying eligibility in detail, preparing the enrollment dossier, and navigating the bureaucracy on the patient's behalf. That's the niche Kyriaki claims, and it appears to be genuinely unoccupied.

**However:** Tempus is the 800-pound gorilla. With 50%+ oncologist coverage, EMR integrations, genomic data, and the Deep 6 AI acquisition, they *could* build this capability. Kyriaki's window of advantage is real but not permanent.

---

## 5. Feasibility & Risk Assessment

### Technical Feasibility: MEDIUM-HIGH

**What's realistic:**
- Claude 4.6's 1M token context window genuinely can process multi-year patient histories and full trial protocols in a single pass. This is real and differentiated.
- TEFCA/QHIN infrastructure is live and expanding. The Individual Access Services (IAS) pathway exists for patient-directed data access.
- FHIR APIs are increasingly standardized. The January 2026 USCDI v3 mandate helps.

**What's harder than the plan suggests:**
- "Computer Use" to navigate legacy hospital portals is fragile. Hospital IT environments are chaotic, change without notice, and actively resist automation. This should be a fallback, not a core feature.
- Patient record ingestion via TEFCA is real but not seamless. Data quality varies wildly between sources. Expect significant data normalization work.
- The "OpenClaw local gateway" concept (running locally on the patient's device) may be technically elegant for privacy but creates support/deployment challenges. A cloud-based HIPAA-compliant architecture might be more practical for an MVP.

### Regulatory Feasibility: MEDIUM

**Favorable factors:**
- The FDA's January 2026 Clinical Decision Support guidance clarifies that software matching patients to treatment guidelines (including trials) can potentially be *excluded* from the medical device definition — as long as it's transparent, intended for professional review, and doesn't replace clinical judgment.
- Human-in-the-loop design (biometric confirmation before submission) is the right approach.
- 21 CFR Part 11 compliance for digital signatures is well-established.

**Risks:**
- The "Digital Power of Attorney" concept in the business plan is novel and legally untested. Patient consent for data access is straightforward under HIPAA; an AI agent "negotiating with trial coordinators" on behalf of a patient is uncharted territory.
- If the tool's recommendations cross the line from "matching" into "clinical advice" (e.g., ranking trials by predicted efficacy), it could trigger FDA SaMD classification.
- HIPAA compliance for an AI system processing PHI requires robust BAAs, encryption, audit trails, and breach protocols. This is achievable but non-trivial and expensive.

### Business Model Feasibility: MEDIUM

**The $15K–$25K per-patient pharma success fee:**
- Directionally right. Pharma absolutely pays this level for high-quality enrolled patients.
- **But:** You need to prove you can deliver *randomized* patients, not just *matched* patients. The delta between "eligible on paper" and "actually randomized" involves site-level logistics Kyriaki doesn't control.
- Risk: Pharma will want volume proof before signing contracts. Chicken-and-egg problem.

**The $5K/month site SaaS:**
- Reasonable price point for oncology sites, but you're competing with tools sites already have (Tempus TIME, Epic's built-in matching).
- Sites are notoriously slow to adopt new software. Sales cycles are 6–12+ months.

**Recommended pivot:** Consider a **patient-direct freemium model** initially. Free for patients, monetize via pharma referral fees only after demonstrating matching quality. This builds the patient base that makes the pharma pitch credible.

---

## 6. Honest SWOT Analysis

### Strengths
- Genuinely unoccupied niche: patient-side *agent* vs. provider-side *tool*
- TEFCA/IAS pathway enables patient-directed data access without hospital integration deals
- AI technology (LLM reasoning over protocols + patient history) is mature enough for this use case
- Oncology focus provides urgency and willingness-to-pay that other therapeutic areas lack
- Timing: infrastructure (TEFCA), technology (LLMs), and market need are converging in 2026

### Weaknesses
- No existing data moat — Tempus has 30M+ patients and 50%+ oncologist coverage
- No existing relationships with pharma sponsors or trial sites
- Regulatory pathway for an AI "patient agent" is untested
- Technical complexity of reliable health record ingestion and normalization
- Solo founder / early stage — execution risk

### Opportunities
- Rare/pediatric cancers wedge: low competition, high urgency, sympathetic to advocacy group partnerships
- Patient advocacy groups (LUNGevity, Leukemia & Lymphoma Society, etc.) as distribution channels — lower CAC than direct-to-patient marketing
- TEFCA expansion will make patient data access progressively easier each quarter
- Potential for pharma to pre-fund development in exchange for exclusive early access

### Threats
- Tempus could add end-to-end enrollment to their existing platform within 12–18 months
- Regulatory crackdown on AI in healthcare could slow deployment
- Patient trust barrier: getting cancer patients to authorize an AI to handle their medical records is a high bar
- TEFCA implementation delays or data quality issues could slow the core workflow

---

## 7. Recommendations: What to Do Before Building

### Keep
- The "acting agent" positioning — this is the right differentiator
- Oncology focus — the urgency and willingness-to-pay are real
- The rare cancers / Stage 4 wedge — high urgency, fewer competitors, advocacy group alignment
- TEFCA/IAS as the data access strategy — this is the right bet

### Pivot or Refine
- **Drop "OpenClaw local gateway" for MVP.** Build a HIPAA-compliant cloud service first. Local execution is a nice-to-have for V2, not an MVP requirement.
- **Drop "Computer Use for legacy portals" for MVP.** Focus on structured data via FHIR/TEFCA. Manual portal navigation is too fragile for a first product.
- **Reframe "Digital Power of Attorney."** Instead, use standard HIPAA authorization + patient consent. The DPOA concept sounds innovative but creates unnecessary legal risk.
- **Add a patient-facing freemium entry point.** Don't gate everything behind pharma contracts. Let patients use the matching for free; prove the model; then sell to pharma.
- **Consider a "concierge" hybrid.** For the MVP, have the AI do 80% of the work but have a human patient navigator review and submit. This de-risks the regulatory question and builds trust.

### Validate Next
Before writing code, these are the highest-value validation steps:

1. **Talk to 10 cancer patients or caregivers** who have tried to find/enroll in trials. Confirm the pain points and test whether they'd trust an AI agent with their records.
2. **Talk to 3–5 trial site coordinators.** Understand their actual workflow for enrollment. What would they need from an AI-generated "eligibility dossier" to take it seriously?
3. **Talk to 1–2 patient advocacy groups** (start with rare cancers). Would they partner on a pilot? Would they promote a free tool to their members?
4. **Build a non-functional prototype/demo** showing the patient journey. Use this for conversations with potential pharma partners to gauge willingness-to-pay.
5. **Consult a health tech regulatory attorney** on the FDA classification question. One 2-hour session could save months of misdirection.

---

## 8. Bottom Line

Kyriaki targets a validated, severe problem in a large and growing market. The competitive landscape has real incumbents but a genuine gap in patient-side enrollment automation. The technology and infrastructure environment in 2026 make this more buildable than it would have been even two years ago.

The biggest risks are: competing with Tempus's data moat, navigating untested regulatory territory for an AI patient agent, and the go-to-market challenge of building both patient supply and pharma demand simultaneously.

**Recommendation: Proceed — but tighten the MVP scope, validate with real users before coding, and consider a human-in-the-loop "concierge" model for the first version.**

---

*This report was prepared for internal decision-making. Market data sourced from public reports and industry publications as of March 2026.*
