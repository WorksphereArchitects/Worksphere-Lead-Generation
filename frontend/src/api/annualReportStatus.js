const REPORT_STATES = new Set([
  "pending",
  "queued",
  "processing",
  "completed",
  "failed",
  "unavailable",
]);

function normalizeState(value) {
  if (!value) return null;

  const state = String(value).toLowerCase();
  if (["running", "in_progress", "in-progress", "started"].includes(state)) {
    return "processing";
  }
  if (["done", "success", "succeeded", "complete"].includes(state)) {
    return "completed";
  }
  if (["waiting", "created"].includes(state)) {
    return "queued";
  }
  return REPORT_STATES.has(state) ? state : null;
}

export function getAnnualReportStatus(statusData) {
  if (!statusData?.success) {
    throw new Error(statusData?.error || "Could not retrieve report status.");
  }

  const jobState = normalizeState(statusData.job?.status);
  const reportState = normalizeState(statusData.report_status);

  // A job is the most precise signal while work is queued or running. Once
  // it is absent (for example, immediately after report creation), the report
  // lifecycle still tells us that the report is waiting to be processed.
  // A report can exist before processing has been requested. Keep that state
  // separate so the UI can offer the Process report action. Once a worker job
  // exists, its status takes precedence over the report's pending lifecycle.
  const state = jobState || (
    reportState === "pending"
      ? "pending"
      : reportState || normalizeState(statusData.status) || "pending"
  );
  const error =
    statusData.error ||
    statusData.job?.last_error ||
    statusData.job?.failure_reason ||
    null;

  return {
    state,
    job: statusData.job || null,
    error,
  };
}

export function isAnnualReportActive(state) {
  return state === "queued" || state === "processing";
}
