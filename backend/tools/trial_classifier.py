"""Tool: Deterministic trial classification for biomarker-therapy alignment.

Pure-Python rule-based classifier. No network, no LLM. Used to:
1. Categorize trial interventions (targeted/chemo/radiation/immunotherapy/...)
2. Detect biomarker-therapy alignment for actionable patient profiles
3. Validate cancer-type match between patient and trial

Reuses existing utilities:
- civic_client._parse_biomarker_to_gene — biomarker → gene normalization
- trials_client._GENE_TO_DRUGS — gene → targeted drug list
- trials_client._NEGATIVE_SUFFIXES — negative biomarker detection

Industry pattern: defense-in-depth filtering before LLM eligibility analysis.
Inspired by TrialGPT (Google Research 2024) and Mendel.ai clinical entity matching.
"""

from __future__ import annotations

import re

from logging_config import get_logger

logger = get_logger("kyriaki.tools.trial_classifier")


# --- Drug class whitelists (lowercased) ---

# Common chemotherapy agents — used to classify DRUG interventions as 'chemo'
_CHEMO_DRUGS: frozenset[str] = frozenset(
    {
        # Platinum
        "cisplatin",
        "carboplatin",
        "oxaliplatin",
        # Taxanes
        "paclitaxel",
        "docetaxel",
        "nab-paclitaxel",
        "abraxane",
        # Antimetabolites
        "pemetrexed",
        "gemcitabine",
        "5-fu",
        "5-fluorouracil",
        "fluorouracil",
        "capecitabine",
        "methotrexate",
        "cytarabine",
        # Anthracyclines
        "doxorubicin",
        "epirubicin",
        "daunorubicin",
        # Topoisomerase inhibitors
        "etoposide",
        "irinotecan",
        "topotecan",
        # Alkylating
        "cyclophosphamide",
        "ifosfamide",
        "temozolomide",
        "bendamustine",
        "dacarbazine",
        # Vinca alkaloids
        "vincristine",
        "vinblastine",
        "vinorelbine",
        # Other
        "bleomycin",
        "mitomycin",
        "eribulin",
        "trabectedin",
    }
)

# Common immunotherapy / checkpoint inhibitor agents
_IO_DRUGS: frozenset[str] = frozenset(
    {
        # Anti-PD-1
        "pembrolizumab",
        "nivolumab",
        "cemiplimab",
        "dostarlimab",
        "tislelizumab",
        "toripalimab",
        # Anti-PD-L1
        "atezolizumab",
        "durvalumab",
        "avelumab",
        # Anti-CTLA-4
        "ipilimumab",
        "tremelimumab",
        # Anti-LAG-3
        "relatlimab",
        # Cell therapies
        "tisagenlecleucel",
        "axicabtagene",
        "lisocabtagene",
        "brexucabtagene",
    }
)

# Hormonal / endocrine therapy
_HORMONAL_DRUGS: frozenset[str] = frozenset(
    {
        "tamoxifen",
        "anastrozole",
        "letrozole",
        "exemestane",
        "fulvestrant",
        "leuprolide",
        "goserelin",
        "abiraterone",
        "enzalutamide",
        "apalutamide",
        "darolutamide",
        "bicalutamide",
        "flutamide",
        "raloxifene",
    }
)


def _flat_targeted_drugs() -> frozenset[str]:
    """Flatten _GENE_TO_DRUGS into a lowercase set for membership checks."""
    from trials_client import _GENE_TO_DRUGS

    return frozenset(d.lower() for drugs in _GENE_TO_DRUGS.values() for d in drugs)


# Computed lazily on first use to avoid import cycles
_TARGETED_DRUGS_CACHE: frozenset[str] | None = None


def _targeted_drugs() -> frozenset[str]:
    global _TARGETED_DRUGS_CACHE
    if _TARGETED_DRUGS_CACHE is None:
        _TARGETED_DRUGS_CACHE = _flat_targeted_drugs()
    return _TARGETED_DRUGS_CACHE


# --- Cancer type synonym dictionary ---
# Maps canonical key → list of regex patterns. Covers ~95% of US oncology traffic.

