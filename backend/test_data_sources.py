"""Tests for MVP data source integrations: RxNorm, CIViC, NCI search."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# RxNorm tests
# ---------------------------------------------------------------------------


class TestRxNormShortcuts:
    """Test the pre-seeded oncology drug name shortcuts (no API calls)."""

    def test_brand_to_generic(self):
        from rxnorm_client import drug_names_match

        assert drug_names_match("Keytruda", "pembrolizumab")
        assert drug_names_match("Opdivo", "nivolumab")
        assert drug_names_match("Tagrisso", "osimertinib")

    def test_investigational_code_to_generic(self):
        from rxnorm_client import drug_names_match

        assert drug_names_match("MK-3475", "pembrolizumab")
        assert drug_names_match("AZD9291", "osimertinib")
        assert drug_names_match("DS-8201", "trastuzumab deruxtecan")

    def test_same_name_matches(self):
        from rxnorm_client import drug_names_match

        assert drug_names_match("pembrolizumab", "pembrolizumab")
        assert drug_names_match("Keytruda", "Keytruda")

    def test_case_insensitive(self):
        from rxnorm_client import drug_names_match

        assert drug_names_match("keytruda", "PEMBROLIZUMAB")
        assert drug_names_match("OPDIVO", "nivolumab")

    def test_different_drugs_dont_match(self):
        from rxnorm_client import drug_names_match

        assert not drug_names_match("Keytruda", "nivolumab")
        assert not drug_names_match("pembrolizumab", "Opdivo")
        assert not drug_names_match("carboplatin", "cisplatin")

    def test_unknown_drug_no_match(self):
        from rxnorm_client import drug_names_match

        assert not drug_names_match("SomeRandomDrug", "pembrolizumab")

    def test_chemo_mappings(self):
        from rxnorm_client import drug_names_match

        assert drug_names_match("Taxol", "paclitaxel")
        assert drug_names_match("5-FU", "fluorouracil")
        assert drug_names_match("5fu", "fluorouracil")
        assert drug_names_match("VP-16", "etoposide")
        assert drug_names_match("Xeloda", "capecitabine")

    def test_targeted_therapy_mappings(self):
        from rxnorm_client import drug_names_match

        assert drug_names_match("Herceptin", "trastuzumab")
        assert drug_names_match("Lynparza", "olaparib")
        assert drug_names_match("Lumakras", "sotorasib")
        assert drug_names_match("Enhertu", "trastuzumab deruxtecan")
        assert drug_names_match("T-DXd", "trastuzumab deruxtecan")


class TestRxNormNormalize:
    """Test normalize_drug with local shortcuts (no API calls)."""

    @pytest.mark.asyncio
    async def test_normalize_from_shortcut(self):
        from rxnorm_client import normalize_drug

        result = await normalize_drug("Keytruda")
        assert result is not None
        assert result.canonical == "pembrolizumab"
        assert "mk-3475" in [s.lower() for s in result.synonyms] or "MK-3475" in result.synonyms

    @pytest.mark.asyncio
    async def test_normalize_canonical_name(self):
        from rxnorm_client import normalize_drug

        result = await normalize_drug("pembrolizumab")
        assert result is not None
        assert result.canonical == "pembrolizumab"

    @pytest.mark.asyncio
    async def test_normalize_empty(self):
        from rxnorm_client import normalize_drug

        result = await normalize_drug("")
        assert result is None

        result = await normalize_drug("   ")
        assert result is None

    @pytest.mark.asyncio
    async def test_normalize_list(self):
        from rxnorm_client import normalize_drug_list

        results = await normalize_drug_list(["Keytruda", "Taxol", "Opdivo"])
        assert len(results) == 3
        assert results["Keytruda"].canonical == "pembrolizumab"
        assert results["Taxol"].canonical == "paclitaxel"
        assert results["Opdivo"].canonical == "nivolumab"

    @pytest.mark.asyncio
    async def test_normalized_drug_matches(self):
        from rxnorm_client import normalize_drug

        drug = await normalize_drug("Keytruda")
        assert drug is not None
        assert drug.matches("pembrolizumab")
        assert drug.matches("MK-3475")

    @pytest.mark.asyncio
    async def test_normalize_caching(self):
        from rxnorm_client import _norm_cache, normalize_drug

        # Clear cache
        _norm_cache.clear()

        result1 = await normalize_drug("Keytruda")
        assert "keytruda" in _norm_cache

        result2 = await normalize_drug("Keytruda")
        assert result1.canonical == result2.canonical


class TestRxNormAPI:
    """Test RxNorm API fallback with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_api_fallback_on_unknown_drug(self):
        from rxnorm_client import _norm_cache, normalize_drug

        _norm_cache.clear()

        mock_response_approx = MagicMock()
        mock_response_approx.status_code = 200
        mock_response_approx.raise_for_status = MagicMock()
        mock_response_approx.json.return_value = {
            "approximateGroup": {"candidate": [{"rxcui": "12345", "name": "testdrug"}]}
        }

        mock_response_props = MagicMock()
        mock_response_props.status_code = 200
        mock_response_props.raise_for_status = MagicMock()
        mock_response_props.json.return_value = {"properties": {"name": "testdrug", "rxcui": "12345"}}

        mock_response_related = MagicMock()
        mock_response_related.status_code = 200
        mock_response_related.raise_for_status = MagicMock()
        mock_response_related.json.return_value = {"relatedGroup": {"conceptGroup": []}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_response_approx, mock_response_props, mock_response_related])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("rxnorm_client.httpx.AsyncClient", return_value=mock_client):
            result = await normalize_drug("testdrug_xyz")

        assert result is not None
        assert result.canonical == "testdrug"
        assert result.rxcui == "12345"


