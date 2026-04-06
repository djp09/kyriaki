"""Tests for Gemma pipeline stages 1, 3, and 4.

Tests are structured in two tiers:
- Unit tests: mock the Gemma client, test prompt construction + schema validation
- Integration tests: require running Ollama (skipped in CI via GEMMA_INTEGRATION marker)

Run unit tests:     pytest backend/test_gemma_pipeline.py -v
Run integration:    pytest backend/test_gemma_pipeline.py -v -m gemma_integration
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from criterion_extraction import Criterion, ExtractedCriteria, extract_criteria
from gemma_client import GemmaSchemaError, OllamaGemmaClient, reset_gemma_client
from intake import NormalizedIntake, normalize_intake
from semantic_recall import (
    _cosine_similarity,
    build_patient_summary,
    build_trial_summary,
    rank_trials_by_similarity,
    text_hash,
)

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the global Gemma client singleton between tests."""
    reset_gemma_client()
    yield
    reset_gemma_client()


def _mock_gemma(return_value):
    """Create a mock GemmaClient that returns the given value from generate()."""
    mock_client = AsyncMock(spec=OllamaGemmaClient)
    mock_client.generate.return_value = return_value
    mock_client.embed.return_value = []
    return mock_client


# ──────────────────────────────────────────────────────────────
# Stage 1 — Intake normalization
# ──────────────────────────────────────────────────────────────


