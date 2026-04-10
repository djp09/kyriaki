"""Patient routing — classifies complexity and configures agent strategy.

Runs before the agent loop starts. Examines the patient profile and returns
a RouteConfig that tunes budget, model, and strategy hints.

Routing is deterministic (no API calls) for speed. Classification uses
cancer type matching against known lists + patient profile heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_loop import AgentBudget
from config import get_settings
from logging_config import get_logger
from models import PatientProfile

logger = get_logger("kyriaki.routing")

# Known rare cancers — triggers expanded search budget
RARE_CANCERS = [
    "ewing sarcoma",
    "rhabdomyosarcoma",
    "osteosarcoma",
    "neuroblastoma",
    "wilms tumor",
    "retinoblastoma",
    "medulloblastoma",
    "glioblastoma",
    "cholangiocarcinoma",
    "mesothelioma",
    "thymoma",
    "thymic carcinoma",
    "adrenocortical carcinoma",
    "gastrointestinal stromal tumor",
    "gist",
    "merkel cell carcinoma",
    "angiosarcoma",
    "chordoma",
    "desmoid tumor",
    "leiomyosarcoma",
    "liposarcoma",
    "synovial sarcoma",
    "dermatofibrosarcoma",
    "carcinoid",
    "neuroendocrine",
    "pheochromocytoma",
    "paraganglioma",
    "gestational trophoblastic",
    "choriocarcinoma",
    "hepatoblastoma",
    "pleuropulmonary blastoma",
    "atypical teratoid rhabdoid",
    "craniopharyngioma",
    "ependymoma",
    "inflammatory breast cancer",
    "male breast cancer",
    "gallbladder cancer",
    "penile cancer",
    "vulvar cancer",
    "anal cancer",
    "small bowel cancer",
    "appendiceal cancer",
]

# Common cancers — standard budget is sufficient
COMMON_CANCERS = [
    "non-small cell lung cancer",
    "nsclc",
    "small cell lung cancer",
    "breast cancer",
    "prostate cancer",
    "colorectal cancer",
    "colon cancer",
    "rectal cancer",
    "melanoma",
    "bladder cancer",
    "kidney cancer",
    "renal cell carcinoma",
    "ovarian cancer",
    "pancreatic cancer",
    "liver cancer",
    "hepatocellular carcinoma",
    "thyroid cancer",
    "endometrial cancer",
    "uterine cancer",
    "cervical cancer",
    "head and neck cancer",
    "gastric cancer",
    "stomach cancer",
    "esophageal cancer",
    "lymphoma",
    "leukemia",
    "multiple myeloma",
]


@dataclass
class RouteConfig:
    """Configuration produced by the router for an agent run."""

    complexity: str  # "simple", "moderate", "complex"
    category: str  # "common_adult", "rare_adult", "pediatric"
    strategy_hint: str  # Injected into orchestrator prompt
    max_iterations: int = 5
    max_search_calls: int = 3
    max_analysis_calls: int = 20

    def to_budget(self) -> AgentBudget:
        """Convert to AgentBudget for the agent loop."""
        return AgentBudget(
            max_iterations=self.max_iterations,
            max_search_calls=self.max_search_calls,
            max_analysis_calls=self.max_analysis_calls,
        )


def classify_patient(patient: PatientProfile) -> RouteConfig:
    """Classify a patient's complexity and return routing configuration.

    Uses deterministic rules (no API calls) for speed:
    - Pediatric: age < 18
    - Rare: cancer_type matches RARE_CANCERS list
    - Complex: rare OR high lines of therapy OR many biomarkers
    - Simple: everything else
    """
    cancer_lower = patient.cancer_type.lower().strip()
    is_pediatric = patient.age < 18
    is_rare = any(rare in cancer_lower for rare in RARE_CANCERS)
    is_common = any(common in cancer_lower for common in COMMON_CANCERS)
    high_therapy_lines = patient.lines_of_therapy >= 3
    many_biomarkers = len(patient.biomarkers) >= 5

    # Determine category
    if is_pediatric:
        category = "pediatric"
    elif is_rare:
        category = "rare_adult"
    else:
        category = "common_adult"

    # Determine complexity
    if is_pediatric or is_rare:
        complexity = "complex"
    elif high_therapy_lines or many_biomarkers:
        complexity = "moderate"
    elif not is_common:
        complexity = "moderate"
    else:
        complexity = "simple"

    # Build strategy hint
    hints = []
    if is_pediatric:
        hints.append(
            f"PEDIATRIC PATIENT (age {patient.age}). Search with pediatric-specific terms. "
            "Many adult trials exclude minors — check age criteria carefully. "
            "Consider searching by specific tumor type AND 'pediatric'."
        )
    if is_rare:
        hints.append(
            "RARE CANCER TYPE. Expect fewer trials. Use broader search terms and synonyms. "
            f"Try searching by cancer family (e.g., 'sarcoma' not just '{patient.cancer_type}'). "
            "Also search by known interventions for this cancer type."
        )
    if high_therapy_lines:
        hints.append(
            f"HEAVILY PRE-TREATED ({patient.lines_of_therapy} prior lines). Many trials exclude patients with >2 prior lines. "
            "Focus on later-line and refractory-specific trials. "
            "Search for 'refractory' or 'relapsed' in query terms."
        )
    if many_biomarkers:
        hints.append(
            f"COMPLEX BIOMARKER PROFILE ({len(patient.biomarkers)} biomarkers). Consider searching by specific biomarker-targeted "
            "therapies. Multiple searches may be needed — one per key biomarker."
        )
    if not hints:
        hints.append(
            "STANDARD CASE. The patient's cancer type is common with many available trials. "
            "A targeted search by cancer type should yield good candidates."
        )

    strategy_hint = "\n".join(f"- {h}" for h in hints)

    # Set budget based on complexity
    if complexity == "complex":
        config = RouteConfig(
            complexity=complexity,
            category=category,
            strategy_hint=strategy_hint,
            max_iterations=7,
            max_search_calls=5,
            max_analysis_calls=30,
        )
    elif complexity == "moderate":
        config = RouteConfig(
            complexity=complexity,
            category=category,
            strategy_hint=strategy_hint,
            max_iterations=6,
            max_search_calls=4,
            max_analysis_calls=25,
        )
    else:
        settings = get_settings()
        config = RouteConfig(
            complexity=complexity,
            category=category,
            strategy_hint=strategy_hint,
            max_iterations=settings.agent_max_iterations,
            max_search_calls=settings.agent_max_search_calls,
            max_analysis_calls=settings.agent_max_analysis_calls,
        )

    logger.info(
        "routing.classified",
        cancer_type=patient.cancer_type,
        complexity=complexity,
        category=category,
        max_iterations=config.max_iterations,
        max_searches=config.max_search_calls,
    )
    return config
