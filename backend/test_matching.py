"""Tests for the matching engine, prompt formatting, JSON parsing, and models."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from matching_engine import _extract_minimal_result, _parse_json_response, _repair_truncated_json
from models import CriterionEvaluation, MatchRequest, MatchResponse, PatientProfile, TrialMatch
from prompts import ELIGIBILITY_ANALYSIS_PROMPT, PATIENT_SUMMARY_PROMPT

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_patient():
    return PatientProfile(
        cancer_type="Non-Small Cell Lung Cancer",
        cancer_stage="Stage IV",
        biomarkers=["EGFR+", "PD-L1 80%", "ALK-"],
        prior_treatments=["Carboplatin/Pemetrexed", "Pembrolizumab"],
        lines_of_therapy=2,
        age=62,
        sex="male",
        ecog_score=1,
        key_labs={"wbc": 5.2, "platelets": 180},
        location_zip="10001",
        willing_to_travel_miles=100,
        additional_conditions=["Type 2 Diabetes"],
        additional_notes="Previously responded well to immunotherapy",
    )


@pytest.fixture
def sample_trial():
    return {
        "nct_id": "NCT12345678",
        "brief_title": "Study of Drug X in NSCLC",
        "phase": "Phase 2",
        "overall_status": "RECRUITING",
        "conditions": ["Non-Small Cell Lung Cancer"],
        "brief_summary": "A study evaluating Drug X in patients with advanced NSCLC.",
        "eligibility_criteria": (
            "Inclusion Criteria:\n"
            "- Stage IV NSCLC\n"
            "- EGFR activating mutation\n"
            "- At least 1 prior line of therapy\n"
            "- ECOG 0-1\n"
            "- Age >= 18\n\n"
            "Exclusion Criteria:\n"
            "- Active brain metastases\n"
            "- Autoimmune disease requiring systemic treatment\n"
        ),
        "locations": [],
        "interventions": ["DRUG: Drug X"],
    }


@pytest.fixture
def valid_analysis_json():
    return {
        "match_score": 85,
        "match_explanation": "You appear to be a strong fit for this trial.",
        "inclusion_evaluations": [
            {"criterion": "Stage IV NSCLC", "status": "met", "explanation": "Patient has Stage IV NSCLC"},
        ],
        "exclusion_evaluations": [
            {
                "criterion": "Active brain metastases",
                "status": "not_triggered",
                "explanation": "No brain mets reported",
            },
        ],
        "flags_for_oncologist": ["Confirm no brain metastases"],
    }


# ---------------------------------------------------------------------------
# JSON parsing tests
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def test_valid_json(self, valid_analysis_json):
        text = json.dumps(valid_analysis_json)
        result = _parse_json_response(text)
        assert result is not None
        assert result["match_score"] == 85

    def test_json_with_whitespace(self, valid_analysis_json):
        text = "  \n" + json.dumps(valid_analysis_json) + "  \n"
        result = _parse_json_response(text)
        assert result is not None
        assert result["match_score"] == 85

    def test_json_with_markdown_fences(self, valid_analysis_json):
        text = "```json\n" + json.dumps(valid_analysis_json) + "\n```"
        result = _parse_json_response(text)
        assert result is not None
        assert result["match_score"] == 85

    def test_json_with_plain_markdown_fences(self, valid_analysis_json):
        text = "```\n" + json.dumps(valid_analysis_json) + "\n```"
        result = _parse_json_response(text)
        assert result is not None
        assert result["match_score"] == 85

    def test_json_with_surrounding_text(self, valid_analysis_json):
        text = "Here is the analysis:\n" + json.dumps(valid_analysis_json) + "\nHope this helps!"
        result = _parse_json_response(text)
        assert result is not None
        assert result["match_score"] == 85

    def test_truncated_json_simple(self):
        """JSON cut off mid-object."""
        text = '{"match_score": 72, "match_explanation": "Likely a good fit", "inclusion_evaluations": ['
        result = _parse_json_response(text)
        assert result is not None
        assert result["match_score"] == 72

    def test_truncated_json_mid_string(self):
        """JSON cut off in the middle of a string value."""
        text = '{"match_score": 55, "match_explanation": "This trial focuses on pati'
        result = _parse_json_response(text)
        assert result is not None
        assert result["match_score"] == 55

    def test_truncated_json_nested(self):
        """JSON cut off inside nested array of objects."""
        text = '{"match_score": 90, "match_explanation": "Strong match", "inclusion_evaluations": [{"criterion": "Stage IV", "status": "met", "explanation": "yes"}, {"criterion": "EGFR+", "status": "met"'
        result = _parse_json_response(text)
        assert result is not None
        assert result["match_score"] == 90

    def test_empty_string(self):
        assert _parse_json_response("") is None

    def test_none_input(self):
        assert _parse_json_response(None) is None

    def test_garbage_text(self):
        assert _parse_json_response("This is not JSON at all") is None

    def test_complete_valid_json_not_modified(self, valid_analysis_json):
        """Ensure we don't mangle already-valid JSON."""
        text = json.dumps(valid_analysis_json)
        result = _parse_json_response(text)
        assert result == valid_analysis_json


