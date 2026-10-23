import { useEffect, useMemo, useState } from "react";

import { getCompanies } from "../api/clientApi";

import {
  Building2,
  Search,
  TrendingUp,
} from "lucide-react";

import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";

export default function NotQualifiedCompanies() {
  const [companies, setCompanies] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);


  // ============================================================
  // LOAD NOT QUALIFIED COMPANIES
  // ============================================================

  useEffect(() => {
    async function loadCompanies() {
      try {
        setLoading(true);
        setError(null);

        const data = await getCompanies();

        const notQualified = (data.companies || []).filter(
          (company) =>
            company.qualification?.qualification_status ===
            "not_qualified"
        );

        setCompanies(notQualified);
      } catch (error) {
        console.error(
          "Failed to load non-qualified companies:",
          error
        );

        setError(
          error.message ||
            "Failed to load non-qualified companies"
        );
      } finally {
        setLoading(false);
      }
    }

    loadCompanies();
  }, []);


  // ============================================================
  // SEARCH
  // ============================================================

  const filteredCompanies = useMemo(() => {
    const query = search.trim().toLowerCase();

    if (!query) {
      return companies;
    }

    return companies.filter((company) => {
      const name =
        company.name?.toLowerCase() || "";

      const symbol =
        company.symbol?.toLowerCase() || "";

      const sector =
        company.sector?.toLowerCase() || "";

      return (
        name.includes(query) ||
        symbol.includes(query) ||
        sector.includes(query)
      );
    });
  }, [companies, search]);


  // ============================================================
  // HELPERS
  // ============================================================

  const formatRevenue = (revenue) => {
    if (revenue == null || revenue === "") {
      return "—";
    }

    const value = Number(revenue);

    if (Number.isNaN(value)) {
      return "—";
    }

    return `₹${value.toLocaleString("en-IN")} Cr`;
  };


  const formatGrowth = (growth) => {
    if (growth == null || growth === "") {
      return "—";
    }

    const value = Number(growth);

    if (Number.isNaN(value)) {
      return "—";
    }

    return `${value.toFixed(2)}%`;
  };


  // ============================================================
  // LOADING
  // ============================================================

  if (loading) {
    return (
      <div className="flex min-h-[calc(100dvh-6rem)] items-center justify-center lg:min-h-screen">

        <p className="text-sm text-muted-foreground">
          Loading non-qualified companies...
        </p>

      </div>
    );
  }


  // ============================================================
  // ERROR
  // ============================================================

  if (error) {
    return (
      <div className="p-6">

        <div className="rounded-xl border bg-background p-6">

          <h2 className="text-lg font-semibold">
            Failed to load non-qualified companies
          </h2>

          <p className="mt-2 text-sm text-muted-foreground">
            {error}
          </p>

        </div>

      </div>
    );
  }


  // ============================================================
  // PAGE
  // ============================================================

  return (
  <div className="min-h-[calc(100dvh-6rem)] min-w-0 flex-1 p-4 sm:p-6 lg:h-screen lg:overflow-y-auto">
      {/* ========================================================
          HEADER
      ======================================================== */}

      <div className="mb-6">

        <h1 className="text-2xl font-semibold tracking-tight">
          Not Qualified Companies
        </h1>

        <p className="mt-1 text-sm text-muted-foreground">
          Companies that do not currently meet the WorkSphere
          qualification criteria.
        </p>

      </div>


      {/* ========================================================
          NOT QUALIFIED COMPANIES STAT CARD
      ======================================================== */}

      <div className="mb-6">

        <Card className="w-full sm:w-[280px]">

          <CardContent className="flex items-center gap-4 p-5">

            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-muted">

              <Building2 className="h-5 w-5" />

            </div>

            <div>

              <p className="text-sm text-muted-foreground">
                Not Qualified Companies
              </p>

              <p className="mt-1 text-2xl font-semibold">
                {companies.length}
              </p>

            </div>

          </CardContent>

        </Card>

      </div>


      {/* ========================================================
          SEARCH
      ======================================================== */}

      <div className="mb-6 w-full max-w-md">

        <div className="relative">

          <Search
            className="
              pointer-events-none
              absolute
              right-3
              top-1/2
              h-4
              w-4
              -translate-y-1/2
              text-muted-foreground
            "
          />

          <Input
            type="search"
            placeholder="Search by company, symbol or sector..."
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
            }}
            className="h-10 pl-3 pr-10"
          />

        </div>

      </div>


      {/* ========================================================
          TABLE
      ======================================================== */}

      <div className="overflow-hidden rounded-xl border bg-background">

        <div className="w-full overflow-x-auto">

          <table className="w-full min-w-[1100px] table-fixed text-sm">

            <colgroup>

              <col className="w-[24%]" />
              <col className="w-[10%]" />
              <col className="w-[16%]" />
              <col className="w-[14%]" />
              <col className="w-[14%]" />
              <col className="w-[10%]" />
              <col className="w-[12%]" />

            </colgroup>


            <thead className="border-b bg-muted/40">

              <tr>

                <th className="px-5 py-3 text-left font-medium text-muted-foreground">
                  Company
                </th>

                <th className="px-5 py-3 text-left font-medium text-muted-foreground">
                  Symbol
                </th>

                <th className="px-5 py-3 text-left font-medium text-muted-foreground">
                  Sector
                </th>

                <th className="px-5 py-3 text-right font-medium text-muted-foreground">
                  FY 2025–26 Revenue
                </th>

                <th className="px-5 py-3 text-right font-medium text-muted-foreground">
                  FY 2024–25 Revenue
                </th>

                <th className="px-5 py-3 text-right font-medium text-muted-foreground">
                  Growth
                </th>

                <th className="px-5 py-3 text-left font-medium text-muted-foreground">
                  Source
                </th>

              </tr>

            </thead>


            <tbody className="divide-y">

              {filteredCompanies.map((company) => {

                const qualification =
                  company.qualification || {};

                return (
                  <tr
                    key={company.id}
                    className="transition-colors hover:bg-muted/30"
                  >

                    {/* Company */}

                    <td className="px-5 py-4">

                      <div className="flex min-w-0 items-center gap-3">

                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted">

                          <Building2 className="h-4 w-4" />

                        </div>

                        <span
                          className="truncate font-medium"
                          title={company.name || ""}
                        >
                          {company.name || "—"}
                        </span>

                      </div>

                    </td>


                    {/* Symbol */}

                    <td className="px-5 py-4">

                      <span className="block truncate font-mono text-xs">
                        {company.symbol || "—"}
                      </span>

                    </td>


                    {/* Sector */}

                    <td className="px-5 py-4">

                      <span
                        className="block truncate text-muted-foreground"
                        title={company.sector || ""}
                      >
                        {company.sector || "—"}
                      </span>

                    </td>


                    {/* Current Revenue */}

                    <td className="px-5 py-4 text-right font-medium whitespace-nowrap">

                      {formatRevenue(
                        qualification.revenue
                      )}

                    </td>


                    {/* Previous Revenue */}

                    <td className="px-5 py-4 text-right text-muted-foreground whitespace-nowrap">

                      {formatRevenue(
                        qualification.previous_year_revenue
                      )}

                    </td>


                    {/* Growth */}

                    <td className="px-5 py-4 text-right whitespace-nowrap">

                      <div className="inline-flex items-center gap-1.5 font-medium">

                        <TrendingUp className="h-3.5 w-3.5 shrink-0" />

                        {formatGrowth(
                          qualification.revenue_growth
                        )}

                      </div>

                    </td>


                    {/* Source */}

                    <td className="px-5 py-4">

                      <span
                        className="block truncate text-muted-foreground"
                        title={
                          qualification.qualification_source ||
                          ""
                        }
                      >
                        {qualification.qualification_source ||
                          "—"}
                      </span>

                    </td>

                  </tr>
                );

              })}

            </tbody>

          </table>


          {/* ======================================================
              EMPTY STATE
          ====================================================== */}

          {filteredCompanies.length === 0 && (

            <div className="border-t px-6 py-12 text-center">

              <Building2 className="mx-auto h-8 w-8 text-muted-foreground" />

              <p className="mt-3 text-sm font-medium">

                {search
                  ? "No companies match your search."
                  : "No non-qualified companies found."}

              </p>

              {search && (

                <p className="mt-1 text-xs text-muted-foreground">
                  Try searching by company name, symbol or sector.
                </p>

              )}

            </div>

          )}

        </div>

      </div>


      {/* ========================================================
          SEARCH RESULT COUNT
      ======================================================== */}

      {search && filteredCompanies.length > 0 && (

        <p className="mt-3 text-xs text-muted-foreground">

          Showing {filteredCompanies.length} of{" "}
          {companies.length} non-qualified companies

        </p>

      )}

    </div>
  );
}