"""HIPAA Safe Harbor de-identification scrubber.

Removes the 18 identifiers enumerated in HIPAA §164.514(b)(2) from free text
before it crosses the PHI boundary to an external LLM.

Scope and limitations:
- This is a regex-based scrubber. It will catch common forms of each
  identifier type but cannot guarantee the text is identifier-free.
  It is the LAST line of defence, not the only one: structured patient
  data should be reduced to Safe Harbor fields at the boundary
  (`phi.boundary.to_external_llm`) *before* free-text scrubbing runs.
- Name detection is conservative and trigger-based (titles and labels
  like "Patient:", "Name:", "Dr."). It deliberately does not try to
  flag arbitrary capitalised token pairs, which would produce large
  numbers of false positives in clinical text ("Stage IV", "New York",
  "Non Small Cell").

Strictness levels:
- ``safe_harbor`` (default): removes all 18 identifiers. Ages over 89 are
  bucketed as ``90+``; dates become year-only; ZIPs become ZIP3 with the
  Safe Harbor excluded-prefix list mapped to ``000``.
- ``limited_dataset``: preserves dates and city/state/ZIP. Still removes
  direct identifiers (name, phone, email, SSN, MRN, etc.). Use only
  under a Data Use Agreement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Literal

Strictness = Literal["safe_harbor", "limited_dataset"]

# HIPAA Safe Harbor — ZIP3 prefixes with populations ≤ 20,000 (must be "000").
# Source: 45 CFR §164.514(b)(2)(i)(B).
SAFE_HARBOR_EXCLUDED_ZIP3: frozenset[str] = frozenset(
    {
        "036",
        "059",
        "063",
        "102",
        "203",
        "556",
        "692",
        "790",
        "821",
        "823",
        "830",
        "831",
        "878",
        "879",
        "884",
        "890",
        "893",
    }
)


@dataclass
class Redaction:
    """A single identifier that was removed from the input."""

    kind: str
    original: str
    replacement: str


@dataclass
class DeidentifiedText:
    """Result of de-identifying a block of text."""

    text: str
    redactions: list[Redaction] = field(default_factory=list)

    @property
    def redaction_report(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.redactions:
            counts[r.kind] = counts.get(r.kind, 0) + 1
        return counts

    def is_clean(self) -> bool:
        return not self.redactions


# --- Regex patterns (compiled once) ---

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Phone: require at least one separator or parenthesised area code so we
# don't collide with MRNs or long ID numbers.
_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?1[\s.\-]?)?"
    r"(?:\(\d{3}\)[\s.\-]?|\d{3}[\s.\-])"
    r"\d{3}[\s.\-]\d{4}"
    r"(?!\d)"
)

# MRN / account / record / device / licence number labels. The captured
# value must contain at least one digit and be ≥3 chars, which prevents
# matches like "record shows" or "account holder".
_LABELED_ID_RE = re.compile(
    r"\b(MRN|medical\s+record(?:\s+number)?|patient\s+id|record|"
    r"account(?:\s+number)?|acct|policy|license|"
    r"plate|device\s*(?:id|serial)|serial)"
    r"[\s:#]*"
    r"\b(?=[A-Za-z0-9\-]{3,}\b)([A-Za-z0-9\-]*\d[A-Za-z0-9\-]*)\b",
    re.IGNORECASE,
)

# Dates — keep the 4-digit year when present, otherwise drop entirely.
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b")
_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DATE_MONTH_WORD_RE = re.compile(
    rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,)?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_DATE_DAY_MONTH_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}\s+(\d{{4}})\b",
    re.IGNORECASE,
)

# Ages over 89. Several common clinical phrasings.
_AGE_PHRASE_RE = re.compile(
    r"\b(?:age[d]?\s*[:\-]?\s*|is\s+)?(\d{2,3})\s*[-\s]*(?:year[s]?[-\s]*old|y\.?o\.?|yr[s]?\.?)\b",
    re.IGNORECASE,
)
_AGE_LABEL_RE = re.compile(r"\b(age|aged)\s*[:\-]?\s*(\d{2,3})\b", re.IGNORECASE)

# ZIP codes. ZIP+4 and 5-digit.
_ZIP_RE = re.compile(r"(?<!\d)(\d{5})(?:-\d{4})?(?!\d)")

# Names — trigger-based. Captures 1–4 capitalised tokens (with optional
# middle initial) after an explicit label or honorific.
_NAME_CAP = r"[A-Z][a-zA-Z'\-]{1,24}"
_NAME_CAP_SEQ = rf"{_NAME_CAP}(?:\s+(?:[A-Z]\.\s*)?{_NAME_CAP}){{0,3}}"
_NAME_HONORIFIC_RE = re.compile(
    rf"\b(Mr|Mrs|Ms|Miss|Mister|Dr|Doctor|Prof|Professor|Rev|Sir|Madam|Mme|Mlle)\.?\s+({_NAME_CAP_SEQ})\b"
)
_NAME_LABEL_RE = re.compile(
    rf"\b(patient(?:'s)?\s+name|name|pt|patient|signed(?:\s+by)?|by|from|to)"
    rf"\s*[:\-]\s*({_NAME_CAP_SEQ})\b",
    re.IGNORECASE,
)
_NAME_IS_RE = re.compile(rf"\bname\s+is\s+({_NAME_CAP_SEQ})\b", re.IGNORECASE)


def _run_pattern(
    text: str,
    pattern: re.Pattern[str],
    kind: str,
    replacer: Callable[[re.Match[str]], str],
    redactions: list[Redaction],
) -> str:
    def _sub(m: re.Match[str]) -> str:
        replacement = replacer(m)
        redactions.append(Redaction(kind=kind, original=m.group(0), replacement=replacement))
        return replacement

    return pattern.sub(_sub, text)


def _zip_replacement(m: re.Match[str]) -> str:
    zip5 = m.group(1)
    zip3 = zip5[:3]
    if zip3 in SAFE_HARBOR_EXCLUDED_ZIP3:
        return "000"
    return f"{zip3}XX"


def _date_year_only(year_str: str) -> str:
    year = int(year_str)
    if year < 100:
        # 2-digit year: we can't safely recover the century. Drop entirely.
        return "[DATE]"
    return str(year)


def _age_replacement(age_str: str, suffix: str = " years old") -> str:
    try:
        age = int(age_str)
    except ValueError:
        return "[AGE]"
    if age > 89:
        return f"90+{suffix}"
    return f"{age}{suffix}"


def deidentify(
    text: str,
    strictness: Strictness = "safe_harbor",
) -> DeidentifiedText:
    """Remove HIPAA Safe Harbor identifiers from free text.

    Args:
        text: free-text input (may be multi-line).
        strictness: ``safe_harbor`` (default) removes all 18 identifiers.
            ``limited_dataset`` preserves dates and geographic detail.

    Returns:
        DeidentifiedText with the scrubbed text and a list of Redactions
        describing what was removed.
    """
    if not text:
        return DeidentifiedText(text=text or "")

    redactions: list[Redaction] = []
    out = text

    # 1. Emails
    out = _run_pattern(out, _EMAIL_RE, "email", lambda m: "[EMAIL]", redactions)

    # 2. URLs
    out = _run_pattern(out, _URL_RE, "url", lambda m: "[URL]", redactions)

    # 3. IPs
    out = _run_pattern(out, _IP_RE, "ip", lambda m: "[IP]", redactions)

    # 4. SSN
    out = _run_pattern(out, _SSN_RE, "ssn", lambda m: "[SSN]", redactions)

    # 5. Phone
    out = _run_pattern(out, _PHONE_RE, "phone", lambda m: "[PHONE]", redactions)

    # 6. MRN / account / licence / plate / device IDs (labelled values)
    def _labeled_id_repl(m: re.Match[str]) -> str:
        label = m.group(1)
        return f"{label}: [ID]"

    out = _run_pattern(out, _LABELED_ID_RE, "labeled_id", _labeled_id_repl, redactions)

    # 7. Dates → year only (safe_harbor) or preserved (limited_dataset)
    if strictness == "safe_harbor":
        out = _run_pattern(
            out,
            _DATE_NUMERIC_RE,
            "date",
            lambda m: _date_year_only(m.group(3)),
            redactions,
        )
        out = _run_pattern(
            out,
            _DATE_ISO_RE,
            "date",
            lambda m: _date_year_only(m.group(1)),
            redactions,
        )
        out = _run_pattern(
            out,
            _DATE_MONTH_WORD_RE,
            "date",
            lambda m: m.group(len(m.groups())),
            redactions,
        )
        out = _run_pattern(
            out,
            _DATE_DAY_MONTH_RE,
            "date",
            lambda m: m.group(len(m.groups())),
            redactions,
        )

    # 8. Ages over 89 (always, even in limited_dataset)
    def _age_phrase_repl(m: re.Match[str]) -> str:
        return _age_replacement(m.group(1))

    def _age_label_repl(m: re.Match[str]) -> str:
        label = m.group(1)
        age = m.group(2)
        try:
            n = int(age)
        except ValueError:
            return m.group(0)
        if n > 89:
            return f"{label}: 90+"
        return m.group(0)

    out = _run_pattern(out, _AGE_PHRASE_RE, "age", _age_phrase_repl, redactions)
    # Only keep label-based age redactions that actually changed something
    before = out
    out = _AGE_LABEL_RE.sub(_age_label_repl, out)
    if out != before:
        redactions.append(Redaction(kind="age_over_89", original="[label]", replacement="90+"))

    # 9. ZIP (safe_harbor only — limited_dataset keeps full ZIP)
    if strictness == "safe_harbor":
        out = _run_pattern(out, _ZIP_RE, "zip", _zip_replacement, redactions)

    # 10. Names — honorifics and labelled forms
    def _name_honorific_repl(m: re.Match[str]) -> str:
        return f"{m.group(1)}. [NAME]"

    def _name_label_repl(m: re.Match[str]) -> str:
        return f"{m.group(1)}: [NAME]"

    out = _run_pattern(out, _NAME_HONORIFIC_RE, "name", _name_honorific_repl, redactions)
    out = _run_pattern(out, _NAME_LABEL_RE, "name", _name_label_repl, redactions)
    out = _run_pattern(out, _NAME_IS_RE, "name", lambda m: "name is [NAME]", redactions)

    return DeidentifiedText(text=out, redactions=redactions)