class TestIntakeNormalization:
    """Unit tests for Stage 1 intake normalization."""

    @pytest.mark.asyncio
    async def test_basic_nsclc(self):
        mock_result = NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
            biomarkers=["EGFR+", "PD-L1 80%"],
            prior_treatments=["Osimertinib", "Carboplatin/Pemetrexed"],
            lines_of_therapy=2,
            ecog_score=1,
        )
        with patch("intake.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await normalize_intake(
                "62F stage 4 lung cancer, EGFR positive, PD-L1 80%, was on Tagrisso then carbo/pem",
                form_hints={"sex": "female", "age": 62},
            )
        assert result.cancer_type == "Non-Small Cell Lung Carcinoma"
        assert result.cancer_stage == "Stage IV"
        assert "EGFR+" in result.biomarkers
        assert result.lines_of_therapy == 2

    @pytest.mark.asyncio
    async def test_tnbc_brca(self):
        mock_result = NormalizedIntake(
            cancer_type="Triple-Negative Breast Cancer",
            cancer_stage="Stage IIIB",
            biomarkers=["BRCA1+"],
            prior_treatments=["AC-T"],
            lines_of_therapy=1,
        )
        with patch("intake.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await normalize_intake("54F TNBC stage IIIB BRCA1+, had AC-T")
        assert result.cancer_type == "Triple-Negative Breast Cancer"
        assert result.prior_treatments == ["AC-T"]
        assert result.lines_of_therapy == 1

    @pytest.mark.asyncio
    async def test_brand_to_generic(self):
        mock_result = NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            biomarkers=["ALK+"],
            prior_treatments=["Crizotinib", "Alectinib"],
            lines_of_therapy=2,
        )
        with patch("intake.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await normalize_intake("ALK-positive lung cancer, took Xalkori then Alecensa")
        assert "ALK+" in result.biomarkers
        assert "Crizotinib" in result.prior_treatments
        assert "Alectinib" in result.prior_treatments

    @pytest.mark.asyncio
    async def test_metastatic_maps_to_stage_iv(self):
        mock_result = NormalizedIntake(
            cancer_type="Metastatic Colorectal Carcinoma",
            cancer_stage="Stage IV",
            biomarkers=["KRAS G12C"],
            prior_treatments=["FOLFOX", "FOLFIRI/Bevacizumab"],
            lines_of_therapy=2,
        )
        with patch("intake.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await normalize_intake("mCRC KRAS G12C, FOLFOX then FOLFIRI+bev")
        assert result.cancer_stage == "Stage IV"

    @pytest.mark.asyncio
    async def test_ecog_null_when_qualitative(self):
        mock_result = NormalizedIntake(
            cancer_type="Ovarian Carcinoma",
            biomarkers=["BRCA2+"],
            ecog_score=None,
            normalization_notes="ECOG not stated numerically.",
        )
        with patch("intake.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await normalize_intake("ovarian cancer BRCA2 mutation, gets tired easily")
        assert result.ecog_score is None

    @pytest.mark.asyncio
    async def test_empty_input(self):
        mock_result = NormalizedIntake(
            normalization_notes="No input provided.",
        )
        with patch("intake.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await normalize_intake("", form_hints=None)
        assert result.cancer_type is None

    @pytest.mark.asyncio
    async def test_form_hints_passed_to_prompt(self):
        mock_result = NormalizedIntake(cancer_type="Non-Small Cell Lung Carcinoma")
        mock_client = _mock_gemma(mock_result)
        with patch("intake.get_gemma_client", return_value=mock_client):
            await normalize_intake("lung cancer", form_hints={"age": 55, "sex": "male"})
        call_args = mock_client.generate.call_args
        prompt = call_args[0][0]
        assert "age: 55" in prompt
        assert "sex: male" in prompt

    @pytest.mark.asyncio
    async def test_schema_error_propagates(self):
        mock_client = AsyncMock(spec=OllamaGemmaClient)
        mock_client.generate.side_effect = GemmaSchemaError("bad json")
        with patch("intake.get_gemma_client", return_value=mock_client), pytest.raises(GemmaSchemaError):
            await normalize_intake("some input")

    @pytest.mark.asyncio
    async def test_multiple_biomarkers(self):
        mock_result = NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            biomarkers=["EGFR+", "PD-L1 80%", "ALK-", "ROS1-"],
        )
        with patch("intake.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await normalize_intake("NSCLC EGFR+, PD-L1 80%, ALK neg, ROS1 neg")
        assert len(result.biomarkers) == 4

    @pytest.mark.asyncio
    async def test_pediatric_case(self):
        mock_result = NormalizedIntake(
            cancer_type="Neuroblastoma",
            cancer_stage="Stage IV",
            biomarkers=["MYCN Amplified"],
            prior_treatments=["Cyclophosphamide/Doxorubicin/Vincristine"],
            lines_of_therapy=1,
        )
        with patch("intake.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await normalize_intake("3yo with neuroblastoma stage 4 MYCN amplified, had chemo")
        assert result.cancer_type == "Neuroblastoma"


# ──────────────────────────────────────────────────────────────
# Stage 4 — Criterion extraction
# ──────────────────────────────────────────────────────────────


class TestCriterionExtraction:
    """Unit tests for Stage 4 criterion extraction."""

    @pytest.mark.asyncio
    async def test_basic_extraction(self):
        mock_result = ExtractedCriteria(
            criteria=[
                Criterion(type="inclusion", text="Age >= 18 years", category="demographic"),
                Criterion(type="inclusion", text="ECOG 0-1", category="performance"),
                Criterion(type="exclusion", text="Active brain metastases", category="disease_status"),
            ]
        )
        with patch("criterion_extraction.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await extract_criteria("Inclusion:\n1. Age >= 18\n2. ECOG 0-1\nExclusion:\n1. Active brain mets")
        assert len(result.criteria) == 3
        inc = [c for c in result.criteria if c.type == "inclusion"]
        exc = [c for c in result.criteria if c.type == "exclusion"]
        assert len(inc) == 2
        assert len(exc) == 1

    @pytest.mark.asyncio
    async def test_empty_eligibility_text(self):
        result = await extract_criteria("")
        assert len(result.criteria) == 0
        assert "Empty" in result.extraction_notes

    @pytest.mark.asyncio
    async def test_compound_criteria_split(self):
        mock_result = ExtractedCriteria(
            criteria=[
                Criterion(type="inclusion", text="Age >= 18 years", category="demographic"),
                Criterion(type="inclusion", text="Histologically confirmed NSCLC", category="diagnosis"),
            ]
        )
        with patch("criterion_extraction.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await extract_criteria("Age >= 18 with histologically confirmed NSCLC")
        assert len(result.criteria) == 2

    @pytest.mark.asyncio
    async def test_lab_criteria_split(self):
        mock_result = ExtractedCriteria(
            criteria=[
                Criterion(type="inclusion", text="ANC >= 1500/uL", category="labs"),
                Criterion(type="inclusion", text="Platelets >= 100,000/uL", category="labs"),
                Criterion(type="inclusion", text="Hemoglobin >= 9.0 g/dL", category="labs"),
            ]
        )
        with patch("criterion_extraction.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await extract_criteria("Adequate organ function: ANC >= 1500, Plt >= 100k, Hgb >= 9")
        assert all(c.category == "labs" for c in result.criteria)

    @pytest.mark.asyncio
    async def test_categories_valid(self):
        valid_categories = {
            "diagnosis",
            "stage",
            "biomarker",
            "prior_therapy",
            "demographic",
            "performance",
            "labs",
            "comorbidity",
            "washout",
            "disease_status",
            "consent",
            "other",
        }
        mock_result = ExtractedCriteria(
            criteria=[Criterion(type="inclusion", text="test", category=cat) for cat in valid_categories]
        )
        with patch("criterion_extraction.get_gemma_client", return_value=_mock_gemma(mock_result)):
            result = await extract_criteria("test text")
        for c in result.criteria:
            assert c.category in valid_categories


# ──────────────────────────────────────────────────────────────
# Stage 3 — Semantic recall
# ──────────────────────────────────────────────────────────────


class TestSemanticRecall:
    """Unit tests for Stage 3 semantic recall."""

    def test_cosine_similarity_identical(self):
        v = [1.0, 2.0, 3.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_cosine_similarity_zero_vector(self):
        assert _cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0

    def test_text_hash_deterministic(self):
        h1 = text_hash("hello world")
        h2 = text_hash("hello world")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_text_hash_changes(self):
        assert text_hash("hello") != text_hash("world")

    def test_build_patient_summary(self):
        patient = {
            "cancer_type": "Non-Small Cell Lung Carcinoma",
            "cancer_stage": "Stage IV",
            "biomarkers": ["EGFR+", "PD-L1 80%"],
            "prior_treatments": ["Osimertinib"],
            "lines_of_therapy": 1,
            "ecog_score": 1,
        }
        summary = build_patient_summary(patient)
        assert "Non-Small Cell Lung Carcinoma" in summary
        assert "EGFR+" in summary
        assert "Osimertinib" in summary
        assert "ECOG 1" in summary
        # Should NOT contain identifiers
        assert "name" not in summary.lower()
        assert "zip" not in summary.lower()

    def test_build_patient_summary_empty(self):
        assert build_patient_summary({}) == ""

    def test_build_trial_summary(self):
        trial = {
            "brief_title": "EGFR TKI for Stage IV NSCLC",
            "conditions": ["NSCLC"],
            "phase": "PHASE3",
        }
        summary = build_trial_summary(trial)
        assert "EGFR TKI" in summary
        assert "NSCLC" in summary

    @pytest.mark.asyncio
    async def test_rank_trials_empty(self):
        result = await rank_trials_by_similarity({}, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_rank_trials_ordering(self):
        """Mock embeddings to verify ranking logic works correctly."""
        # Patient embedding similar to trial A, dissimilar to trial B
        patient_emb = [1.0, 0.0, 0.0]
        trial_a_emb = [0.9, 0.1, 0.0]  # similar to patient
        trial_b_emb = [0.0, 0.0, 1.0]  # orthogonal to patient

        mock_client = AsyncMock(spec=OllamaGemmaClient)
        mock_client.embed.return_value = [patient_emb, trial_a_emb, trial_b_emb]

        trials = [
            {"brief_title": "Trial A", "conditions": ["NSCLC"]},
            {"brief_title": "Trial B", "conditions": ["TNBC"]},
        ]
        patient = {"cancer_type": "NSCLC"}

        with patch("semantic_recall.get_gemma_client", return_value=mock_client):
            results = await rank_trials_by_similarity(patient, trials, top_n=2)

        assert len(results) == 2
        assert results[0][0]["brief_title"] == "Trial A"
        assert results[0][1] > results[1][1]  # A scores higher

    @pytest.mark.asyncio
    async def test_rank_trials_top_n(self):
        """Top-N limiting works."""
        mock_client = AsyncMock(spec=OllamaGemmaClient)
        # 1 patient + 5 trials
        mock_client.embed.return_value = [[float(i)] * 3 for i in range(6)]

        trials = [{"brief_title": f"Trial {i}"} for i in range(5)]
        patient = {"cancer_type": "test"}

        with patch("semantic_recall.get_gemma_client", return_value=mock_client):
            results = await rank_trials_by_similarity(patient, trials, top_n=2)

        assert len(results) == 2


# ──────────────────────────────────────────────────────────────
# Gemma client
# ──────────────────────────────────────────────────────────────


class TestGemmaClient:
    """Unit tests for the Gemma client abstraction."""

    @pytest.mark.asyncio
    async def test_generate_plain_text(self):
        client = OllamaGemmaClient()
        with patch.object(client, "_call_generate", new_callable=AsyncMock, return_value="hello"):
            result = await client.generate("say hi")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_generate_with_schema_valid(self):
        client = OllamaGemmaClient()
        valid_json = json.dumps({"cancer_type": "NSCLC", "biomarkers": [], "lines_of_therapy": 0})
        with patch.object(client, "_call_generate", new_callable=AsyncMock, return_value=valid_json):
            result = await client.generate("test", schema=NormalizedIntake)
        assert isinstance(result, NormalizedIntake)
        assert result.cancer_type == "NSCLC"

    @pytest.mark.asyncio
    async def test_generate_with_schema_retry(self):
        client = OllamaGemmaClient()
        bad_json = "not json"
        valid_json = json.dumps({"cancer_type": "NSCLC", "biomarkers": [], "lines_of_therapy": 0})
        call_count = 0

        async def _fake_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return bad_json if call_count == 1 else valid_json

        with patch.object(client, "_call_generate", side_effect=_fake_generate):
            result = await client.generate("test", schema=NormalizedIntake, max_retries=2)
        assert isinstance(result, NormalizedIntake)
        assert call_count == 2  # first attempt failed, second succeeded

    @pytest.mark.asyncio
    async def test_generate_with_schema_exhausted_retries(self):
        client = OllamaGemmaClient()
        with (
            patch.object(client, "_call_generate", new_callable=AsyncMock, return_value="not json"),
            pytest.raises(GemmaSchemaError),
        ):
            await client.generate("test", schema=NormalizedIntake, max_retries=1)


# ──────────────────────────────────────────────────────────────
# Pipeline integration — MatchingAgent helper methods
# ──────────────────────────────────────────────────────────────


class TestMatchingAgentGemmaHelpers:
    """Test the Gemma helper methods wired into MatchingAgent."""

    def _make_patient(self, **overrides):
        defaults = {
            "cancer_type": "Non-Small Cell Lung Carcinoma",
            "cancer_stage": "Stage IV",
            "biomarkers": ["EGFR+"],
            "prior_treatments": ["Osimertinib"],
            "lines_of_therapy": 1,
            "age": 62,
            "sex": "female",
            "location_zip": "94102",
            "additional_notes": None,
        }
        defaults.update(overrides)
        from models import PatientProfile

        return PatientProfile(**defaults)

    def _make_agent(self):
        from agents import MatchingAgent

        return MatchingAgent()

    def test_merge_normalized_preserves_form_fields(self):
        """Form-provided fields are ground truth — Gemma can't overwrite."""
        agent = self._make_agent()
        patient = self._make_patient(cancer_type="NSCLC")
        normalized = NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",  # Gemma has better name
            biomarkers=["PD-L1 80%"],  # New biomarker from notes
        )
        result = agent._merge_normalized(patient, normalized)
        # cancer_type keeps form value because it's non-empty
        assert result.cancer_type == "NSCLC"
        # biomarker is added (union)
        assert "PD-L1 80%" in result.biomarkers
        assert "EGFR+" in result.biomarkers

    def test_merge_normalized_fills_empty_fields(self):
        """Gemma fills in empty/missing fields."""
        agent = self._make_agent()
        patient = self._make_patient(cancer_type="", cancer_stage="", ecog_score=None)
        normalized = NormalizedIntake(
            cancer_type="Non-Small Cell Lung Carcinoma",
            cancer_stage="Stage IV",
            ecog_score=1,
        )
        result = agent._merge_normalized(patient, normalized)
        assert result.cancer_type == "Non-Small Cell Lung Carcinoma"
        assert result.cancer_stage == "Stage IV"
        assert result.ecog_score == 1

    def test_merge_normalized_no_duplicates(self):
        """Merging doesn't create duplicate biomarkers or treatments."""
        agent = self._make_agent()
        patient = self._make_patient(biomarkers=["EGFR+"], prior_treatments=["Osimertinib"])
        normalized = NormalizedIntake(
            biomarkers=["EGFR+", "PD-L1 80%"],
            prior_treatments=["Osimertinib", "Carboplatin/Pemetrexed"],
            lines_of_therapy=2,
        )
        result = agent._merge_normalized(patient, normalized)
        assert result.biomarkers == ["EGFR+", "PD-L1 80%"]
        assert result.prior_treatments == ["Osimertinib", "Carboplatin/Pemetrexed"]

    def test_merge_normalized_noop(self):
        """When nothing to merge, returns same patient."""
        agent = self._make_agent()
        patient = self._make_patient()
        normalized = NormalizedIntake()
        result = agent._merge_normalized(patient, normalized)
        assert result is patient

    @pytest.mark.asyncio
    async def test_normalize_intake_fallback_on_error(self):
        """Stage 1 returns original patient on Gemma failure."""
        agent = self._make_agent()
        patient = self._make_patient(additional_notes="some notes")
        with patch("intake.normalize_intake", side_effect=Exception("ollama down")):
            result = await agent._normalize_intake(patient)
        assert result is patient

    @pytest.mark.asyncio
    async def test_semantic_rank_disabled(self):
        """Stage 3 returns pool unchanged when disabled."""
        agent = self._make_agent()
        patient = self._make_patient()
        pool = {f"NCT{i:08d}": {"nct_id": f"NCT{i:08d}"} for i in range(60)}
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.gemma_stage3_enabled = False
        result = await agent._semantic_rank(pool, patient, settings)
        assert result is pool

    @pytest.mark.asyncio
    async def test_semantic_rank_small_pool_skipped(self):
        """Stage 3 skips ranking when pool < 50."""
        agent = self._make_agent()
        patient = self._make_patient()
        pool = {f"NCT{i:08d}": {"nct_id": f"NCT{i:08d}"} for i in range(30)}
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.gemma_stage3_enabled = True
        result = await agent._semantic_rank(pool, patient, settings)
        assert result is pool

    @pytest.mark.asyncio
    async def test_semantic_rank_fallback_on_error(self):
        """Stage 3 returns pool unchanged on embedding failure."""
        agent = self._make_agent()
        patient = self._make_patient()
        pool = {f"NCT{i:08d}": {"nct_id": f"NCT{i:08d}"} for i in range(60)}
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.gemma_stage3_enabled = True
        with patch("semantic_recall.rank_trials_by_similarity", side_effect=Exception("embed failed")):
            result = await agent._semantic_rank(pool, patient, settings)
        assert result is pool

    @pytest.mark.asyncio
    async def test_get_cached_criteria_disabled(self):
        """Stage 4 returns None when disabled."""
        agent = self._make_agent()
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.gemma_stage4_enabled = False
        result = await agent._get_cached_criteria("NCT123", "some text", settings)
        assert result is None

    def _get_agent_class(self):
        from agents import MatchingAgent

        return MatchingAgent

    def test_biomarker_search_terms_egfr(self):
        """EGFR+ should produce EGFR intervention search."""
        cls = self._get_agent_class()
        intr, term = cls._biomarker_search_terms(["EGFR L858R+"])
        assert intr == "EGFR"
        assert "EGFR" in term

    def test_biomarker_search_terms_alk(self):
        cls = self._get_agent_class()
        intr, term = cls._biomarker_search_terms(["ALK+"])
        assert intr == "ALK"

    def test_biomarker_search_terms_brca(self):
        """BRCA should search for PARP inhibitor."""
        cls = self._get_agent_class()
        intr, term = cls._biomarker_search_terms(["BRCA2 mutation"])
        assert intr == "PARP inhibitor"

    def test_biomarker_search_terms_msih(self):
        """MSI-H should search for checkpoint inhibitor."""
        cls = self._get_agent_class()
        intr, term = cls._biomarker_search_terms(["MSI-H"])
        assert intr == "checkpoint inhibitor"

    def test_biomarker_search_terms_kras_g12c(self):
        """KRAS G12C should use specific variant, not generic KRAS."""
        cls = self._get_agent_class()
        intr, term = cls._biomarker_search_terms(["KRAS G12C"])
        assert intr == "KRAS G12C"

    def test_biomarker_search_terms_none(self):
        """No biomarkers → no search terms."""
        cls = self._get_agent_class()
        intr, term = cls._biomarker_search_terms([])
        assert intr is None
        assert term is None

    def test_biomarker_search_terms_pdl1_only(self):
        """PD-L1 alone shouldn't trigger intervention search (it's a selection criterion)."""
        cls = self._get_agent_class()
        intr, term = cls._biomarker_search_terms(["PD-L1 80%"])
        assert intr is None