class TestRepairTruncatedJson:
    def test_simple_open_object(self):
        text = '{"a": 1, "b": 2'
        result = _repair_truncated_json(text)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["a"] == 1

    def test_nested_open_array(self):
        text = '{"items": [1, 2, 3'
        result = _repair_truncated_json(text)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["items"] == [1, 2, 3]

    def test_already_valid(self):
        text = '{"a": 1}'
        result = _repair_truncated_json(text)
        assert json.loads(result) == {"a": 1}

    def test_trailing_comma(self):
        text = '{"a": 1, "b": 2,'
        result = _repair_truncated_json(text)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["a"] == 1


class TestExtractMinimalResult:
    def test_extracts_score_and_explanation(self):
        text = 'blah "match_score": 75, "match_explanation": "Good fit" blah'
        result = _extract_minimal_result(text, "NCT00000000")
        assert result is not None
        assert result["match_score"] == 75
        assert result["match_explanation"] == "Good fit"

    def test_extracts_score_only(self):
        text = 'something "match_score": 42 something'
        result = _extract_minimal_result(text, "NCT00000000")
        assert result is not None
        assert result["match_score"] == 42
        assert (
            "incomplete" in result["match_explanation"].lower() or "oncologist" in result["match_explanation"].lower()
        )

    def test_no_score_returns_none(self):
        result = _extract_minimal_result("totally unparseable", "NCT00000000")
        assert result is None


# ---------------------------------------------------------------------------
# Prompt formatting tests
# ---------------------------------------------------------------------------


