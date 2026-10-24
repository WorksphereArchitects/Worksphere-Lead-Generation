import { useEffect, useMemo, useRef, useState } from "react";

import DashboardHeader from "../components/layout/DashboardHeader";
import StatCards from "../components/dashboard/StatCards";
import LeadTable from "../components/dashboard/LeadTable";
import CompanyDetails from "../components/company/CompanyDetails";

import {
  getCompanies,
  getCompanyIntelligence,
  getCompanyNews,
  getReportProcessingStatus,
  ingestCompanyAnnualReport,
  ingestCompanyNews,
  processAnnualReport,
  updateCompanySalesStage,
} from "../api/clientApi";

/*
 * Convert a company from the companies API into the
 * structure currently required by LeadTable.
 *
 * Qualification comes from the backend.
 */
function mapCompanyToLead(company) {
  return {
    id: company.id,
    symbol: company.symbol,
    company: company.name,
    industry: company.sector || "—",
    sales_stage: company.sales_stage || "suspect",
    qualification:
      company.qualification || null,
  };
}

/*
 * Convert the detailed company intelligence response.
 */
function mapCompanyIntelligence(data, newsData) {
  const company = data.company || {};
  const evidence = data.evidence || [];
  const reports = data.reports || [];
  const qualification = data.qualification || {};
  const processingRuns = data.processing_runs || [];

  const latestReport = reports[0] || null;
  const latestRun = latestReport
    ? processingRuns.find((run) => run.annual_report_id === latestReport.id) || null
    : null;
  const reportEvidence = latestReport
    ? evidence.filter((item) => item.source_id === latestReport.id)
    : [];

  return {
    /*
     * Company information
     */
    id: company.id,
    symbol: company.symbol,
    company: company.name,
    industry: company.sector || "—",
    sales_stage: company.sales_stage || "suspect",
    /*
     * Financial information
     *
     * Same source used by QualifiedCompanies.
     */
    revenue: qualification.revenue ?? null,
    previousRevenue:
      qualification.previous_year_revenue ?? null,
    revenueGrowth:
      qualification.revenue_growth ?? null,

    /*
     * Financial year for current revenue.
     *
     * QualifiedCompanies currently displays
     * FY 2025–26 / FY 2024–25 based on the
     * backend financial data.
     */
    revenueYear: qualification.financial_year || null,

    /*
     * Backend financial qualification
     */
    qualification:
      data.qualification || null,

    /*
     * Annual report
     */
    annualReport: latestReport
      ? {
        available: true,
          id: latestReport.id,
        year: latestReport.financial_year,
        title: latestReport.report_title,
        pageCount: latestReport.page_count,
        processingStatus:
          latestReport.processing_status,
        nseUrl: latestReport.nse_url,
          latestRun,
      }
      : {
        available: false,
      },

    /*
     * REAL annual-report evidence.
     */
    annualEvidence: reportEvidence,

    /* Persisted articles from the company news API. */
    recentIntelligence: newsData?.articles || [],
    newsState: newsData?.state || "loading",
    newsLatestRun: newsData?.latest_run || null,
    processingRuns,

    /*
     * Keep complete backend response
     * available to detail components.
     */
    backendData: data,
  };
}

