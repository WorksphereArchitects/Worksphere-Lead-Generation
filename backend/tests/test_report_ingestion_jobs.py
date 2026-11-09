from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


supabase_module = types.ModuleType("applications.services.supabase_client")
supabase_module.supabase = MagicMock(name="supabase")
sys.modules["applications.services.supabase_client"] = supabase_module

from applications.services import report_ingestion_jobs
from applications.services.report_ingestion_jobs import (
    ReportIngestionDatabaseError,
    queue_company_report_ingestion,
)


class FakeDatabaseError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ReportIngestionJobTests(unittest.TestCase):
    def setUp(self):
        report_ingestion_jobs.supabase = MagicMock(name="supabase")

    def test_successful_job_creation_submits_background_work(self):
        query = MagicMock()
        query.insert.return_value.select.return_value.execute.return_value.data = [
            {"id": "job-1", "company_id": "company-1", "status": "processing"}
        ]
        report_ingestion_jobs.supabase.table.return_value = query

        with patch(
            "applications.services.report_ingestion_jobs._REPORT_EXECUTOR.submit"
        ) as submit:
            job = queue_company_report_ingestion({
                "id": "company-1",
                "symbol": "TEST",
            })

        self.assertEqual(job["id"], "job-1")
        submit.assert_called_once()
        query.insert.assert_called_once_with({
            "company_id": "company-1",
            "status": "processing",
        })

    def test_duplicate_active_job_is_returned(self):
        insert_query = MagicMock()
        insert_query.insert.return_value.select.return_value.execute.side_effect = (
            FakeDatabaseError("23505", "ux_report_ingestion_runs_one_processing_per_company")
        )
        existing_query = MagicMock()
        existing_query.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"id": "existing-job", "status": "processing"}
        ]
        report_ingestion_jobs.supabase.table.side_effect = [insert_query, existing_query]

        job = queue_company_report_ingestion({"id": "company-1", "symbol": "TEST"})

        self.assertEqual(job["id"], "existing-job")

    def test_schema_cache_error_is_not_misreported_as_a_conflict(self):
        query = MagicMock()
        query.insert.return_value.select.return_value.execute.side_effect = (
            FakeDatabaseError("PGRST205", "Could not find the table in the schema cache")
        )
        report_ingestion_jobs.supabase.table.return_value = query

        with self.assertRaises(ReportIngestionDatabaseError):
            queue_company_report_ingestion({"id": "company-1", "symbol": "TEST"})


if __name__ == "__main__":
    unittest.main()