class TestPromptFormatting:
    def test_eligibility_prompt_formats_correctly(self, sample_patient, sample_trial):
        """Ensure the prompt template accepts all expected variables without error."""
        prompt = ELIGIBILITY_ANALYSIS_PROMPT.format(
            cancer_type=sample_patient.cancer_type,
            cancer_stage=sample_patient.cancer_stage,
            biomarkers=", ".join(sample_patient.biomarkers),
            prior_treatments=", ".join(sample_patient.prior_treatments),
            lines_of_therapy=sample_patient.lines_of_therapy,
            age=sample_patient.age,
            sex=sample_patient.sex,
            ecog_score=sample_patient.ecog_score,
            key_labs=json.dumps(sample_patient.key_labs),
            additional_conditions=", ".join(sample_patient.additional_conditions),
            additional_notes=sample_patient.additional_notes,
            nct_id=sample_trial["nct_id"],
            brief_title=sample_trial["brief_title"],
            phase=sample_trial["phase"],
            brief_summary=sample_trial["brief_summary"],
            parsed_criteria="[inc_1] INCLUSION (diagnosis): Stage IV NSCLC",
            enriched_context="",
        )
        assert "EGFR+" in prompt
        assert "Non-Small Cell Lung Cancer" in prompt
        assert "NCT12345678" in prompt
        assert "Stage IV" in prompt
        assert "inc_1" in prompt

    def test_eligibility_prompt_handles_empty_fields(self):
        """Ensure prompt works with minimal/empty patient data."""
        prompt = ELIGIBILITY_ANALYSIS_PROMPT.format(
            cancer_type="Lung Cancer",
            cancer_stage="Stage II",
            biomarkers="None reported",
            prior_treatments="None",
            lines_of_therapy=0,
            age=45,
            sex="female",
            ecog_score="Not reported",
            key_labs="Not reported",
            additional_conditions="None reported",
            additional_notes="None",
            nct_id="NCT00000001",
            brief_title="Test Trial",
            phase="Phase 1",
            brief_summary="A test trial.",
            parsed_criteria="[inc_1] INCLUSION (demographic): Age >= 18",
            enriched_context="",
        )
        assert "None reported" in prompt
        assert "Lung Cancer" in prompt

    def test_patient_summary_prompt_formats(self, sample_patient):
        prompt = PATIENT_SUMMARY_PROMPT.format(
            cancer_type=sample_patient.cancer_type,
            cancer_stage=sample_patient.cancer_stage,
            biomarkers=", ".join(sample_patient.biomarkers),
            prior_treatments=", ".join(sample_patient.prior_treatments),
            lines_of_therapy=sample_patient.lines_of_therapy,
            age=sample_patient.age,
            sex=sample_patient.sex,
            ecog_score=sample_patient.ecog_score,
        )
        assert "EGFR+" in prompt
        assert "Pembrolizumab" in prompt
        assert "62" in prompt

    def test_prompt_contains_classification_guidelines(self):
        """Verify the prompt includes MET/NOT_MET/INSUFFICIENT_INFO guidelines."""
        assert "MET" in ELIGIBILITY_ANALYSIS_PROMPT
        assert "NOT_MET" in ELIGIBILITY_ANALYSIS_PROMPT
        assert "INSUFFICIENT_INFO" in ELIGIBILITY_ANALYSIS_PROMPT
        assert "TRIGGERED" in ELIGIBILITY_ANALYSIS_PROMPT

    def test_prompt_contains_important_rules(self):
        assert "Do NOT default to NOT_MET" in ELIGIBILITY_ANALYSIS_PROMPT
        assert "Missing data" in ELIGIBILITY_ANALYSIS_PROMPT


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------


class TestPatientProfile:
    def test_valid_profile(self, sample_patient):
        assert sample_patient.cancer_type == "Non-Small Cell Lung Cancer"
        assert sample_patient.age == 62
        assert sample_patient.sex == "male"

    def test_minimal_profile(self):
        p = PatientProfile(
            cancer_type="Breast Cancer",
            cancer_stage="Stage III",
            age=50,
            sex="female",
            location_zip="90210",
        )
        assert p.lines_of_therapy == 0
        assert p.biomarkers == []
        assert p.ecog_score is None

    def test_invalid_sex_rejected(self):
        with pytest.raises(Exception):
            PatientProfile(
                cancer_type="Lung Cancer",
                cancer_stage="Stage I",
                age=40,
                sex="other",
                location_zip="10001",
            )

    def test_age_bounds(self):
        with pytest.raises(Exception):
            PatientProfile(
                cancer_type="Lung Cancer",
                cancer_stage="Stage I",
                age=-1,
                sex="male",
                location_zip="10001",
            )
        with pytest.raises(Exception):
            PatientProfile(
                cancer_type="Lung Cancer",
                cancer_stage="Stage I",
                age=121,
                sex="female",
                location_zip="10001",
            )

    def test_ecog_bounds(self):
        with pytest.raises(Exception):
            PatientProfile(
                cancer_type="Lung Cancer",
                cancer_stage="Stage I",
                age=50,
                sex="male",
                location_zip="10001",
                ecog_score=5,
            )

    def test_zip_code_length(self):
        with pytest.raises(Exception):
            PatientProfile(
                cancer_type="Lung Cancer",
                cancer_stage="Stage I",
                age=50,
                sex="male",
                location_zip="123",  # too short
            )