CANCER_TYPE_SYNONYMS: dict[str, list[str]] = {
    "nsclc": [
        r"non[- ]small[- ]cell\s+lung",
        r"\bnsclc\b",
        r"lung\s+adenocarcinoma",
        r"lung\s+squamous",
        r"pulmonary\s+adenocarcinoma",
        # Broader lung patterns — NSCLC patients should also match generic lung trials
        r"\blung\s+(cancer|neoplasm|carcinoma|tumor|malignan)",
        r"\bnsclc\b",
        r"\bnscl\b",
    ],
    "sclc": [r"small[- ]cell\s+lung", r"\bsclc\b"],
    "lung": [r"\blung\s+(cancer|neoplasm|carcinoma|tumor)", r"lung\s+malignan"],
    "breast": [
        r"\bbreast\s+(cancer|carcinoma|neoplasm|tumor)",
        r"\btnbc\b",
        r"triple[- ]negative\s+breast",
        r"\bhr[- ]?(positive|negative)\s+breast",
        r"\bher2[- ]?(positive|negative)\s+breast",
    ],
    "colorectal": [r"\bcolorectal\b", r"\bcolon\s+cancer\b", r"\brectal\s+cancer\b", r"\bcrc\b"],
    "prostate": [r"\bprostate\s+(cancer|carcinoma|neoplasm)\b"],
    "pancreatic": [r"\bpancreatic\s+(cancer|carcinoma|adenocarcinoma)\b", r"\bpdac\b"],
    "ovarian": [r"\bovarian\s+(cancer|carcinoma)\b", r"\bfallopian\s+tube\b"],
    "hepatocellular": [r"\bhepatocellular\b", r"\bhcc\b", r"\bliver\s+cancer\b"],
    "renal": [r"\brenal\s+cell\b", r"\brcc\b", r"\bkidney\s+cancer\b"],
    "melanoma": [r"\bmelanoma\b"],
    "glioblastoma": [r"\bglioblastoma\b", r"\bgbm\b", r"\bglioma\b"],
    "myeloma": [r"\bmultiple\s+myeloma\b", r"\bmyeloma\b"],
    "leukemia": [r"\bleukemia\b", r"\baml\b", r"\bcml\b", r"\ball\b", r"\bcll\b"],
    "lymphoma": [r"\blymphoma\b", r"\bdlbcl\b", r"\bhodgkin\b"],
    "bladder": [r"\bbladder\s+(cancer|carcinoma)\b", r"urothelial"],
    "head_neck": [r"\bhead\s+and\s+neck\b", r"\bhnscc\b"],
    "esophageal": [r"\besophageal\b", r"\bgastroesophageal\b"],
    "gastric": [r"\bgastric\b", r"\bstomach\s+cancer\b"],
    "endometrial": [r"\bendometrial\b", r"\buterine\b"],
    "cervical": [r"\bcervical\s+cancer\b"],
}

# Generic terms used by basket / tumor-agnostic / molecular trials.
# When a trial only lists these, defer to biomarker alignment instead of cancer-type match.
_GENERIC_SOLID_TUMOR_TERMS = re.compile(
    r"\b(solid\s+tumor|advanced\s+cancer|advanced\s+malignan|metastatic\s+cancer|"
    r"refractory\s+cancer|locally\s+advanced)",
    re.IGNORECASE,
)

_BASKET_TRIAL_MARKERS = re.compile(
    r"\b(basket|umbrella|tumor[- ]agnostic|molecular\s+profile|nci[- ]?match|"
    r"tapur|drup|pan[- ]cancer|histology[- ]agnostic)\b",
    re.IGNORECASE,
)


# --- Public functions ---


def classify_interventions(trial: dict) -> set[str]:
    """Classify a trial's interventions into therapeutic categories.

    Returns a set of category strings from:
        {"targeted", "chemo", "radiation", "immunotherapy", "hormonal",
         "surgery", "observational", "device", "other"}

    Reads ``trial["interventions"]`` which is a list of "TYPE: name" strings
    produced by trials_client._extract_study (line 196-201).

    Defensive: trials with no interventions return {"other"}, never empty.
    """
    raw = trial.get("interventions") or []
    if not raw:
        return {"other"}

    types: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            continue
        # Format is "TYPE: name" — split on first colon
        if ":" in entry:
            itype, name = entry.split(":", 1)
            itype = itype.strip().upper()
            name = name.strip().lower()
        else:
            itype = ""
            name = entry.strip().lower()

        # Map ClinicalTrials.gov intervention types
        if itype == "RADIATION":
            types.add("radiation")
        elif itype in ("PROCEDURE", "SURGICAL"):
            types.add("surgery")
        elif itype == "DEVICE":
            types.add("device")
        elif itype in ("DIAGNOSTIC_TEST", "BEHAVIORAL", "OTHER", "DIETARY_SUPPLEMENT"):
            types.add("observational")
        elif itype in ("DRUG", "BIOLOGICAL", "COMBINATION_PRODUCT", "GENETIC"):
            # Need to inspect the drug name to classify
            if name in _IO_DRUGS or any(io in name for io in _IO_DRUGS):
                types.add("immunotherapy")
            elif name in _HORMONAL_DRUGS or any(h in name for h in _HORMONAL_DRUGS):
                types.add("hormonal")
            elif name in _targeted_drugs() or any(td in name for td in _targeted_drugs()):
                types.add("targeted")
            elif name in _CHEMO_DRUGS or any(c in name for c in _CHEMO_DRUGS):
                types.add("chemo")
            else:
                # Unknown drug — conservative default to "targeted" so we don't
                # wrongly filter promising trials. Better to let LLM evaluate.
                types.add("targeted")
        else:
            # Unrecognized type — defensive default
            types.add("other")

    return types or {"other"}


