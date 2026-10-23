
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
    item.type ||
    item.category ||
    item.event_type ||
    "Business update"
  );
}

export default function RecentIntelligence({
  company,
  actionLoading = false,
  actionError = null,
  onFetchNews,
}) {
  const news = company.recentIntelligence || [];

  return (
    <div className="">
      {/* Section heading */}
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <div className="rounded-lg border bg-muted/50 p-2">
              <Newspaper className="h-4 w-4" />
            </div>

            <h3 className="text-base font-semibold tracking-tight">
              Recent News Intelligence
            </h3>

            <Badge variant="secondary">{news.length}</Badge>
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
            disabled={actionLoading}
            onClick={() => onFetchNews(company)}
            className="shrink-0 gap-2"
          >
            <RefreshCw
              className={`h-4 w-4 ${
                actionLoading ? "animate-spin" : ""
              }`}
            />
            {actionLoading ? "Fetching news…" : "Refresh news"}
          </Button>
        )}
      </div>

      {actionError && (
        <div
          role="alert"
          className="mt-4 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
        >
          {actionError}
        </div>
      )}

      {/* Empty state */}
      {news.length === 0 ? (
        <div className="mt-5 flex flex-col items-center justify-center rounded-2xl border border-dashed bg-muted/20 px-6 py-12 text-center">
          <div className="rounded-2xl border bg-background p-4 shadow-sm">
            <Newspaper className="h-7 w-7 text-muted-foreground" />
          </div>

          <h4 className="mt-4 text-sm font-semibold">
            No recent news available
          </h4>

          <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
            Recent news articles will appear here when the news
            ingestion pipeline returns results for this company.
          </p>

          {onFetchNews && (
            <Button
              className="mt-5 gap-2"
              variant="outline"
              disabled={actionLoading}
              onClick={() => onFetchNews(company)}
            >
              <RefreshCw
                className={`h-4 w-4 ${
                  actionLoading ? "animate-spin" : ""
                }`}
              />
              {actionLoading ? "Fetching news…" : "Fetch news"}
            </Button>
          )}
        </div>
      ) : (
        /* Responsive article grid */
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

            const url = item.source_url || item.url || item.link || null;

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
                <div className="h-1 w-full" />

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
                      <time>{date}</time>
                    </div>
                  )}

                  {/* Summary */}
                  {item.summary && (
                    <p className="mt-4 line-clamp-5 text-sm leading-6 text-muted-foreground">
                      {item.summary}
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
    </div>
  );
}
