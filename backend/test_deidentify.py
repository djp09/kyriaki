"""Tests for phi.deidentify — HIPAA Safe Harbor scrubber.

Coverage targets each of the 18 §164.514(b)(2) identifiers plus fuzz
cases: names embedded in sentences, partial dates, multi-line notes.
"""

from __future__ import annotations

import pytest

from phi.deidentify import SAFE_HARBOR_EXCLUDED_ZIP3, deidentify

# --- Emails, URLs, IPs ---


def test_email_is_redacted() -> None:
    r = deidentify("Contact me at jane.doe+tag@example.co.uk for details.")
    assert "[EMAIL]" in r.text
    assert "jane.doe" not in r.text
    assert r.redaction_report == {"email": 1}


def test_url_is_redacted() -> None:
    r = deidentify("See https://hospital.example.com/records/123 and www.foo.bar/x")
    assert "[URL]" in r.text
    assert "hospital.example.com" not in r.text
    assert r.redaction_report["url"] == 2


def test_ip_address_is_redacted() -> None:
    r = deidentify("Logged in from 192.168.1.42 yesterday.")
    assert "[IP]" in r.text
    assert "192.168.1.42" not in r.text


# --- SSN, Phone ---


def test_ssn_is_redacted() -> None:
    r = deidentify("SSN: 123-45-6789 on file.")
    assert "[SSN]" in r.text
    assert "123-45-6789" not in r.text


@pytest.mark.parametrize(
    "phone",
    [
        "(555) 123-4567",
        "555-123-4567",
        "555.123.4567",
        "555 123 4567",
        "+1 555-123-4567",
        "1-555-123-4567",
    ],
)
def test_phone_formats_are_redacted(phone: str) -> None:
    r = deidentify(f"Call {phone} for intake.")
    assert "[PHONE]" in r.text
    assert "4567" not in r.text
    assert r.redaction_report.get("phone", 0) == 1


def test_phone_does_not_match_plain_long_number() -> None:
    # 10 consecutive digits with no separator could be anything; skip.
    r = deidentify("Trial enrolled 5551234567 patients last year.")
    # We don't require redaction here, just assert the text survives (no phone match on pure digits).
    # The ZIP regex should not match either (not 5 digits at a boundary).
    assert "5551234567" in r.text


# --- MRN / labelled IDs ---


def test_mrn_is_redacted() -> None:
    r = deidentify("MRN: 0001234 admitted for workup.")
    assert "[ID]" in r.text
    assert "0001234" not in r.text


def test_medical_record_number_phrase() -> None:
    r = deidentify("Medical Record Number 9876543 assigned to patient.")
    assert "[ID]" in r.text
    assert "9876543" not in r.text


def test_account_number() -> None:
    r = deidentify("Account #: AB-12345 posted 03/10/2023.")
    assert "[ID]" in r.text
    assert "AB-12345" not in r.text


# --- Dates ---


@pytest.mark.parametrize(
    "date_str,expected_year",
    [
        ("03/15/2024", "2024"),
        ("3-15-2024", "2024"),
        ("2024-03-15", "2024"),
        ("March 15, 2024", "2024"),
        ("15 March 2024", "2024"),
        ("Jan 3rd, 1999", "1999"),
    ],
)
def test_dates_reduced_to_year(date_str: str, expected_year: str) -> None:
    r = deidentify(f"Seen on {date_str} in clinic.")
    assert expected_year in r.text
    assert date_str not in r.text
    assert r.redaction_report.get("date", 0) >= 1


def test_partial_two_digit_year_becomes_placeholder() -> None:
    r = deidentify("Visit on 3/15/24 noted.")
    # Two-digit years cannot be safely recovered, so they become [DATE].
    assert "[DATE]" in r.text
    assert "3/15/24" not in r.text


def test_limited_dataset_preserves_dates() -> None:
    r = deidentify("Seen on 03/15/2024.", strictness="limited_dataset")
    assert "03/15/2024" in r.text
    assert r.redaction_report.get("date", 0) == 0


# --- Ages ---


def test_age_over_89_bucketed() -> None:
    r = deidentify("95-year-old female with NSCLC.")
    assert "90+" in r.text
    assert "95" not in r.text


def test_age_label_over_89() -> None:
    r = deidentify("Age: 92 at diagnosis.")
    assert "90+" in r.text
    assert "92" not in r.text


def test_age_under_89_preserved() -> None:
    r = deidentify("45-year-old male, ECOG 1.")
    assert "45" in r.text
    assert "90+" not in r.text