class TestTrialMatch:
    def test_valid_trial_match(self, valid_analysis_json):
        tm = TrialMatch(
            nct_id="NCT12345678",
            brief_title="Test Trial",
            phase="Phase 2",
            overall_status="RECRUITING",
            conditions=["NSCLC"],
            brief_summary="A test trial.",
            eligibility_criteria="Age >= 18",
            match_score=85,
            match_explanation="Strong match.",
            inclusion_evaluations=[
                CriterionEvaluation(criterion="Age", status="met", explanation="OK"),
            ],
            exclusion_evaluations=[],
            flags_for_oncologist=["Check labs"],
        )
        assert tm.match_score == 85

    def test_match_score_bounds(self):
        with pytest.raises(Exception):
            TrialMatch(
                nct_id="NCT12345678",
                brief_title="Test",
                phase="Phase 1",
                overall_status="RECRUITING",
                conditions=[],
                brief_summary="",
                eligibility_criteria="",
                match_score=101,  # out of bounds
                match_explanation="",
                inclusion_evaluations=[],
                exclusion_evaluations=[],
                flags_for_oncologist=[],
            )


class TestMatchRequest:
    def test_valid_request(self, sample_patient):
        req = MatchRequest(patient=sample_patient)
        assert req.max_results == 10

    def test_custom_max_results(self, sample_patient):
        req = MatchRequest(patient=sample_patient, max_results=5)
        assert req.max_results == 5


class TestMatchResponse:
    def test_disclaimer_present(self):
        resp = MatchResponse(
            patient_summary="Summary here",
            matches=[],
            total_trials_screened=0,
        )
        assert "informational purposes" in resp.disclaimer


# ---------------------------------------------------------------------------
# Matching engine integration tests (with mocked Claude API)
# ---------------------------------------------------------------------------


