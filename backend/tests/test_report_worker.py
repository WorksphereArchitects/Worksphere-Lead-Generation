from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import report_worker


class ReportWorkerTests(unittest.TestCase):
    @patch.object(report_worker, "heartbeat_loop")
    @patch.object(report_worker, "complete_job")
    @patch.object(report_worker, "process_annual_report")
    @patch.object(report_worker, "claim_job")
    def test_duplicate_worker_execution_exits_without_processing(
        self, claim_job, process_report, complete_job, heartbeat_loop
    ):
        claim_job.return_value = None

        result = report_worker.process_job("job-1", "report-1")

        self.assertEqual(result, 0)
        process_report.assert_not_called()
        complete_job.assert_not_called()

    @patch.object(report_worker, "heartbeat_loop")
    @patch.object(report_worker, "fail_job")
    @patch.object(report_worker, "process_annual_report")
    @patch.object(report_worker, "claim_job")
    def test_processing_failure_is_recorded_as_retryable(
        self, claim_job, process_report, fail_job, heartbeat_loop
    ):
        claim_job.return_value = {"id": "job-1", "attempts": 1}
        process_report.side_effect = TimeoutError("provider timeout")

        result = report_worker.process_job("job-1", "report-1")

        self.assertEqual(result, 1)
        fail_job.assert_called_once()
        self.assertTrue(fail_job.call_args.kwargs["retryable"])


if __name__ == "__main__":
    unittest.main()