def patient_actionable_genes(biomarkers: list[str]) -> set[str]:
    """Return the set of actionable gene symbols from a patient's biomarker list.

    "Actionable" means: positive status AND has known targeted drugs in
    trials_client._GENE_TO_DRUGS. Negative biomarkers (EGFR-, ALK-) are
    excluded — they don't drive targeted-therapy matching.
    """
    from civic_client import _parse_biomarker_to_gene
    from trials_client import _GENE_TO_DRUGS, _NEGATIVE_SUFFIXES

    actionable: set[str] = set()
    for biomarker in biomarkers or []:
        clean = biomarker.strip().lower()
        if not clean:
            continue
        # Skip negative biomarkers
        if any(clean.endswith(s) for s in _NEGATIVE_SUFFIXES):
            continue
        if "negative" in clean or "absent" in clean or "not detected" in clean or "wild type" in clean:
            continue
        gene = _parse_biomarker_to_gene(biomarker)
        if not gene:
            continue
        if gene in _GENE_TO_DRUGS:
            actionable.add(gene)
    return actionable


def is_biomarker_aligned(trial: dict, actionable_genes: set[str]) -> tuple[bool, str]:
    """Check if a trial targets any of the patient's actionable biomarkers.

    Returns (aligned, reason). A trial is aligned if:
    - patient has no actionable genes (gate is N/A → True), OR
    - any trial intervention drug is in _GENE_TO_DRUGS[gene] for any gene, OR
    - eligibility_criteria text contains a positive context for any gene.
    """
    if not actionable_genes:
        return True, "no actionable genes (gate N/A)"

    from trials_client import _GENE_TO_DRUGS

    # Check 1: intervention drug match
    raw = trial.get("interventions") or []
    intervention_text = " ".join(str(i).lower() for i in raw)
    for gene in actionable_genes:
        for drug in _GENE_TO_DRUGS.get(gene, []):
            if drug.lower() in intervention_text:
                return True, f"intervention contains {gene}-targeted drug ({drug})"

    # Check 2: eligibility criteria mentions the gene in a positive context
    elig = (trial.get("eligibility_criteria") or "").lower()
    title = (trial.get("brief_title") or "").lower()
    summary = (trial.get("brief_summary") or "").lower()
    haystack = f"{title} {summary} {elig}"

    for gene in actionable_genes:
        gene_lower = gene.lower()
        # Look for gene name in positive context: mutation, positive, fusion, alteration, amplification
        # or specific variants like L858R, V600E, G12C, exon 19, exon 20
        pattern = (
            rf"\b{re.escape(gene_lower)}\b\s*"
            r"(mutation|positive|\+|alteration|fusion|rearrangement|amplification|"
            r"l\d+[a-z]|v\d+[a-z]|g\d+[a-z]|exon\s*\d+|t\d+[a-z])"
        )
        if re.search(pattern, haystack, re.IGNORECASE):
            return True, f"eligibility mentions {gene} in actionable context"
        # Also accept the variant patterns appearing near the gene name
        if re.search(rf"\b{re.escape(gene_lower)}\b", haystack):
            # Gene name appears — check if any variant pattern is within 50 chars
            for match in re.finditer(rf"\b{re.escape(gene_lower)}\b", haystack):
                window = haystack[max(0, match.start() - 50) : match.end() + 50]
                if re.search(r"(mutation|positive|fusion|alteration|amplification|exon)", window):
                    return True, f"eligibility mentions {gene} near actionable terms"

    return False, f"no intervention or criteria match for {','.join(sorted(actionable_genes))}"


def is_radiation_or_observational_only(intervention_types: set[str]) -> bool:
    """True if interventions are exclusively radiation/observational/device/surgery
    with no targeted/chemo/immunotherapy/hormonal therapy.
    """
    if not intervention_types:
        return False
    therapeutic = {"targeted", "chemo", "immunotherapy", "hormonal"}
    if intervention_types & therapeutic:
        return False
    non_therapeutic = {"radiation", "observational", "device", "surgery", "other"}
    # Don't filter pure {"other"} — it means we couldn't classify, be defensive
    if intervention_types == {"other"}:
        return False
    return intervention_types.issubset(non_therapeutic)