# ---------------------------------------------------------------------------
# CIViC tests
# ---------------------------------------------------------------------------


class TestCIViCBiomarkerParsing:
    """Test biomarker string → gene name parsing."""

    def test_basic_gene_parsing(self):
        from civic_client import _parse_biomarker_to_gene

        assert _parse_biomarker_to_gene("EGFR+") == "EGFR"
        assert _parse_biomarker_to_gene("EGFR-") == "EGFR"
        assert _parse_biomarker_to_gene("ALK positive") == "ALK"
        assert _parse_biomarker_to_gene("HER2+") == "ERBB2"
        assert _parse_biomarker_to_gene("PD-L1 80%") == "CD274"
        assert _parse_biomarker_to_gene("BRAF V600E") == "BRAF"
        assert _parse_biomarker_to_gene("KRAS G12C") == "KRAS"

    def test_fusion_variants(self):
        from civic_client import _parse_biomarker_to_gene

        assert _parse_biomarker_to_gene("ALK fusion") == "ALK"
        assert _parse_biomarker_to_gene("ROS1 rearrangement") == "ROS1"
        assert _parse_biomarker_to_gene("RET fusion") == "RET"

    def test_brca_variants(self):
        from civic_client import _parse_biomarker_to_gene

        assert _parse_biomarker_to_gene("BRCA1") == "BRCA1"
        assert _parse_biomarker_to_gene("BRCA2") == "BRCA2"

    def test_msi_tmb(self):
        from civic_client import _parse_biomarker_to_gene

        assert _parse_biomarker_to_gene("MSI-H") == "MSH2"
        assert _parse_biomarker_to_gene("TMB high") == "TMB"

    def test_unknown_biomarker(self):
        from civic_client import _parse_biomarker_to_gene

        # A random gene name should return as-is (uppercase)
        result = _parse_biomarker_to_gene("FOOBAR")
        assert result == "FOOBAR"


class TestCIViCVariantParsing:
    """Test variant extraction from biomarker strings."""

    def test_protein_change(self):
        from civic_client import _parse_variant_from_biomarker

        assert _parse_variant_from_biomarker("EGFR L858R") == "L858R"
        assert _parse_variant_from_biomarker("BRAF V600E") == "V600E"
        assert _parse_variant_from_biomarker("KRAS G12C") == "G12C"

    def test_exon_patterns(self):
        from civic_client import _parse_variant_from_biomarker

        result = _parse_variant_from_biomarker("EGFR exon 19 deletion")
        assert result is not None
        assert "exon 19" in result.lower()

    def test_fusion(self):
        from civic_client import _parse_variant_from_biomarker

        assert _parse_variant_from_biomarker("ALK fusion") == "FUSION"
        assert _parse_variant_from_biomarker("ROS1 rearrangement") == "FUSION"

    def test_amplification(self):
        from civic_client import _parse_variant_from_biomarker

        assert _parse_variant_from_biomarker("MET amplification") == "AMPLIFICATION"

    def test_no_variant(self):
        from civic_client import _parse_variant_from_biomarker

        assert _parse_variant_from_biomarker("EGFR+") is None
        assert _parse_variant_from_biomarker("PD-L1 80%") is None


