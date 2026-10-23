"""Offline checks for the P0 reliability contracts."""

from __future__ import annotations

import sys
import types as python_types
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4


# Import route/service modules without initializing a real Supabase client.
supabase_module = python_types.ModuleType(
    "applications.services.supabase_client"
)
supabase_module.supabase = MagicMock(name="supabase")
sys.modules["applications.services.supabase_client"] = supabase_module

from applications import create_app
from applications.routes import companies_routes
from applications.routes import company_intelligence as company_intelligence_routes
from applications.services import gemini_engine
from applications.services.public_errors import safe_error_summary


class SalesStageRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()
        supabase_module.supabase.reset_mock(return_value=True, side_effect=True)

    def test_invalid_stage_is_rejected_without_database_update(self):
        response = self.client.patch(
            f"/api/companies/{uuid4()}/sales-stage",
            json={"sales_stage": "qualified"},
        )
        self.assertEqual(response.status_code, 400)
        supabase_module.supabase.table.assert_not_called()

    def test_invalid_company_id_is_rejected(self):
        response = self.client.patch(
            "/api/companies/not-a-uuid/sales-stage",
            json={"sales_stage": "prospect"},
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_company_returns_not_found(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.maybe_single.return_value = query
        query.execute.return_value.data = None
        supabase_module.supabase.table.return_value = query

        response = self.client.patch(
            f"/api/companies/{uuid4()}/sales-stage",
            json={"sales_stage": "prospect"},
        )
        self.assertEqual(response.status_code, 404)

    def test_persisted_stage_is_returned(self):
        company_id = str(uuid4())
        existing = MagicMock()
        existing.maybe_single.return_value.execute.return_value.data = {
            "id": company_id,
        }
        update = MagicMock()
        update.update.return_value.eq.return_value.select.return_value.execute.return_value.data = [
            {"id": company_id, "sales_stage": "prospect"}
        ]
        supabase_module.supabase.table.side_effect = [existing, update]

        response = self.client.patch(
            f"/api/companies/{company_id}/sales-stage",
            json={"sales_stage": "prospect"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["company"]["sales_stage"], "prospect")


class CompanyIntelligenceLookupTests(unittest.TestCase):
    def setUp(self):
        supabase_module.supabase.reset_mock(return_value=True, side_effect=True)

    def test_uuid_lookup_handles_empty_symbol_result(self):
        company_id = str(uuid4())
        symbol_query = MagicMock()
        symbol_query.select.return_value = symbol_query
        symbol_query.eq.return_value = symbol_query
        symbol_query.maybe_single.return_value = symbol_query
        symbol_query.execute.return_value = None

        uuid_query = MagicMock()
        uuid_query.select.return_value = uuid_query
        uuid_query.eq.return_value = uuid_query
        uuid_query.maybe_single.return_value = uuid_query
        uuid_query.execute.return_value.data = {"id": company_id}

        supabase_module.supabase.table.side_effect = [symbol_query, uuid_query]

        company = company_intelligence_routes._get_company_by_identifier(company_id)

        self.assertEqual(company, {"id": company_id})


class GeminiReliabilityTests(unittest.TestCase):
    def test_context_budget_keeps_provenance_and_skips_duplicate_passages(self):
        sentences = [
            "Introductory company information.",
            "The company approved a new manufacturing facility.",
            "The project is planned for the next financial year.",
            "The same relevant event is repeated in another section.",
        ]
        packets = [
            "Source sentence index: 2\nCandidate score: 90.00",
            "Source sentence index: 2\nCandidate score: 80.00",
            "Source sentence index: 4\nCandidate score: 50.00",
        ]
        with (
            patch.object(gemini_engine, "split_into_sentences", return_value=sentences),
            patch.object(gemini_engine, "extract_evidence_context", return_value=packets),
            patch.object(gemini_engine, "MAX_CONTEXT_TOKENS_TARGET", 500),
            patch.object(gemini_engine, "MAX_INPUT_TOKENS_PER_REQUEST", 4096),
            patch.object(gemini_engine, "MAX_OUTPUT_TOKENS", 512),
            patch.object(gemini_engine, "MAX_EXCERPT_CHARS", 500),
        ):
            context, stats, registry = gemini_engine.build_retrieval_context(
                "ignored by patched sentence splitter", "Example Co"
            )

        self.assertIn("SOURCE_CANDIDATE_ID: 1", context)
        self.assertIn("Source sentence index: 2", context)
        self.assertIn(1, registry)
        self.assertLessEqual(
            stats["estimated_context_tokens"], stats["context_budget_tokens"]
        )
        self.assertEqual(stats["gemini_packets"], len(registry))

    def test_transient_network_errors_retry_but_auth_errors_do_not(self):
        self.assertTrue(
            gemini_engine._is_transient_error(
                ConnectionAbortedError(10053, "connection aborted")
            )
        )
        self.assertTrue(gemini_engine._is_transient_error(TimeoutError()))
        self.assertFalse(
            gemini_engine._is_transient_error(
                RuntimeError("401 authentication failed")
            )
        )

    def test_retry_after_header_is_honored(self):
        error = RuntimeError("temporary failure")
        error.response = MagicMock(headers={"retry-after": "12"})
        self.assertEqual(
            gemini_engine._extract_provider_retry_delay(error), 12.0
        )

    def test_public_error_summary_redacts_secrets_and_tracebacks(self):
        self.assertEqual(
            safe_error_summary("request failed api_key=private-value"),
            "request failed api_key=[redacted]",
        )
        self.assertEqual(
            safe_error_summary("Traceback (most recent call last):\nsecret"),
            "Operation failed.",
        )


if __name__ == "__main__":
    unittest.main()