def canonical_search_term(patient_cancer_type: str) -> str:
    """Map a patient's cancer_type to a canonical search-friendly string.

    ClinicalTrials.gov search is keyword-based — patient inputs like
    "Non-Small Cell Lung Cancer - Adenocarcinoma" return fewer results
    than the canonical "Non-Small Cell Lung Cancer". This function strips
    subtype suffixes and maps to the most search-effective canonical form.

    Used ONLY for the search API query. The original patient.cancer_type
    is preserved for display and downstream matching.
    """
    if not patient_cancer_type:
        return patient_cancer_type
    clean = patient_cancer_type.strip()
    lower = clean.lower()

    # Strip common subtype suffixes after a dash
    # e.g., "Non-Small Cell Lung Cancer - Adenocarcinoma" → "Non-Small Cell Lung Cancer"
    for sep in [" - ", " – ", " — "]:
        if sep in clean:
            base = clean.split(sep, 1)[0].strip()
            if len(base) >= 5:  # don't strip if base is too short
                clean = base
                lower = clean.lower()
                break

    # Map to canonical search term by detecting cancer family
    if any(p in lower for p in ["non-small cell lung", "non small cell lung", "nsclc"]):
        return "Non-Small Cell Lung Cancer"
    if "lung adenocarcinoma" in lower or "lung squamous" in lower:
        return "Non-Small Cell Lung Cancer"
    if "small cell lung" in lower or "sclc" in lower:
        return "Small Cell Lung Cancer"
    if "lung" in lower and "cancer" in lower:
        return "Lung Cancer"
    if "triple negative breast" in lower or "tnbc" in lower:
        return "Triple Negative Breast Cancer"
    if "breast" in lower and ("cancer" in lower or "carcinoma" in lower):
        return "Breast Cancer"
    if "colorectal" in lower or "colon cancer" in lower or "rectal cancer" in lower:
        return "Colorectal Cancer"
    if "prostate" in lower:
        return "Prostate Cancer"
    if "pancreatic" in lower or "pdac" in lower:
        return "Pancreatic Cancer"
    if "ovarian" in lower:
        return "Ovarian Cancer"
    if "hepatocellular" in lower or "hcc" in lower:
        return "Hepatocellular Carcinoma"
    if "renal cell" in lower or "rcc" in lower:
        return "Renal Cell Carcinoma"
    if "melanoma" in lower:
        return "Melanoma"
    if "glioblastoma" in lower or "gbm" in lower:
        return "Glioblastoma"
    if "myeloma" in lower:
        return "Multiple Myeloma"
    if "leukemia" in lower:
        return "Leukemia"
    if "lymphoma" in lower:
        return "Lymphoma"

    # No mapping — return the (possibly de-suffixed) input
    return clean


def cancer_type_matches(
    patient_cancer_type: str,
    trial_conditions: list[str],
    trial_title: str = "",
) -> tuple[bool, str]:
    """Check if a trial's conditions/title match the patient's cancer type.

    Returns (matches, reason). Allows basket/umbrella/tumor-agnostic trials
    to bypass strict cancer-type matching (they're handled by biomarker alignment).
    """
    if not patient_cancer_type:
        return True, "no patient cancer type provided"

    patient_lower = patient_cancer_type.lower()
    conditions_text = " ".join((c or "").lower() for c in (trial_conditions or []))
    title_lower = (trial_title or "").lower()
    haystack = f"{conditions_text} {title_lower}"

    if not haystack.strip():
        return True, "no trial conditions to check (allowing through)"

    # Basket trial bypass
    if _BASKET_TRIAL_MARKERS.search(haystack):
        return True, "basket/umbrella/tumor-agnostic trial bypass"

    # Find which canonical cancer the patient has
    patient_canon: str | None = None
    for canon, patterns in CANCER_TYPE_SYNONYMS.items():
        for pat in patterns:
            if re.search(pat, patient_lower):
                patient_canon = canon
                break
        if patient_canon:
            break

    if patient_canon is None:
        # Unknown cancer type — defensive default to allow
        return True, "patient cancer type not in synonym dict (allowing through)"

    # Check if trial mentions patient's canonical cancer or any of its synonyms
    for pat in CANCER_TYPE_SYNONYMS[patient_canon]:
        if re.search(pat, haystack):
            return True, f"matched {patient_canon} synonym"

    # Last resort: generic solid tumor terms (lots of biomarker-driven trials use these)
    if _GENERIC_SOLID_TUMOR_TERMS.search(haystack):
        return True, "generic solid tumor / advanced cancer trial"

    return False, f"no match for patient cancer type ({patient_canon})"