class TestCIViCFormatting:
    """Test CIViC context block formatting."""

    def test_format_empty(self):
        from civic_client import format_biomarker_context

        assert format_biomarker_context([]) == ""

    def test_format_with_enrichments(self):
        from civic_client import format_biomarker_context

        enrichments = [
            {
                "biomarker": "EGFR L858R",
                "gene": "EGFR",
                "variant": "L858R",
                "is_positive": True,
                "actionable_drugs": ["osimertinib", "erlotinib"],
                "highest_evidence_level": "A",
                "evidence_summary": "EGFR L858R: Predictive (Level A) — Sensitivity for osimertinib",
            }
        ]
        result = format_biomarker_context(enrichments)
        assert "Biomarker Intelligence" in result
        assert "EGFR L858R" in result
        assert "POSITIVE" in result
        assert "osimertinib" in result
        assert "Level A" in result

    def test_format_negative_biomarker(self):
        from civic_client import format_biomarker_context

        enrichments = [
            {
                "biomarker": "ALK-",
                "gene": "ALK",
                "variant": None,
                "is_positive": False,
                "actionable_drugs": [],
                "highest_evidence_level": None,
                "evidence_summary": "",
            }
        ]
        result = format_biomarker_context(enrichments)
        assert "NEGATIVE" in result


