
import {
  CheckCircle2,
  Sparkles,
  Building2,
  Newspaper,
  FileText,
  X,
} from "lucide-react";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import CompanyOverview from "./CompanyOverview";
import AnnualIntelligence from "./AnnualIntelligence";
import RecentIntelligence from "./RecentIntelligence";

export default function CompanyDetails({
  company,
  open,
  onOpenChange,
  isProspect,
  onQualify,
  onRemove,
  loading = false,
  error = null,
  reportActionError,
  reportActionLoading = false,
  onIngestReport,
  onProcessReport,
  newsActionLoading = false,
  newsActionError,
  onFetchNews,
}) {
  if (!company) return null;

  const annualEvidence = company.annualEvidence || [];
  const recentNews = company.recentIntelligence || [];

  const resolvedCount =
    company.backendData?.summary?.resolved_evidence_count ?? 0;

  const unresolvedCount =
    company.backendData?.summary?.unresolved_evidence_count ?? 0;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent
        className="
    !fixed !left-2 !top-2 !translate-x-0 !translate-y-0
    !w-[calc(100vw-1rem)] !max-w-none
    !h-[calc(100dvh-1rem)] !max-h-none
    flex flex-col gap-0 overflow-hidden
    rounded-2xl border bg-background p-0 shadow-2xl
    sm:!max-w-none
  "
      >
        {/* Header */}
        <AlertDialogHeader className="shrink-0 border-b bg-background px-5 py-4 sm:px-8 sm:py-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="gap-1">
                  <Building2 className="h-3 w-3" />
                  Company Intelligence
                </Badge>

                <Badge variant="secondary">
                  {isProspect ? "Prospect" : "Suspect"}
                </Badge>
              </div>

              <AlertDialogTitle className="text-xl font-semibold tracking-tight sm:text-2xl">
                {company.company}
              </AlertDialogTitle>

              <AlertDialogDescription className="mt-1 text-sm">
                {company.industry || "Industry not available"}
                {company.symbol && ` · ${company.symbol}`}
              </AlertDialogDescription>
            </div>

            <AlertDialogCancel
              aria-label="Close company details"
              className="
                mt-0 h-9 w-9 shrink-0 rounded-full
                border-0 p-0 shadow-none
                hover:bg-muted
              "
            >
              <X className="h-4 w-4" />
              <span className="sr-only">Close</span>
            </AlertDialogCancel>
          </div>
        </AlertDialogHeader>

        {/* Independent scrolling content */}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-muted/20">
          <div className="mx-auto w-full max-w-[1800px] space-y-7 px-4 py-5 sm:px-6 sm:py-7 lg:px-8">
            {loading && (
              <div
                role="status"
                className="flex items-center gap-3 rounded-xl border bg-background p-5 text-sm text-muted-foreground"
              >
                <Sparkles className="h-5 w-5 animate-pulse" />
                Loading company intelligence…
              </div>
            )}

            {!loading && error && (
              <div
                role="alert"
                className="rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive"
              >
                <p className="font-semibold">
                  Company details could not be loaded
                </p>
                <p className="mt-1">{error}</p>
              </div>
            )}

            {!loading && !error && (
              <>
                {/* Summary cards */}
                <section>
                  <div className="mb-4">
                    <h2 className="text-base font-semibold tracking-tight">
                      Intelligence at a glance
                    </h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                      A consolidated view of company signals and available sources.
                    </p>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                    <SummaryCard
                      icon={Sparkles}
                      label="Annual report signals"
                      value={annualEvidence.length}
                      description="Extracted business events"
                    />

                    <SummaryCard
                      icon={CheckCircle2}
                      label="Resolved sources"
                      value={resolvedCount}
                      description="Evidence linked to source text"
                    />

                    <SummaryCard
                      icon={FileText}
                      label="Unresolved sources"
                      value={unresolvedCount}
                      description="Evidence requiring source resolution"
                    />

                    <SummaryCard
                      icon={Newspaper}
                      label="Recent news"
                      value={recentNews.length}
                      description="Available news intelligence articles"
                    />
                  </div>
                </section>

                {/* Company overview */}
                <section className="rounded-2xl border bg-background p-4 shadow-sm sm:p-6">
                  <CompanyOverview company={company} />
                </section>

                {/* Annual intelligence */}
                <section className="rounded-2xl border bg-background p-4 shadow-sm sm:p-6">
                  <AnnualIntelligence
                    company={company}
                    actionLoading={reportActionLoading}
                    actionError={reportActionError}
                    onIngest={onIngestReport}
                    onProcess={onProcessReport}
                  />
                </section>

                {/* Recent news */}
                <section className="rounded-2xl border bg-background p-4 shadow-lg sm:p-6">
                  <RecentIntelligence
                    company={company}
                    actionLoading={newsActionLoading}
                    actionError={newsActionError}
                    onFetchNews={onFetchNews}
                  />
                </section>
              </>
            )}
          </div>
        </div>

        {/* Fixed footer */}
        <AlertDialogFooter className="shrink-0 flex-col gap-3 border-t bg-background px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-8 sm:py-4">
          <p className="hidden text-xs text-muted-foreground lg:block">
            Company intelligence · {company.symbol || "Symbol unavailable"}
          </p>

          <div className="flex w-full flex-col-reverse gap-2 sm:w-auto sm:flex-row">
            <AlertDialogCancel className="mt-0 w-full sm:w-auto">
              Close
            </AlertDialogCancel>

            {isProspect ? (
              <Button
                variant="outline"
                className="w-full sm:w-auto"
                onClick={() => onRemove(company)}
              >
                Remove from Prospects
              </Button>
            ) : (
              <Button
                className="w-full sm:w-auto"
                onClick={() => onQualify(company)}
              >
                Qualify as Prospect
              </Button>
            )}
          </div>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  description,
}) {
  return (
    <div className="group rounded-xl border bg-background p-4 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{label}</p>

          <p className="mt-3 text-3xl font-semibold tracking-tight tabular-nums">
            {value}
          </p>
        </div>

        <div className="rounded-xl border bg-muted/50 p-2.5">
          <Icon className="h-5 w-5 text-muted-foreground" />
        </div>
      </div>

      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        {description}
      </p>
    </div>
  );
}