class TestAnalyzeTrial:
    def _criterion_eval_response(self):
        """Build a valid criterion-level evaluation response."""
        return {
            "criterion_evaluations": [
                {
                    "criterion_id": "inc_1",
                    "criterion_text": "Stage IV NSCLC",
                    "type": "inclusion",
                    "status": "MET",
                    "confidence": "HIGH",
                    "reasoning": "Patient has Stage IV NSCLC",
                    "patient_data_used": ["cancer_type", "cancer_stage"],
                },
                {
                    "criterion_id": "inc_2",
                    "criterion_text": "EGFR activating mutation",
                    "type": "inclusion",
                    "status": "MET",
                    "confidence": "HIGH",
                    "reasoning": "Patient biomarkers include EGFR+",
                    "patient_data_used": ["biomarkers"],
                },
                {
                    "criterion_id": "inc_3",
                    "criterion_text": "Age >= 18",
                    "type": "inclusion",
                    "status": "MET",
                    "confidence": "HIGH",
                    "reasoning": "Patient is 62 years old",
                    "patient_data_used": ["age"],
                },
                {
                    "criterion_id": "exc_4",
                    "criterion_text": "Active brain metastases",
                    "type": "exclusion",
                    "status": "NOT_TRIGGERED",
                    "confidence": "MEDIUM",
                    "reasoning": "No brain mets reported",
                    "patient_data_used": [],
                },
            ],
            "flags_for_oncologist": ["Confirm no brain metastases"],
        }

    @pytest.mark.asyncio
    async def test_analyze_trial_success(self, sample_patient, sample_trial):
        from matching_engine import _analyze_trial

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(self._criterion_eval_response()))]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("matching_engine._get_client", return_value=mock_client):
            result = await _analyze_trial(sample_patient, sample_trial)

        assert result is not None
        # Programmatic scoring: 3 MET inclusions, no NOT_MET, no exclusion triggered
        assert result["match_score"] > 80
        assert result["match_tier"] == "STRONG_MATCH"
        assert result["criteria_met"] == 3

    @pytest.mark.asyncio
    async def test_analyze_trial_retries_on_bad_json(self, sample_patient, sample_trial):
        """First call returns garbage, second call returns valid JSON."""
        from matching_engine import _analyze_trial

        bad_response = MagicMock()
        bad_response.content = [MagicMock(text="not json at all")]

        good_response = MagicMock()
        good_response.content = [MagicMock(text=json.dumps(self._criterion_eval_response()))]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[bad_response, good_response])

        with patch("matching_engine._get_client", return_value=mock_client):
            result = await _analyze_trial(sample_patient, sample_trial)

        assert result is not None
        assert result["match_score"] > 0
        assert mock_client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_analyze_trial_handles_api_error(self, sample_patient, sample_trial):
        """API errors should be handled gracefully."""
        from matching_engine import _analyze_trial

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))

        with patch("matching_engine._get_client", return_value=mock_client):
            result = await _analyze_trial(sample_patient, sample_trial)

        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_trial_truncates_long_eligibility(self, sample_patient, sample_trial):
        """Very long eligibility text should be truncated before parsing."""
        from matching_engine import _analyze_trial

        sample_trial["eligibility_criteria"] = "Inclusion Criteria:\n- Age >= 18\n" + "- Some criterion\n" * 500

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(self._criterion_eval_response()))]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("matching_engine._get_client", return_value=mock_client):
            result = await _analyze_trial(sample_patient, sample_trial)

        # Should still produce a result even with long text
        assert result is not None


class TestGeneratePatientSummary:
    @pytest.mark.asyncio
    async def test_summary_success(self, sample_patient):
        from matching_engine import _generate_patient_summary

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="You are a 62-year-old navigating Stage IV NSCLC.")]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("matching_engine._get_client", return_value=mock_client):
            result = await _generate_patient_summary(sample_patient)

        assert "62" in result

    @pytest.mark.asyncio
    async def test_summary_fallback_on_error(self, sample_patient):
        from matching_engine import _generate_patient_summary

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))

        with patch("matching_engine._get_client", return_value=mock_client):
            result = await _generate_patient_summary(sample_patient)

        # Should get a fallback summary, not an exception
        assert "62" in result
        assert "Non-Small Cell Lung Cancer" in result
        assert "Carboplatin/Pemetrexed" in result


# ---------------------------------------------------------------------------
# Adaptive concurrency limiter tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Criteria parser tests
# ---------------------------------------------------------------------------