class TestCIViCAPI:
    """Test CIViC API calls with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_lookup_gene_mocked(self):
        from civic_client import _civic_cache, lookup_gene

        _civic_cache.clear()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "gene": {
                    "name": "EGFR",
                    "variants": {
                        "nodes": [
                            {
                                "name": "L858R",
                                "singleVariantMolecularProfile": {
                                    "evidenceItems": {
                                        "nodes": [
                                            {
                                                "evidenceType": "PREDICTIVE",
                                                "evidenceLevel": "A",
                                                "evidenceDirection": "SUPPORTS",
                                                "significance": "SENSITIVITY",
                                                "description": "EGFR L858R confers sensitivity to TKIs",
                                                "disease": {"name": "Non-Small Cell Lung Carcinoma"},
                                                "therapies": [{"name": "Osimertinib"}],
                                            }
                                        ]
                                    },
                                },
                            }
                        ]
                    },
                }
            }
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("civic_client.httpx.AsyncClient", return_value=mock_client):
            evidence = await lookup_gene("EGFR")

        assert len(evidence) == 1
        assert evidence[0].gene == "EGFR"
        assert evidence[0].variant == "L858R"
        assert evidence[0].is_therapeutic
        assert evidence[0].is_high_evidence
        assert "Osimertinib" in evidence[0].drugs

    @pytest.mark.asyncio
    async def test_lookup_biomarkers_mocked(self):
        from civic_client import _civic_cache, lookup_biomarkers

        _civic_cache.clear()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "gene": {
                    "name": "EGFR",
                    "variants": {
                        "nodes": [
                            {
                                "name": "L858R",
                                "singleVariantMolecularProfile": {
                                    "evidenceItems": {
                                        "nodes": [
                                            {
                                                "evidenceType": "PREDICTIVE",
                                                "evidenceLevel": "A",
                                                "evidenceDirection": "SUPPORTS",
                                                "significance": "SENSITIVITY",
                                                "description": "Sensitive to TKIs",
                                                "disease": {"name": "Non-Small Cell Lung Cancer"},
                                                "therapies": [{"name": "Osimertinib"}],
                                            }
                                        ]
                                    },
                                },
                            }
                        ]
                    },
                }
            }
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("civic_client.httpx.AsyncClient", return_value=mock_client):
            results = await lookup_biomarkers(["EGFR L858R", "PD-L1 80%"], cancer_type="NSCLC")

        # At least EGFR should resolve (PD-L1 goes to CD274 gene)
        egfr_result = next((r for r in results if r["gene"] == "EGFR"), None)
        assert egfr_result is not None
        assert egfr_result["is_positive"] is True
        assert "Osimertinib" in egfr_result["actionable_drugs"]


# ---------------------------------------------------------------------------
# NCI search tests
# ---------------------------------------------------------------------------


class TestNCISearch:
    """Test NCI-filtered trial search."""

    @pytest.mark.asyncio
    async def test_search_nci_trials_mocked(self):
        from trials_client import _search_cache, search_nci_trials

        _search_cache.clear()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT12345678",
                            "briefTitle": "NCI NSCLC Trial",
                        },
                        "statusModule": {
                            "overallStatus": "RECRUITING",
                            "phases": ["PHASE2"],
                        },
                        "eligibilityModule": {
                            "eligibilityCriteria": "Must have NSCLC",
                            "sex": "ALL",
                            "minimumAge": "18 Years",
                            "maximumAge": "99 Years",
                        },
                        "conditionsModule": {"conditions": ["NSCLC"]},
                        "descriptionModule": {"briefSummary": "An NCI study"},
                        "contactsLocationsModule": {"locations": []},
                        "armsInterventionsModule": {"interventions": [{"name": "Pembrolizumab", "type": "DRUG"}]},
                    }
                }
            ]
        }

        with patch("trials_client._http_get_with_retry", AsyncMock(return_value=mock_response)):
            results = await search_nci_trials("NSCLC", age=55, sex="male")

        assert len(results) == 1
        assert results[0]["nct_id"] == "NCT12345678"

    def test_merge_and_deduplicate(self):
        from trials_client import merge_and_deduplicate

        list1 = [
            {"nct_id": "NCT001", "brief_title": "Trial A from CT.gov"},
            {"nct_id": "NCT002", "brief_title": "Trial B from CT.gov"},
        ]
        list2 = [
            {"nct_id": "NCT001", "brief_title": "Trial A from NCI"},  # duplicate
            {"nct_id": "NCT003", "brief_title": "Trial C from NCI"},
        ]

        merged = merge_and_deduplicate([list1, list2])
        assert len(merged) == 3

        nct_ids = {t["nct_id"] for t in merged}
        assert nct_ids == {"NCT001", "NCT002", "NCT003"}

        # First list takes priority — NCT001 should have CT.gov title
        trial_a = next(t for t in merged if t["nct_id"] == "NCT001")
        assert trial_a["brief_title"] == "Trial A from CT.gov"

    def test_merge_empty_lists(self):
        from trials_client import merge_and_deduplicate

        assert merge_and_deduplicate([]) == []
        assert merge_and_deduplicate([[], []]) == []

    def test_merge_single_list(self):
        from trials_client import merge_and_deduplicate

        trials = [{"nct_id": "NCT001", "title": "A"}]
        assert merge_and_deduplicate([trials]) == trials


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all new tools are properly registered."""

    def test_all_tools_registered(self):
        import tools.biomarker_lookup  # noqa: F401
        import tools.drug_normalization  # noqa: F401
        import tools.trial_search  # noqa: F401
        from tools import list_tools

        registered = list_tools()

        # New tools
        assert "normalize_drug" in registered
        assert "normalize_drug_list" in registered
        assert "drug_match" in registered
        assert "lookup_gene" in registered
        assert "enrich_biomarkers" in registered
        assert "search_nci_trials" in registered
        assert "search_and_merge" in registered

        # Existing tools still registered
        assert "search_trials" in registered
        assert "fetch_trial" in registered
        assert "nearest_site" in registered

    def test_tool_specs_documented(self):
        import tools.biomarker_lookup  # noqa: F401
        import tools.drug_normalization  # noqa: F401
        import tools.trial_search  # noqa: F401
        from tools import get_tool_spec

        for name in ["normalize_drug", "enrich_biomarkers", "search_nci_trials", "search_and_merge"]:
            spec = get_tool_spec(name)
            assert spec is not None, f"Missing spec for {name}"
            assert spec.description, f"Empty description for {name}"
