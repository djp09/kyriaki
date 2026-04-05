"""PHI boundary and de-identification utilities.

This package is the security-critical boundary between internal PHI storage
and external systems (especially the Claude API). See ADR-004.
"""

from phi.boundary import ExternalPayload, PHIBoundaryViolation, to_external_llm
from phi.deidentify import DeidentifiedText, Redaction, deidentify

__all__ = [
    "DeidentifiedText",
    "ExternalPayload",
    "PHIBoundaryViolation",
    "Redaction",
    "deidentify",
    "to_external_llm",
]