class TestCriteriaParser:
    def test_parse_basic_eligibility(self):
        from tools.criteria_parser import parse_eligibility_criteria

        text = """
Inclusion Criteria:
- Histologically confirmed NSCLC
- Age >= 18 years
- ECOG performance status 0-1

Exclusion Criteria:
- Active brain metastases
- Prior treatment with osimertinib
"""
        result = parse_eligibility_criteria(text)
        assert result.success
        assert len(result.data["inclusion_criteria"]) == 3
        assert len(result.data["exclusion_criteria"]) == 2
        assert result.data["inclusion_criteria"][0]["category"] == "diagnosis"
        assert result.data["exclusion_criteria"][0]["category"] == "disease_status"

    def test_parse_numbered_list(self):
        from tools.criteria_parser import parse_eligibility_criteria

        text = """
Inclusion Criteria:
1. Age 18 or older
2. EGFR mutation confirmed
3. At least one prior line of therapy

Exclusion Criteria:
1. Pregnant or breastfeeding
2. Active autoimmune disease
"""
        result = parse_eligibility_criteria(text)
        assert result.success
        assert len(result.data["inclusion_criteria"]) == 3
        assert len(result.data["exclusion_criteria"]) == 2

    def test_parse_no_headers(self):
        from tools.criteria_parser import parse_eligibility_criteria

        text = (
            """- Age greater than or equal to 18 years\n- ECOG performance status 0 or 1\n- Adequate organ function"""
        )
        result = parse_eligibility_criteria(text)
        assert result.success
        # All treated as inclusion when no exclusion header
        assert len(result.data["inclusion_criteria"]) == 3
        assert len(result.data["exclusion_criteria"]) == 0

    def test_parse_empty_text(self):
        from tools.criteria_parser import parse_eligibility_criteria

        result = parse_eligibility_criteria("")
        assert not result.success

    def test_classification_categories(self):
        from tools.criteria_parser import _classify_criterion

        assert _classify_criterion("EGFR mutation positive") == "biomarker"
        assert _classify_criterion("Age >= 18 years") == "demographic"
        assert _classify_criterion("ECOG performance status 0-1") == "performance"
        assert _classify_criterion("Adequate hepatic function") == "labs"
        assert _classify_criterion("Prior chemotherapy required") == "prior_therapy"
        assert _classify_criterion("Active brain metastases") == "disease_status"


# ---------------------------------------------------------------------------
# Programmatic scoring tests
# ---------------------------------------------------------------------------


class TestProgrammaticScoring:
    def test_strong_match(self):
        from tools.scoring import calculate_match_score

        evals = [
            {"type": "inclusion", "status": "MET", "confidence": "HIGH"},
            {"type": "inclusion", "status": "MET", "confidence": "HIGH"},
            {"type": "inclusion", "status": "MET", "confidence": "HIGH"},
            {"type": "exclusion", "status": "NOT_TRIGGERED", "confidence": "HIGH"},
        ]
        result = calculate_match_score(evals)
        assert result["score"] >= 75
        assert result["tier"] == "STRONG_MATCH"
        assert result["criteria_met"] == 3

    def test_exclusion_triggered_scores_zero(self):
        from tools.scoring import calculate_match_score

        evals = [
            {"type": "inclusion", "status": "MET", "confidence": "HIGH"},
            {"type": "exclusion", "status": "TRIGGERED", "confidence": "HIGH", "criterion_text": "Prior immunotherapy"},
        ]
        result = calculate_match_score(evals)
        assert result["score"] == 0
        assert result["tier"] == "EXCLUDED"

    def test_mixed_results(self):
        from tools.scoring import calculate_match_score

        evals = [
            {"type": "inclusion", "status": "MET", "confidence": "HIGH"},
            {"type": "inclusion", "status": "MET", "confidence": "MEDIUM"},
            {"type": "inclusion", "status": "INSUFFICIENT_INFO", "confidence": "LOW"},
            {"type": "inclusion", "status": "NOT_MET", "confidence": "HIGH"},
            {"type": "exclusion", "status": "NOT_TRIGGERED", "confidence": "MEDIUM"},
        ]
        result = calculate_match_score(evals)
        assert 20 < result["score"] < 70
        assert result["criteria_met"] == 2
        assert result["criteria_not_met"] == 1
        assert result["criteria_unknown"] == 1

    def test_all_unknown(self):
        from tools.scoring import calculate_match_score

        evals = [
            {"type": "inclusion", "status": "INSUFFICIENT_INFO", "confidence": "LOW"},
            {"type": "inclusion", "status": "INSUFFICIENT_INFO", "confidence": "LOW"},
            {"type": "inclusion", "status": "INSUFFICIENT_INFO", "confidence": "LOW"},
        ]
        result = calculate_match_score(evals)
        # 0.3 weight per unknown = 30 base
        assert result["score"] < 40
        assert result["tier"] in ("PARTIAL_MATCH", "UNLIKELY_MATCH")

    def test_score_differentiation(self):
        """Different criterion mixes should produce different scores."""
        from tools.scoring import calculate_match_score

        # All MET
        all_met = [{"type": "inclusion", "status": "MET", "confidence": "HIGH"} for _ in range(5)]
        # Half MET, half unknown
        half = [{"type": "inclusion", "status": "MET", "confidence": "HIGH"} for _ in range(3)] + [
            {"type": "inclusion", "status": "INSUFFICIENT_INFO", "confidence": "LOW"} for _ in range(3)
        ]
        # Mostly NOT_MET
        bad = [{"type": "inclusion", "status": "NOT_MET", "confidence": "HIGH"} for _ in range(3)] + [
            {"type": "inclusion", "status": "MET", "confidence": "HIGH"}
        ]

        s1 = calculate_match_score(all_met)["score"]
        s2 = calculate_match_score(half)["score"]
        s3 = calculate_match_score(bad)["score"]

        assert s1 > s2 > s3, f"Expected {s1} > {s2} > {s3}"

    def test_critical_not_met_low_score(self):
        from tools.scoring import calculate_match_score

        evals = [
            {
                "type": "inclusion",
                "status": "NOT_MET",
                "confidence": "HIGH",
                "category": "biomarker",
                "criterion_text": "EGFR mutation required",
            },
            {"type": "inclusion", "status": "MET", "confidence": "HIGH"},
        ]
        result = calculate_match_score(evals)
        assert result["score"] <= 10
        assert result["tier"] == "EXCLUDED"