def test_y_o_shorthand_bucketed() -> None:
    r = deidentify("Pt is 97 y.o. with metastatic disease.")
    assert "90+" in r.text
    assert "97" not in r.text


# --- ZIP codes ---


def test_full_zip_reduced_to_zip3() -> None:
    r = deidentify("Lives in 94110, San Francisco.")
    assert "941XX" in r.text
    assert "94110" not in r.text


def test_zip_plus_four_reduced() -> None:
    r = deidentify("Mail to 02138-1234.")
    assert "021XX" in r.text
    assert "02138" not in r.text


def test_excluded_zip3_becomes_zeros() -> None:
    # 036 is on the Safe Harbor excluded list.
    assert "036" in SAFE_HARBOR_EXCLUDED_ZIP3
    r = deidentify("Lives near ZIP 03601.")
    assert "000" in r.text
    assert "036" not in r.text.replace("000", "")


def test_limited_dataset_preserves_zip() -> None:
    r = deidentify("Lives in 94110.", strictness="limited_dataset")
    assert "94110" in r.text


# --- Names ---


def test_honorific_name_is_redacted() -> None:
    r = deidentify("Dr. Jane Smith reviewed the case.")
    assert "[NAME]" in r.text
    assert "Jane Smith" not in r.text


def test_mr_mrs_ms_honorifics() -> None:
    for honorific in ("Mr", "Mrs", "Ms", "Miss"):
        r = deidentify(f"{honorific}. John Doe arrived.")
        assert "[NAME]" in r.text
        assert "John Doe" not in r.text


def test_patient_name_label() -> None:
    r = deidentify("Patient Name: Jane Q. Public, MRN 123456.")
    assert "[NAME]" in r.text
    assert "Jane" not in r.text


def test_name_is_phrase() -> None:
    r = deidentify("The patient's name is Robert Jones per intake form.")
    assert "[NAME]" in r.text
    assert "Robert Jones" not in r.text


def test_conservative_capitalised_tokens_preserved() -> None:
    # Clinical vocabulary must survive: we should not flag arbitrary
    # capitalised pairs.
    sample = "Stage IV Non Small Cell Lung Cancer in New York state."
    r = deidentify(sample)
    assert "Stage IV" in r.text
    assert "Non Small" in r.text
    assert "New York" in r.text
    assert r.redaction_report.get("name", 0) == 0


# --- Fuzz / composite cases ---


def test_multi_line_clinical_note() -> None:
    note = """\
Patient Name: John A. Smith
DOB: 03/15/1932 (age 92)
MRN: 00012345
Phone: (555) 123-4567
Email: jsmith@example.com
ZIP: 94110

HPI: 92-year-old male presented on 04/10/2024 with dyspnea.
Seen at 123 Main St clinic. Contact dr.jones@example.com.
"""
    r = deidentify(note)
    # Every direct identifier scrubbed
    assert "Smith" not in r.text
    assert "03/15/1932" not in r.text
    assert "00012345" not in r.text
    assert "(555)" not in r.text
    assert "jsmith@example.com" not in r.text
    assert "dr.jones@example.com" not in r.text
    assert "94110" not in r.text
    assert "92-year-old" not in r.text
    # Year-only dates remain
    assert "1932" in r.text
    assert "2024" in r.text
    # Multiple kinds of redaction present
    report = r.redaction_report
    assert report["email"] >= 2
    assert report["phone"] >= 1
    assert report["name"] >= 1
    assert report["labeled_id"] >= 1
    assert report["date"] >= 2
    assert report["zip"] >= 1
    assert report["age"] >= 1


def test_empty_and_whitespace_input() -> None:
    assert deidentify("").text == ""
    assert deidentify("   ").text == "   "
    assert deidentify("   ").is_clean()


def test_clean_text_has_no_redactions() -> None:
    r = deidentify("Stage IV NSCLC, EGFR+, on osimertinib, ECOG 1.")
    assert r.is_clean()
    assert r.text == "Stage IV NSCLC, EGFR+, on osimertinib, ECOG 1."


def test_multiple_emails_counted() -> None:
    r = deidentify("Email a@b.com or c@d.org or e@f.net.")
    assert r.redaction_report["email"] == 3
    assert "[EMAIL]" in r.text


def test_name_embedded_between_punctuation() -> None:
    r = deidentify("Signed: Dr. Alice Walker, MD, PhD")
    assert "[NAME]" in r.text
    assert "Alice Walker" not in r.text
