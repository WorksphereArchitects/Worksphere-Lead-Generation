import {
  Building2,
  MapPin,
  IndianRupee,
  TrendingUp,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";

export default function CompanyOverview({ company }) {
  const evidence = company.annualEvidence || [];
  const signal = evidence[0];

  const formatRevenue = (revenue) => {
    if (revenue == null || revenue === "") {
      return "Not available";
    }

    const value = Number(revenue);

    if (Number.isNaN(value)) {
      return "Not available";
    }

    return `₹${value.toLocaleString("en-IN")} Cr`;
  };

  const formatGrowth = (growth) => {
    if (growth == null || growth === "") {
      return "Not available";
    }

    const value = Number(growth);

    if (Number.isNaN(value)) {
      return "Not available";
    }

    return `${value.toFixed(2)}%`;
  };

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold">
          Company Overview
        </h3>

        <div className="mt-3 grid gap-3 sm:grid-cols-2">

          {/* Industry */}
          <div className="rounded-lg border p-3">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Building2 className="h-4 w-4" />
              <span className="text-xs">
                Industry
              </span>
            </div>

            <p className="mt-2 text-sm font-medium">
              {company.industry ||
                "Not available"}
            </p>
          </div>

          {/* Company */}
          <div className="rounded-lg border p-3">
            <div className="flex items-center gap-2 text-muted-foreground">
              <MapPin className="h-4 w-4" />
              <span className="text-xs">
                Company
              </span>
            </div>

            <p className="mt-2 text-sm font-medium">
              {company.company ||
                "Not available"}
            </p>
          </div>

          {/* Current Revenue */}
          <div className="rounded-lg border p-3">
            <div className="flex items-center gap-2 text-muted-foreground">
              <IndianRupee className="h-4 w-4" />
              <span className="text-xs">
                Current Revenue
              </span>
            </div>

            <p className="mt-2 text-sm font-medium">
              {formatRevenue(
                company.revenue
              )}
            </p>

            {company.revenueYear && (
              <p className="mt-1 text-xs text-muted-foreground">
                {company.revenueYear}
              </p>
            )}
          </div>

          {/* Revenue Growth */}
          <div className="rounded-lg border p-3">
            <div className="flex items-center gap-2 text-muted-foreground">
              <TrendingUp className="h-4 w-4" />
              <span className="text-xs">
                Revenue Growth
              </span>
            </div>

            <p className="mt-2 text-sm font-medium">
              {formatGrowth(
                company.revenueGrowth
              )}
            </p>
          </div>

        </div>
      </div>

      {/* Latest evidence-backed report item */}
      <div>
        <h3 className="text-sm font-semibold">
          Latest Annual Report Evidence
        </h3>

        {signal ? (
          <div className="mt-3 rounded-lg bg-muted/50 p-4">

            <div className="flex flex-wrap gap-2">
              {signal.eventState && (
                <Badge variant="secondary">
                  {signal.eventState}
                </Badge>
              )}

              {signal.type && (
                <Badge variant="outline">
                  {signal.type}
                </Badge>
              )}
            </div>

            <h4 className="mt-3 text-sm font-semibold">
              {signal.title}
            </h4>

            {signal.summary && (
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {signal.summary}
              </p>
            )}

            {signal.whyItMatters && (
              <div className="mt-3">
                <p className="text-xs font-medium text-muted-foreground">
                  Why it matters
                </p>

                <p className="mt-1 text-sm">
                  {signal.whyItMatters}
                </p>
              </div>
            )}

          </div>
        ) : (
          <div className="mt-3 rounded-lg border p-4">
            <p className="text-sm text-muted-foreground">
              No annual-report evidence is available for this report yet.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
