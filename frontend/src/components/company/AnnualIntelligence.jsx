import { FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function formatObject(value) {
  if (!value || typeof value !== "object") {
    return value;
  }

  return Object.entries(value)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(
      ([key, value]) =>
        `${key.replaceAll("_", " ")}: ${value}`
    )
    .join(" • ");
}

export default function AnnualIntelligence({
  company,
  actionLoading = false,
  actionError,
  onIngest,
  onProcess,
}) {
  const report = company.annualReport;
  const evidence = company.annualEvidence || [];
  const latestRun = report?.latestRun;
  const status = latestRun?.status === "failed"
    ? "failed"
    : latestRun?.status === "running"
      ? "processing"
      : report?.processingStatus;
  const unresolvedCount = evidence.filter(
    (item) => item.source_resolution_status === "unresolved"
  ).length;

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4" />

          <h3 className="text-sm font-semibold">
            Annual Report Intelligence
          </h3>
        </div>

        {report?.year && (
          <Badge variant="outline">
            {report.year}
          </Badge>
        )}
      </div>

      {actionError && (
        <div role="alert" className="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {actionError}
        </div>
      )}

      {!report?.available ? (
        <div className="mt-3 rounded-lg border p-4">
          <p className="text-sm text-muted-foreground">
            No annual report record is available for this company.
          </p>
          {onIngest && (
            <Button className="mt-3" size="sm" onClick={() => onIngest(company)} disabled={actionLoading}>
              {actionLoading ? "Finding report…" : "Find latest NSE report"}
            </Button>
          )}
        </div>
      ) : (
        <div className="mt-3 rounded-lg border p-4">
          <p className="text-sm font-medium">
            {status === "failed"
              ? "The most recent processing attempt failed."
              : status === "processing"
                ? "Annual report processing is in progress."
                : status === "completed" && evidence.length === 0
                  ? "Processing completed; no evidence was found."
                  : status === "completed"
                    ? "Annual report processing completed."
                    : status === "pending"
                      ? "The report is available but has not been processed."
                      : "Report processing status is unavailable."}
          </p>
          {status === "failed" && latestRun?.error_message && (
            <p className="mt-2 text-sm text-destructive">{latestRun.error_message}</p>
          )}
          {unresolvedCount > 0 && status !== "failed" && (
            <p className="mt-2 text-sm text-muted-foreground">
              {unresolvedCount} evidence item{unresolvedCount === 1 ? " has" : "s have"} an unresolved source.
            </p>
          )}
          {status !== "processing" && onProcess && (
            <Button className="mt-3" size="sm" onClick={() => onProcess(company)} disabled={actionLoading}>
              {actionLoading
                ? "Processing…"
                : status === "failed"
                  ? "Retry processing"
                  : status === "completed"
                    ? "Reprocess report"
                    : "Process report"}
            </Button>
          )}
        </div>
      )}

      {report?.available && evidence.length > 0 && (
        <div className="mt-3 space-y-3">
          {evidence.map((item, index) => (
            <div
              key={item.id || `${item.headline}-${index}`}
              className="rounded-lg border p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <h4 className="text-sm font-semibold leading-5">
                  {item.headline || "Untitled evidence"}
                </h4>

                {item.event_state && (
                  <Badge variant="secondary">
                    {item.event_state}
                  </Badge>
                )}
              </div>

              {item.evidence_type && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {item.evidence_type}
                </p>
              )}

              {item.summary && (
                <p className="mt-3 text-sm leading-6">
                  {item.summary}
                </p>
              )}

              {item.why_it_matters && (
                <div className="mt-3 rounded-md bg-muted/50 p-3">
                  <p className="text-xs font-medium">
                    Why it matters
                  </p>

                  <p className="mt-1 text-sm text-muted-foreground">
                    {item.why_it_matters}
                  </p>
                </div>
              )}

              {item.investment && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-muted-foreground">
                    Investment
                  </p>

                  <p className="mt-1 text-sm">
                    {formatObject(item.investment)}
                  </p>
                </div>
              )}

              {item.physical_scale && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-muted-foreground">
                    Physical Scale
                  </p>

                  <p className="mt-1 text-sm">
                    {formatObject(item.physical_scale)}
                  </p>
                </div>
              )}

              {item.timeline && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-muted-foreground">
                    Timeline
                  </p>

                  <p className="mt-1 text-sm">
                    {item.timeline}
                  </p>
                </div>
              )}

              {item.location && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-muted-foreground">
                    Location
                  </p>

                  <p className="mt-1 text-sm">
                    {item.location}
                  </p>
                </div>
              )}

              {item.physical_consequence && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-muted-foreground">
                    Physical Consequence
                  </p>

                  <p className="mt-1 text-sm">
                    {item.physical_consequence}
                  </p>
                </div>
              )}

              {item.excerpt && (
                <div className="mt-4 border-t pt-3">
                  <p className="text-xs font-medium text-muted-foreground">
                    Source Evidence
                  </p>

                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    "{item.excerpt}"
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