# ---------------------------------------------------------------------------
# Adaptive concurrency limiter tests
# ---------------------------------------------------------------------------


class TestAdaptiveConcurrencyLimiter:
    @pytest.mark.asyncio
    async def test_initial_concurrency(self):
        from tools.claude_api import AdaptiveConcurrencyLimiter

        limiter = AdaptiveConcurrencyLimiter(max_concurrent=5)
        assert limiter.current_concurrency == 5

    @pytest.mark.asyncio
    async def test_backoff_on_rate_limit(self):
        from tools.claude_api import AdaptiveConcurrencyLimiter

        limiter = AdaptiveConcurrencyLimiter(max_concurrent=8, min_concurrent=1)
        assert limiter.current_concurrency == 8

        await limiter.on_rate_limit()
        assert limiter.current_concurrency == 4

        await limiter.on_rate_limit()
        assert limiter.current_concurrency == 2

        await limiter.on_rate_limit()
        assert limiter.current_concurrency == 1

        # Should not go below min
        await limiter.on_rate_limit()
        assert limiter.current_concurrency == 1

    @pytest.mark.asyncio
    async def test_ramp_up_on_success(self):
        from tools.claude_api import AdaptiveConcurrencyLimiter

        limiter = AdaptiveConcurrencyLimiter(max_concurrent=10, min_concurrent=1)
        # Back off first
        await limiter.on_rate_limit()
        low = limiter.current_concurrency

        # Success calls should ramp up
        for _ in range(limiter._ramp_up_threshold):
            await limiter.on_success()
        assert limiter.current_concurrency == low + 1

    @pytest.mark.asyncio
    async def test_does_not_exceed_max(self):
        from tools.claude_api import AdaptiveConcurrencyLimiter

        limiter = AdaptiveConcurrencyLimiter(max_concurrent=3)
        # Already at max — success shouldn't increase
        for _ in range(20):
            await limiter.on_success()
        assert limiter.current_concurrency == 3

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        from tools.claude_api import AdaptiveConcurrencyLimiter

        limiter = AdaptiveConcurrencyLimiter(max_concurrent=2)
        await limiter.acquire()
        await limiter.acquire()
        limiter.release()
        limiter.release()
        # Should not deadlock — if we get here, it works
