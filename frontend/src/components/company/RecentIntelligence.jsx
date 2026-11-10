import { useEffect, useRef } from "react";
import {
  Newspaper,
  ExternalLink,
  CalendarDays,
  ArrowUpRight,
  Globe2,
  RefreshCw,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function formatDate(value) {
  if (!value) return null;

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function getCategory(item) {
  return (
    item.category ||
    item.type ||
    item.event_type ||
    item.events?.[0]?.category ||
    "Business update"
  );
}

function isNewsProcessing(state) {
  return state === "loading" || state === "processing";
}

export default function RecentIntelligence({
  company,
  actionLoading = false,
  newsLoading = false,
  actionError = null,
  onFetchNews,
}) {
  const news = Array.isArray(company?.recentIntelligence)
    ? company.recentIntelligence
    : [];

  const newsState = company?.newsState || "not_fetched";

  // Keep loading active while either the initial request or
  // the background ingestion process is running.
  const isFetching =
    actionLoading ||
    newsLoading ||
    isNewsProcessing(newsState);

  const hasNewsError = actionError || company?.newsError;

  const ingestionFailed = newsState === "failed";

  const completedWithoutNews =
    newsState === "completed_empty" ||
    newsState === "not_fetched";

  const completedWithErrors =
    newsState === "completed_with_errors";

  const showFailureState =
    news.length === 0 &&
    !isFetching &&
    Boolean(hasNewsError || ingestionFailed);

  const showEmptyState =
    news.length === 0 &&
    !isFetching &&
    !hasNewsError &&
    !ingestionFailed &&
    !completedWithErrors;

  // Log the underlying failure details once per distinct failure so they
  // are available in DevTools without flooding the console on re-renders.
  const loggedFailureRef = useRef("");

  useEffect(() => {
    if (!hasNewsError && !ingestionFailed) {
      loggedFailureRef.current = "";
      return;
    }

    const latestRun = company?.newsLatestRun || company?.latestRun || null;
    const errorDetails =
      hasNewsError ||
      latestRun?.error ||
      latestRun?.error_message ||
      latestRun?.failure_reason ||
      latestRun?.message ||
      "The API reported state='failed' but did not provide an error message.";

    const failureKey = JSON.stringify({
      companyId: company?.id,
      newsState,
      errorDetails,
      latestRun,
    });

    if (loggedFailureRef.current === failureKey) return;
    loggedFailureRef.current = failureKey;

    console.groupCollapsed(
      `[News ingestion] Failed for company ${company?.id || "unknown"}`
    );
    console.error("News ingestion error:", errorDetails);
    console.error("News state:", newsState);
    console.error("Latest ingestion run:", latestRun);
    console.error("Company news error field:", company?.newsError);
    console.error("Fetch action error:", actionError);
    console.groupEnd();
  }, [
    actionError,
    company,
    company?.id,
    company?.newsError,
    company?.newsLatestRun,
    company?.latestRun,
    hasNewsError,
    ingestionFailed,
    newsState,
  ]);

  const handleFetchNews = () => {
    if (!isFetching && onFetchNews) {
      onFetchNews(company);
    }
  };

  return (
    <div>
      {/* Section heading */}
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="rounded-lg border bg-muted/50 p-2">
              <Newspaper className="h-4 w-4" />
            </div>

            <h3 className="text-base font-semibold tracking-tight">
              Recent News Intelligence
            </h3>

            <Badge variant="secondary">
              {news.length}
            </Badge>

            {isFetching && (
              <span
                className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground"
                role="status"
                aria-live="polite"
              >
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                {newsState === "processing"
                  ? "Processing"
                  : "Loading"}
              </span>
            )}
          </div>

          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Recent company announcements, business developments, and
            externally reported events.
          </p>
        </div>

        {onFetchNews && (
          <Button
            variant="outline"
            size="sm"
            disabled={isFetching}
            onClick={handleFetchNews}
            className="shrink-0 gap-2"
          >
            <RefreshCw
              className={`h-4 w-4 ${
                isFetching ? "animate-spin" : ""
              }`}
            />

            {isFetching ? "Fetching news…" : "Refresh news"}
          </Button>
        )}
      </div>

      {/* Single failure state: do not also render the empty state. */}
      {showFailureState && (
        <div
          role="alert"
          className="mt-5 rounded-2xl border border-destructive/30 bg-destructive/5 p-6 text-center"
        >
          <h4 className="text-sm font-semibold text-destructive">
            News ingestion failed
          </h4>

          <p className="mt-2 text-sm text-muted-foreground">
            {typeof hasNewsError === "string"
              ? hasNewsError
              : "We couldn't retrieve news for this company. Check the browser console for debugging details."}
          </p>

          {onFetchNews && (
            <Button
              className="mt-5 gap-2"
              variant="outline"
              onClick={handleFetchNews}
            >
              <RefreshCw className="h-4 w-4" />
              Retry fetching news
            </Button>
          )}
        </div>
      )}

      {/* Background ingestion progress */}
      {isFetching && news.length > 0 && (
        <div
          role="status"
          aria-live="polite"
          className="mt-5 flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/[0.03] px-4 py-3 text-sm text-muted-foreground"
        >
          <RefreshCw className="h-4 w-4 shrink-0 animate-spin text-primary" />

          <span>
            {newsState === "processing"
              ? "News is being analyzed. Your existing articles will remain available and new articles will appear when processing finishes."
              : "Loading saved news intelligence…"}
          </span>
        </div>
      )}

      {/* Initial loading / background processing with no articles */}
      {news.length === 0 && isFetching && (
        <>
          <div className="mt-5 flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/[0.03] px-4 py-3 text-sm text-muted-foreground">
            <RefreshCw className="h-4 w-4 shrink-0 animate-spin text-primary" />

            <span>
              {newsState === "processing"
                ? "Fetching and analyzing recent company news. This may take a little while…"
                : "Loading recent company news…"}
            </span>
          </div>

          <NewsLoadingState />
        </>
      )}

      {/* Empty state - only after loading has stopped */}
      {showEmptyState && (
        <div className="mt-5 flex flex-col items-center justify-center rounded-2xl border border-dashed bg-muted/20 px-6 py-12 text-center">
          <div className="rounded-2xl border bg-background p-4 shadow-sm">
            <Newspaper className="h-7 w-7 text-muted-foreground" />
          </div>

          <h4 className="mt-4 text-sm font-semibold">
            No recent news available
          </h4>

          <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
            {completedWithoutNews
              ? "No news articles have been fetched for this company yet."
              : "Recent news articles will appear here when the news ingestion pipeline returns results."}
          </p>

          {onFetchNews && (
            <Button
              className="mt-5 gap-2"
              variant="outline"
              onClick={handleFetchNews}
              disabled={isFetching}
            >
              <RefreshCw className="h-4 w-4" />
              Fetch news
            </Button>
          )}
        </div>
      )}


      {/* Completed with errors */}
      {completedWithErrors && news.length === 0 && !hasNewsError && (
        <div className="mt-5 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-muted-foreground">
          News ingestion finished, but some sources could not be processed.
          No articles were available to display.
        </div>
      )}

      {/* Responsive article grid */}
      {news.length > 0 && (
        <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {news.map((item, index) => {
            const title =
              item.title ||
              item.headline ||
              "Untitled news article";

            const source =
              item.source ||
              item.publisher ||
              item.domain ||
              null;

            const date = formatDate(
              item.date ||
              item.published_at ||
              item.publishedAt
            );

            const category = getCategory(item);

            const summary =
              item.summary ||
              item.rss_description ||
              null;

            const url =
              item.url ||
              item.source_url ||
              item.link ||
              null;

            return (
              <article
                key={item.id || `${title}-${index}`}
                className="
                  group flex min-w-0 flex-col
                  overflow-hidden rounded-2xl border
                  bg-background shadow-sm
                  transition-all duration-200
                  hover:-translate-y-0.5 hover:shadow-lg
                "
              >
                {/* Article accent */}
                <div className="h-1 w-full bg-primary/60" />

                <div className="flex flex-1 flex-col p-5 sm:p-6">
                  {/* Category and source */}
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Badge
                      variant="secondary"
                      className="max-w-full"
                    >
                      {category}
                    </Badge>

                    {source && (
                      <span className="inline-flex max-w-full items-center gap-1.5 text-xs text-muted-foreground">
                        <Globe2 className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate">{source}</span>
                      </span>
                    )}
                  </div>

                  {/* Headline */}
                  <h4 className="mt-4 text-base font-semibold leading-6 tracking-tight sm:text-lg">
                    {title}
                  </h4>

                  {/* Date */}
                  {date && (
                    <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                      <CalendarDays className="h-3.5 w-3.5" />

                      <time dateTime={item.published_at || item.date || undefined}>
                        {date}
                      </time>
                    </div>
                  )}

                  {/* Summary */}
                  {summary && (
                    <p className="mt-4 line-clamp-5 text-sm leading-6 text-muted-foreground">
                      {summary}
                    </p>
                  )}

                  {/* Optional intelligence details */}
                  {item.why_it_matters && (
                    <div className="mt-4 rounded-xl border bg-muted/30 p-3.5">
                      <p className="text-xs font-semibold">
                        Why it matters
                      </p>

                      <p className="mt-1.5 text-sm leading-5 text-muted-foreground">
                        {item.why_it_matters}
                      </p>
                    </div>
                  )}

                  {/* Footer action */}
                  <div className="mt-auto border-t pt-4">
                    {url ? (
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="
                          inline-flex items-center gap-2
                          text-sm font-medium text-primary
                          transition-colors hover:underline
                        "
                      >
                        Read full article

                        <ArrowUpRight className="h-4 w-4 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                      </a>
                    ) : (
                      <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                        Source URL unavailable

                        <ExternalLink className="h-4 w-4" />
                      </span>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {/* Completed with errors but some articles were retrieved */}
      /* {completedWithErrors && news.length > 0 && (
        <div className="mt-5 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-muted-foreground">
          News ingestion finished with some source errors. The available
          articles are displayed above.
        </div> 
      )} */
    </div>
  );
}

function NewsLoadingState() {
  return (
    <div
      className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3"
      role="status"
      aria-label="Loading news"
    >
      {[0, 1, 2].map((item) => (
        <div
          key={item}
          className="rounded-2xl border bg-background p-5 shadow-sm"
        >
          <div className="flex items-center justify-between gap-4">
            <div className="h-5 w-24 animate-pulse rounded-full bg-muted" />
            <div className="h-4 w-20 animate-pulse rounded bg-muted" />
          </div>

          <div className="mt-5 h-5 w-11/12 animate-pulse rounded bg-muted" />
          <div className="mt-3 h-5 w-3/4 animate-pulse rounded bg-muted" />
          <div className="mt-6 h-3 w-full animate-pulse rounded bg-muted" />
          <div className="mt-2 h-3 w-5/6 animate-pulse rounded bg-muted" />
          <div className="mt-8 h-4 w-28 animate-pulse rounded bg-muted" />
        </div>
      ))}

      <span className="sr-only">
        Fetching recent news…
      </span>
    </div>
  );
}