export default function Dashboard() {
  /*
   * Real backend companies
   */
  const [companies, setCompanies] =
    useState([]);

  const [loadingCompanies, setLoadingCompanies] =
    useState(true);

  const [companyError, setCompanyError] =
    useState(null);
  const [companyReloadToken, setCompanyReloadToken] = useState(0);

  const [salesStageError, setSalesStageError] = useState(null);

  /*
   * Suspects / Prospects
   *
   * All backend-qualified companies start
   * as Suspects.
   *
   * Prospects start empty and are populated
   * only when the sales team manually qualifies
   * a Suspect.
   */
  const [suspects, setSuspects] =
    useState([]);

  const [prospects, setProspects] =
    useState([]);

  /*
   * Dashboard tab state
   *
   * This is still the existing
   * Suspects / Prospects tab.
   */
  const [activeTab, setActiveTab] =
    useState("suspects");

  const [search, setSearch] =
    useState("");

  /*
   * Selected company
   */
  const [selectedCompany, setSelectedCompany] =
    useState(null);

  const [detailsOpen, setDetailsOpen] =
    useState(false);

  /*
   * Detailed intelligence loading state
   */
  const [loadingCompanyDetails, setLoadingCompanyDetails] =
    useState(false);

  const [companyDetailsError, setCompanyDetailsError] =
    useState(null);

  const [reportActionError, setReportActionError] = useState(null);
  const [reportActionLoading, setReportActionLoading] = useState(false);
  const [newsActionCompanyIds, setNewsActionCompanyIds] = useState([]);
  const [newsActionError, setNewsActionError] = useState(null);
  const newsActionInFlight = useRef(new Set());
  const detailsRequestId = useRef(0);



  /*
   * Load companies
   */
  useEffect(() => {
    let cancelled = false;

    async function loadCompanies() {
      try {
        setLoadingCompanies(true);
        setCompanyError(null);

        const response = await getCompanies();
        const rows = response.companies || [];
        const leads = rows.map(mapCompanyToLead);

        if (cancelled) return;

        setCompanies(leads);

        const qualifiedLeads = leads.filter(
          (lead) => lead.qualification?.qualified === true
        );

        setSuspects(
          qualifiedLeads.filter(
            (lead) => lead.sales_stage !== "prospect"
          )
        );

        setProspects(
          qualifiedLeads.filter(
            (lead) => lead.sales_stage === "prospect"
          )
        );
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to load companies:", error);
          setCompanyError(
            error.message || "Failed to load companies."
          );
        }
      } finally {
        if (!cancelled) {
          setLoadingCompanies(false);
        }
      }
    }

    loadCompanies();

    return () => {
      cancelled = true;
    };
  }, [companyReloadToken]);

  // Background ingestion survives drawer interactions and reports progress
  // through the latest Supabase run record.
  useEffect(() => {
    const companyId = selectedCompany?.id;
    if (!detailsOpen || !companyId || selectedCompany?.newsState !== "processing") {
      return undefined;
    }

    let cancelled = false;
    let timerId;
    const poll = async () => {
      try {
        const newsData = await getCompanyNews(companyId);
        if (cancelled) return;
        setSelectedCompany((current) => (
          current?.id === companyId
            ? {
              ...current,
              recentIntelligence: newsData.articles,
              newsState: newsData.state,
              newsLatestRun: newsData.latest_run,
              newsError: null,
            }
            : current
        ));
        if (newsData.state === "processing") {
          timerId = window.setTimeout(poll, 1500);
        }
      } catch (error) {
        if (cancelled) return;
        setSelectedCompany((current) => (
          current?.id === companyId
            ? { ...current, newsError: error.message || "Progress refresh failed." }
            : current
        ));
        timerId = window.setTimeout(poll, 4000);
      }
    };

    timerId = window.setTimeout(poll, 700);
    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
    };
  }, [detailsOpen, selectedCompany?.id, selectedCompany?.newsState]);

  useEffect(() => {
    const companyId = selectedCompany?.id;
    const reportId = selectedCompany?.annualReport?.id;
    if (
      !detailsOpen
      || !companyId
      || !reportId
      || selectedCompany?.annualReport?.processingStatus !== "processing"
    ) {
      return undefined;
    }

    let cancelled = false;
    let timerId;
    const poll = async () => {
      try {
        const status = await getReportProcessingStatus(reportId);
        if (cancelled) return;

        if (status.status === "processing") {
          setSelectedCompany((current) => (
            current?.id === companyId
              ? {
                ...current,
                annualReport: {
                  ...current.annualReport,
                  processingStatus: status.status,
                  latestRun: status.latest_run,
                },
              }
              : current
          ));
          timerId = window.setTimeout(poll, 5000);
          return;
        }

        const latestData = await getCompanyIntelligence(companyId);
        if (cancelled) return;
        const refreshedCompany = mapCompanyIntelligence(latestData, null);
        setSelectedCompany((current) => (
          current?.id === companyId
            ? {
              ...refreshedCompany,
              recentIntelligence: current.recentIntelligence,
              newsState: current.newsState,
              newsLatestRun: current.newsLatestRun,
              newsError: current.newsError,
            }
            : current
        ));
      } catch (error) {
        if (cancelled) return;
        console.error("Failed to refresh annual report processing status:", error);
        timerId = window.setTimeout(poll, 10000);
      }
    };

    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
    };
  }, [
    detailsOpen,
    selectedCompany?.id,
    selectedCompany?.annualReport?.id,
    selectedCompany?.annualReport?.processingStatus,
  ]);


  /*
   * Companies shown in the active
   * Suspects / Prospects tab.
   */
  const activeLeads =
    activeTab === "suspects"
      ? suspects
      : prospects;

  /*
   * Search
   */
  const filteredLeads =
    useMemo(() => {
      const query =
        search
          .toLowerCase()
          .trim();

      if (!query) {
        return activeLeads;
      }

      return activeLeads.filter(
        (lead) =>
          lead.company
            ?.toLowerCase()
            .includes(query) ||

          lead.symbol
            ?.toLowerCase()
            .includes(query) ||

          lead.industry
            ?.toLowerCase()
            .includes(query)
      );

    }, [activeLeads, search]);

  /*
   * Select company and load
   * its real intelligence.
   */
  async function loadCompanyDetails(company) {
    const requestId = ++detailsRequestId.current;
    setLoadingCompanyDetails(true);
    setCompanyDetailsError(null);
    setNewsActionError(null);
    setSelectedCompany(
      company
    );

    try {
      /*
       * Use NSE symbol.
       */
      const backendData = await getCompanyIntelligence(
        company.id || company.symbol
      );
      if (requestId !== detailsRequestId.current) return;

      /*
       * Convert backend response
       * into structure consumed by
       * CompanyDetails.
       */
      const mappedCompany =
        mapCompanyIntelligence(
          backendData,
          null
        );

      /*
       * Preserve qualification from
       * dashboard row if the detailed
       * endpoint does not contain it.
       */
      if (
        !mappedCompany.qualification
      ) {
        mappedCompany.qualification =
          company.qualification ||
          null;

        /*
         * Also preserve the financial
         * values from the dashboard row.
         */
        if (company.qualification) {
          mappedCompany.revenue =
            company.qualification.revenue ??
            null;

          mappedCompany.previousRevenue =
            company.qualification.previous_year_revenue ??
            null;

          mappedCompany.revenueGrowth =
            company.qualification.revenue_growth ??
            null;
        }
      }

      setSelectedCompany(
        mappedCompany
      );

      getCompanyNews(company.id || company.symbol).then((newsData) => {
        if (requestId !== detailsRequestId.current) return;
        setSelectedCompany((current) => (
          current?.id === mappedCompany.id
            ? {
              ...current,
              recentIntelligence: newsData.articles,
              newsState: newsData.state,
              newsLatestRun: newsData.latest_run,
              newsError: null,
            }
            : current
        ));
      }).catch((error) => {
        if (requestId !== detailsRequestId.current) return;
        setSelectedCompany((current) => (
          current?.id === mappedCompany.id
            ? {
              ...current,
              newsState: "unavailable",
              newsError: error.message || "Stored news could not be loaded.",
            }
            : current
        ));
      });

    } catch (error) {
      if (requestId !== detailsRequestId.current) return;
      console.error(
        "Failed to load company intelligence:",
        error
      );

      setCompanyDetailsError(
        error.message || "Failed to load company details."
      );

    } finally {
      if (requestId === detailsRequestId.current) {
        setLoadingCompanyDetails(false);
      }
    }
  }

  async function handleSelectCompany(company) {
    setDetailsOpen(true);
    setReportActionError(null);
    await loadCompanyDetails(company);
  }


  async function handleQualify(company) {
    setSalesStageError(null);

    try {
      const response = await updateCompanySalesStage(company.id, "prospect");

      const updatedCompany = {
        ...company,
        sales_stage: response.company?.sales_stage || "prospect",
      };
      detailsRequestId.current += 1;
      setLoadingCompanyDetails(false);

      setSuspects((current) =>
        current.filter((lead) => lead.id !== company.id)
      );

      setProspects((current) => [
        updatedCompany,
        ...current.filter((lead) => lead.id !== company.id),
      ]);

      setSelectedCompany(updatedCompany);
      setDetailsOpen(false);
    } catch (error) {
      setSalesStageError(
        error.message || "Failed to move company to Prospects."
      );
    }
  }

  async function handleRemove(company) {
    setSalesStageError(null);

    try {
      const response = await updateCompanySalesStage(company.id, "suspect");

      const updatedCompany = {
        ...company,
        sales_stage: response.company?.sales_stage || "suspect",
      };
      detailsRequestId.current += 1;
      setLoadingCompanyDetails(false);

      setProspects((current) =>
        current.filter((lead) => lead.id !== company.id)
      );

      setSuspects((current) => [
        updatedCompany,
        ...current.filter((lead) => lead.id !== company.id),
      ]);

      setSelectedCompany(updatedCompany);
      setDetailsOpen(false);
    } catch (error) {
      setSalesStageError(
        error.message || "Failed to move company to Suspects."
      );
    }
  }

  async function handleIngestReport(company) {
    setReportActionLoading(true);
    setReportActionError(null);
    try {
      await ingestCompanyAnnualReport(company.id);
      await loadCompanyDetails(company);
    } catch (error) {
      setReportActionError(error.message || "Annual report ingestion failed.");
    } finally {
      setReportActionLoading(false);
    }
  }

  async function handleProcessReport(company) {
    if (!company.annualReport?.id) return;
    setReportActionLoading(true);
    setReportActionError(null);
    try {
      await processAnnualReport(company.annualReport.id);
      await loadCompanyDetails(company);
    } catch (error) {
      setReportActionError(error.message || "Annual report processing failed.");
    } finally {
      setReportActionLoading(false);
    }
  }

  async function handleFetchCompanyNews(company) {
    if (newsActionInFlight.current.has(company.id)) return;
    newsActionInFlight.current.add(company.id);
    setNewsActionCompanyIds((current) => [...current, company.id]);
    const requestId = detailsRequestId.current;
    setNewsActionError(null);

    try {
      const response = await ingestCompanyNews(company.id, 30);
      if (requestId !== detailsRequestId.current) return;
      setSelectedCompany((current) => (
        current?.id === company.id
          ? {
            ...current,
            newsState: "processing",
            newsLatestRun: response.run || current.newsLatestRun,
            newsError: null,
          }
          : current
      ));
    } catch (error) {
      if (requestId === detailsRequestId.current) {
        setNewsActionError(error.message || "News ingestion failed.");
      }
    } finally {
      newsActionInFlight.current.delete(company.id);
      setNewsActionCompanyIds((current) => current.filter((id) => id !== company.id));
    }
  }


  /*
   * Initial loading
   */
  if (loadingCompanies) {
    return (
      <div className="flex min-h-[calc(100dvh-6rem)] items-center justify-center bg-muted/30 lg:min-h-screen">
        <div className="text-sm text-muted-foreground">
          Loading companies...
        </div>
      </div>
    );
  }

  /*
   * Initial loading error
   */
  if (companyError) {
    return (
      <div className="flex min-h-[calc(100dvh-6rem)] items-center justify-center bg-muted/30 lg:min-h-screen">
        <div className="max-w-md rounded-xl border bg-background p-6">
          <h2 className="text-lg font-semibold">
            Failed to load companies
          </h2>

          <p className="mt-2 text-sm text-muted-foreground">
            {companyError}
          </p>
          <button
            type="button"
            className="mt-4 rounded-md border px-3 py-2 text-sm"
            onClick={() => setCompanyReloadToken((value) => value + 1)}
          >
            Retry loading companies
          </button>
        </div>
      </div>
    );
  }

  /*
   * Total qualified companies.
   */
  const totalQualified =
    companies.filter(
      (company) =>
        company.qualification?.qualification_status ===
        "qualified"
    ).length;

  return (
    <div className="min-h-[calc(100dvh-6rem)] min-w-0 flex-1 lg:h-screen lg:overflow-y-auto">

      <DashboardHeader />

      <StatCards
        totalQualified={totalQualified}
        suspectCount={suspects.length}
        prospectCount={prospects.length}
      />
      {salesStageError && (
        <div
          role="alert"
          className="mx-4 mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive sm:mx-6"
        >
          {salesStageError}
        </div>
      )}
      <div className="px-4 pb-6 sm:px-6">

        <LeadTable
          leads={
            filteredLeads
          }

          search={
            search
          }

          onSearchChange={
            setSearch
          }

          activeTab={
            activeTab
          }

          onTabChange={
            setActiveTab
          }

          suspectCount={
            suspects.length
          }

          prospectCount={
            prospects.length
          }

          onSelect={
            handleSelectCompany
          }

          onQualify={
            handleQualify
          }

          onRemove={
            handleRemove
          }
        />

      </div>

      <CompanyDetails
        company={selectedCompany}
        open={detailsOpen}
        onOpenChange={setDetailsOpen}
        isProspect={selectedCompany?.sales_stage === "prospect"}
        onQualify={handleQualify}
        onRemove={handleRemove}
        loading={loadingCompanyDetails}
        error={companyDetailsError}
        reportActionError={reportActionError}
        reportActionLoading={reportActionLoading}
        onIngestReport={handleIngestReport}
        onProcessReport={handleProcessReport}
        newsActionLoading={newsActionCompanyIds.includes(selectedCompany?.id)}
        newsActionError={newsActionError}
        onFetchNews={handleFetchCompanyNews}
      />

    </div>
  );
}
