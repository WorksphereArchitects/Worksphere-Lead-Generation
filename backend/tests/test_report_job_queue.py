from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock


supabase_module = types.ModuleType("applications.services.supabase_client")
supabase_module.supabase = MagicMock(name="supabase")
sys.modules["applications.services.supabase_client"] = supabase_module

from applications.services import report_job_queue


class ReportJobQueueTests(unittest.TestCase):
    def setUp(self):
        supabase_module.supabase.reset_mock(return_value=True, side_effect=True)

    def test_enqueue_is_delegated_to_database_rpc(self):
        response = MagicMock(data={"id": "job-1", "status": "queued"})
        supabase_module.supabase.rpc.return_value.execute.return_value = response

        job = report_job_queue.enqueue_report_job(
            {"id": "report-1", "company_id": "company-1"}
        )

        self.assertEqual(job["id"], "job-1")
        supabase_module.supabase.rpc.assert_called_once_with(
            "enqueue_report_processing_job",
            {"p_report_id": "report-1", "p_retry": False},
        )

    def test_claim_uses_job_and_report_ids(self):
        response = MagicMock(data={"id": "job-1", "status": "processing"})
        supabase_module.supabase.rpc.return_value.execute.return_value = response

        result = report_job_queue.claim_job("job-1", "report-1", "worker-1")

        self.assertEqual(result["status"], "processing")
        supabase_module.supabase.rpc.assert_called_once_with(
            "claim_report_processing_job",
            {
                "p_job_id": "job-1",
                "p_report_id": "report-1",
                "p_worker_id": "worker-1",
            },
        )

    def test_completion_and_failure_are_owner_scoped_rpcs(self):
        supabase_module.supabase.rpc.return_value.execute.side_effect = [
            MagicMock(data={"id": "job-1", "status": "completed"}),
            MagicMock(data={"id": "job-1", "status": "failed"}),
        ]

        report_job_queue.complete_job("job-1", "worker-1", "run-1")
        report_job_queue.fail_job("job-1", "worker-1", "temporary", True)

        calls = supabase_module.supabase.rpc.call_args_list
        self.assertEqual(calls[0].args[0], "complete_report_processing_job")
        self.assertEqual(calls[1].args[0], "fail_report_processing_job")
        self.assertEqual(calls[1].args[1]["p_retryable"], True)


if __name__ == "__main__":
    unittest.main()
