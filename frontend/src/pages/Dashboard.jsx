import { useEffect, useMemo, useRef, useState } from "react";

import DashboardHeader from "../components/layout/DashboardHeader";
import StatCards from "../components/dashboard/StatCards";
import LeadTable from "../components/dashboard/LeadTable";
import CompanyDetails from "../components/company/CompanyDetails";

import {
  getCompanies,
  getCompanyIntelligence,
  getCompanyNews,
  ingestCompanyAnnualReport,
  getAnnualReportIngestionStatus,
  getAnnualReportProcessingStatus,
  ingestCompanyNews,
  processAnnualReport,
  updateCompanySalesStage,
} from "../api/clientApi";

import {
  getAnnualReportStatus,
  isAnnualReportActive,
} from "../api/annualReportStatus";

/*
 * News states returned by the backend.
 */
function isNewsActive(state) {
  return state === "loading" || state === "processing";
}

/*
 * Convert a company from the companies API into the
 * structure currently required by LeadTable.
 */
function mapCompanyToLead(company) {
  return {
    id: company.id,
    symbol: company.symbol,
    company: company.name,
    industry: company.sector || "—",
    sales_stage: company.sales_stage || "suspect",
    qualification: company.qualification || null,
  };
}

/*
 * Convert the detailed company intelligence response.
 */
function mapCompanyIntelligence(data, newsData = null) {
  const company = data.company || {};
  const evidence = data.evidence || [];
  const reports = data.reports || [];
  const qualification = data.qualification || {};
  const processingRuns = data.processing_runs || [];

  const latestReport = reports[0] || null;

  const latestRun = latestReport
    ? processingRuns.find(
        (run) => run.annual_report_id === latestReport.id
      ) || null
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
     */
    revenue: qualification.revenue ?? null,

    previousRevenue:
      qualification.previous_year_revenue ?? null,

    revenueGrowth:
      qualification.revenue_growth ?? null,

    revenueYear:
      qualification.financial_year || null,

    /*
     * Backend financial qualification
     */
    qualification: data.qualification || null,

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
          processingStatus: latestReport.processing_status,
          processingStatusLoading: true,
          processingStatusError: null,
          job: latestReport.job || null,
          nseUrl: latestReport.nse_url,
          storagePath: latestReport.document_storage_path,
          latestRun,
        }
      : {
          available: false,
        },

    /*
     * Annual report evidence
     */
    annualEvidence: reportEvidence,

    /*
     * Persisted news articles.
     *
     * The initial state is loading because the news endpoint
     * still needs to be checked.
     */
    recentIntelligence: newsData?.articles || [],
    newsState: newsData?.state || "loading",
    newsLatestRun: newsData?.latest_run || null,
    newsError: null,

    processingRuns,

    /*
     * Complete backend response
     */
    backendData: data,
  };
}

export default function Dashboard() {
  /*
   * Real backend companies
   */
  const [companies, setCompanies] = useState([]);

  const [loadingCompanies, setLoadingCompanies] = useState(true);

  const [companyError, setCompanyError] = useState(null);

  const [companyReloadToken, setCompanyReloadToken] = useState(0);

  const [salesStageError, setSalesStageError] = useState(null);

  /*
   * Suspects / Prospects
   */
  const [suspects, setSuspects] = useState([]);

  const [prospects, setProspects] = useState([]);

  /*
   * Dashboard tab state
   */
  const [activeTab, setActiveTab] = useState("suspects");

  const [search, setSearch] = useState("");

  /*
   * Selected company
   */
  const [selectedCompany, setSelectedCompany] = useState(null);

  const [detailsOpen, setDetailsOpen] = useState(false);

  /*
   * Detailed intelligence loading state
   */
  const [loadingCompanyDetails, setLoadingCompanyDetails] =
    useState(false);

  const [companyDetailsError, setCompanyDetailsError] = useState(null);

  /*
   * Annual report actions
   */
  const [reportActionError, setReportActionError] = useState(null);

  const [reportActionLoading, setReportActionLoading] = useState(false);

  /*
   * News actions
   */
  const [newsActionCompanyIds, setNewsActionCompanyIds] = useState([]);

  const [newsActionError, setNewsActionError] = useState(null);

  const newsActionInFlight = useRef(new Set());

  /*
   * Prevent outdated company requests from updating
   * the currently selected company.
   */
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

  /*
   * NEWS POLLING
   *
   * This effect handles:
   *
   * 1. Initial news status retrieval.
   * 2. Background ingestion progress.
   * 3. Refreshing articles while processing.
   * 4. Retrying temporary API/network failures.
   *
   * It stops only when the backend returns a terminal state.
   */
  useEffect(() => {
    const companyId = selectedCompany?.id;

    const newsState = selectedCompany?.newsState;

    if (!companyId || !isNewsActive(newsState)) {
      return undefined;
    }

    let cancelled = false;

    let timerId = null;

    let inFlight = false;

    let failedAttempts = 0;

    /*
     * Schedule the next polling request.
     */
    const scheduleNextPoll = (delay) => {
      if (cancelled) return;

      if (timerId) {
        window.clearTimeout(timerId);
      }

      timerId = window.setTimeout(pollNews, delay);
    };

    /*
     * Retrieve the latest news state and articles.
     */
    const pollNews = async () => {
      if (cancelled || inFlight) return;

      inFlight = true;

      try {
        const newsData = await getCompanyNews(companyId);

        if (cancelled) return;

        failedAttempts = 0;

        /*
         * Update only the company currently being viewed.
         */
        setSelectedCompany((current) => {
          if (current?.id !== companyId) {
            return current;
          }

          return {
            ...current,

            recentIntelligence: Array.isArray(newsData.articles)
              ? newsData.articles
              : current.recentIntelligence || [],

            newsState: newsData.state,

            newsLatestRun:
              newsData.latest_run || current.newsLatestRun || null,

            newsError: null,
          };
        });

        /*
         * Continue polling only while the backend reports
         * an active state.
         *
         * Backend terminal states include:
         * not_fetched
         * failed
         * completed_with_errors
         * completed_with_articles
         * completed_empty
         */
        if (isNewsActive(newsData.state)) {
          scheduleNextPoll(1500);
        }
      } catch (error) {
        if (cancelled) return;

        failedAttempts += 1;

        console.error(
          `News status polling failed (attempt ${failedAttempts}):`,
          error
        );

        /*
         * Keep the existing state active.
         * A temporary API error must not make the UI
         * incorrectly display the empty state.
         */
        setSelectedCompany((current) => {
          if (current?.id !== companyId) {
            return current;
          }

          return {
            ...current,
            newsError:
              error.message || "Could not refresh news progress.",
          };
        });

        /*
         * Exponential retry:
         * 2 seconds, 4 seconds, 8 seconds, then 10 seconds.
         */
        const retryDelay = Math.min(
          2000 * (2 ** Math.min(failedAttempts - 1, 3)),
          10000
        );

        scheduleNextPoll(retryDelay);
      } finally {
        inFlight = false;
      }
    };

    /*
     * Start with a short delay so the company details
     * can finish rendering.
     */
    scheduleNextPoll(500);

    return () => {
      cancelled = true;

      if (timerId) {
        window.clearTimeout(timerId);
      }
    };
  }, [selectedCompany?.id, selectedCompany?.newsState]);

  /*
   * ANNUAL REPORT STATUS POLLING
   *
   * Poll the report status while the worker is active.
   * When it reaches a terminal state, fetch company intelligence
   * again so newly extracted evidence appears without reopening
   * the Company Details dialog.
   */
  useEffect(() => {
    const companyId = selectedCompany?.id;
    const reportId = selectedCompany?.annualReport?.id;

    if (!detailsOpen || !companyId || !reportId) {
      return undefined;
    }

    let cancelled = false;
    let timerId = null;
    let inFlight = false;
    let failedAttempts = 0;

    const schedule = (delay) => {
      if (!cancelled) {
        timerId = window.setTimeout(poll, delay);
      }
    };

    const refreshCompanyIntelligence = async (normalized) => {
      /*
       * The status endpoint can become terminal before the
       * details currently held by React have been refreshed.
       * Fetch the full payload, including evidence and runs.
       */
      const latestData = await getCompanyIntelligence(companyId);

      if (cancelled) return;

      setSelectedCompany((current) => {
        if (
          current?.id !== companyId ||
          current?.annualReport?.id !== reportId
        ) {
          return current;
        }

        const preservedNews = {
          articles: current.recentIntelligence || [],
          state: current.newsState || "not_fetched",
          latest_run: current.newsLatestRun || null,
        };

        const refreshed = mapCompanyIntelligence(
          latestData,
          preservedNews
        );

        return {
          ...refreshed,

          // Keep the latest news state; this refresh is for annual data.
          recentIntelligence: current.recentIntelligence || [],
          newsState: current.newsState,
          newsLatestRun: current.newsLatestRun,
          newsError: current.newsError,

          annualReport: {
            ...refreshed.annualReport,
            processingStatus: normalized.state,
            processingStatusLoading: false,
            processingStatusError: null,
            job:
              normalized.job ||
              refreshed.annualReport?.job ||
              current.annualReport?.job ||
              null,
            processingError: normalized.error || null,
          },
        };
      });
    };

    const poll = async () => {
      if (cancelled || inFlight) return;

      inFlight = true;

      try {
        const statusData =
          await getAnnualReportProcessingStatus(reportId);

        if (cancelled) return;

        const normalized = getAnnualReportStatus(statusData);
        failedAttempts = 0;

        /*
         * Update the visible status immediately.
         */
        setSelectedCompany((current) =>
          current?.annualReport?.id === reportId &&
          current.id === companyId
            ? {
                ...current,
                annualReport: {
                  ...current.annualReport,
                  processingStatus: normalized.state,
                  processingStatusLoading: false,
                  processingStatusError: null,
                  job:
                    normalized.job ||
                    current.annualReport.job ||
                    null,
                  processingError: normalized.error,
                },
              }
            : current
        );

        setReportActionError(null);

        if (isAnnualReportActive(normalized.state)) {
          schedule(5000);
        } else {
          /*
           * Terminal state: refresh the complete company payload.
           * This is the missing step that makes new evidence appear
           * immediately in the open dialog.
           */
          try {
            await refreshCompanyIntelligence(normalized);
          } catch (refreshError) {
            console.error(
              "Annual report finished, but refreshing company intelligence failed:",
              refreshError
            );

            setSelectedCompany((current) =>
              current?.id === companyId &&
              current?.annualReport?.id === reportId
                ? {
                    ...current,
                    annualReport: {
                      ...current.annualReport,
                      processingStatus: normalized.state,
                      processingStatusLoading: false,
                      processingStatusError:
                        refreshError.message ||
                        "Report finished, but the latest evidence could not be loaded. Reopen the company or try again.",
                    },
                  }
                : current
            );
          }
        }
      } catch (error) {
        if (cancelled) return;

        failedAttempts += 1;

        setSelectedCompany((current) =>
          current?.annualReport?.id === reportId &&
          current.id === companyId
            ? {
                ...current,
                annualReport: {
                  ...current.annualReport,
                  processingStatusLoading: failedAttempts < 3,
                  processingStatusError:
                    failedAttempts >= 3
                      ? error.message ||
                        "Could not refresh report status."
                      : null,
                },
              }
            : current
        );

        schedule(
          Math.min(
            1000 * (2 ** Math.min(failedAttempts - 1, 3)),
            10000
          )
        );
      } finally {
        inFlight = false;
      }
    };

    timerId = window.setTimeout(poll, 500);

    return () => {
      cancelled = true;
      if (timerId) {
        window.clearTimeout(timerId);
      }
    };
  }, [
    detailsOpen,
    selectedCompany?.id,
    selectedCompany?.annualReport?.id,
  ]);

  /*
   * Companies shown in the active tab.
   */
  const activeLeads =
    activeTab === "suspects" ? suspects : prospects;

  /*
   * Search
   */
  const filteredLeads = useMemo(() => {
    const query = search.toLowerCase().trim();

    if (!query) {
      return activeLeads;
    }

    return activeLeads.filter(
      (lead) =>
        lead.company?.toLowerCase().includes(query) ||
        lead.symbol?.toLowerCase().includes(query) ||
        lead.industry?.toLowerCase().includes(query)
    );
  }, [activeLeads, search]);

  /*
   * Select company and load its real intelligence.
   */
  async function loadCompanyDetails(company) {
    const requestId = ++detailsRequestId.current;

    setLoadingCompanyDetails(true);

    setCompanyDetailsError(null);

    setNewsActionError(null);

    setSelectedCompany(company);

    try {
      /*
       * Use the company ID for the backend lookup.
       */
      const backendData = await getCompanyIntelligence(
        company.id || company.symbol
      );

      if (requestId !== detailsRequestId.current) return;

      /*
       * Map the company intelligence response.
       *
       * News is initialized as loading. The news polling
       * effect will retrieve its actual status and articles.
       */
      const mappedCompany = mapCompanyIntelligence(
        backendData,
        null
      );

      /*
       * Preserve qualification from the dashboard row
       * if the detailed endpoint does not contain it.
       */
      if (!mappedCompany.qualification) {
        mappedCompany.qualification =
          company.qualification || null;

        if (company.qualification) {
          mappedCompany.revenue =
            company.qualification.revenue ?? null;

          mappedCompany.previousRevenue =
            company.qualification.previous_year_revenue ?? null;

          mappedCompany.revenueGrowth =
            company.qualification.revenue_growth ?? null;
        }
      }

      if (requestId !== detailsRequestId.current) return;

      setSelectedCompany(mappedCompany);

      /*
       * IMPORTANT:
       *
       * Do not call getCompanyNews() separately here.
       *
       * The NEWS POLLING effect automatically starts
       * when newsState becomes "loading".
       *
       * This avoids competing requests and ensures that
       * the same polling mechanism handles initial loading
       * and background ingestion.
       */
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

  /*
   * Qualify company.
   */
  async function handleQualify(company) {
    setSalesStageError(null);

    try {
      const response = await updateCompanySalesStage(
        company.id,
        "prospect"
      );

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

  /*
   * Remove company from prospects.
   */
  async function handleRemove(company) {
    setSalesStageError(null);

    try {
      const response = await updateCompanySalesStage(
        company.id,
        "suspect"
      );

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

  /*
   * Ingest annual report.
   *
   * Existing implementation preserved.
   */
  async function handleIngestReport(company) {
    setReportActionLoading(true);

    setReportActionError(null);

    try {
      const response = await ingestCompanyAnnualReport(company.id);

      const jobId = response.job?.id;

      if (jobId) {
        const startedAt = Date.now();

        let status = response.job?.status || "queued";

        while (
          Date.now() - startedAt < 10 * 60 * 1000 &&
          ["queued", "processing"].includes(status)
        ) {
          await new Promise((resolve) =>
            window.setTimeout(resolve, 4000)
          );

          const statusResponse =
            await getAnnualReportIngestionStatus(
              company.id,
              jobId
            );

          status = statusResponse.job?.status;

          if (status === "failed") {
            throw new Error(
              statusResponse.job.failure_reason ||
                "Annual report ingestion failed."
            );
          }

          if (status === "completed") break;
        }

        if (status !== "completed") {
          setReportActionError(
            "Annual report ingestion is still running; you can revisit this company to check its status."
          );

          return;
        }
      }

      await loadCompanyDetails(company);
    } catch (error) {
      setReportActionError(
        error.message || "Annual report ingestion failed."
      );
    } finally {
      setReportActionLoading(false);
    }
  }

  /*
   * Process annual report.
   */
  async function handleProcessReport(company) {
    if (!company.annualReport?.id) return;

    setReportActionLoading(true);

    setReportActionError(null);

    try {
      await processAnnualReport(company.annualReport.id, {
        retry: company.annualReport.processingStatus === "failed",
      });

      /*
       * Do not reload company details here: the workflow runs
       * asynchronously. The annual-report polling effect will
       * refresh the full company intelligence when it finishes.
       */
      setSelectedCompany((current) =>
        current?.id === company.id &&
        current?.annualReport?.id === company.annualReport.id
          ? {
              ...current,
              annualReport: {
                ...current.annualReport,
                processingStatus: "processing",
                processingStatusLoading: false,
                processingStatusError: null,
              },
            }
          : current
      );
    } catch (error) {
      setReportActionError(
        error.message || "Annual report processing failed."
      );
    } finally {
      setReportActionLoading(false);
    }
  }

  /*
   * Update the currently selected company's news data.
   */
  function applyCompanyNews(companyId, newsData, fallbackRun = null) {
    setSelectedCompany((current) => {
      if (current?.id !== companyId) {
        return current;
      }

      return {
        ...current,

        recentIntelligence: Array.isArray(newsData.articles)
          ? newsData.articles
          : current.recentIntelligence || [],

        newsState: newsData.state,

        newsLatestRun:
          newsData.latest_run ||
          fallbackRun ||
          current.newsLatestRun ||
          null,

        newsError: null,
      };
    });
  }

  /*
   * Fetch company news.
   *
   * The POST queues the backend worker.
   * The polling effect takes over once the run is active.
   */
  async function handleFetchCompanyNews(company) {
    const companyId = company.id;

    if (!companyId) return;

    if (newsActionInFlight.current.has(companyId)) {
      return;
    }

    newsActionInFlight.current.add(companyId);

    setNewsActionCompanyIds((current) =>
      current.includes(companyId)
        ? current
        : [...current, companyId]
    );

    const requestId = detailsRequestId.current;

    setNewsActionError(null);

    /*
     * Start the loading indicator immediately.
     * Existing articles are deliberately preserved.
     */
    setSelectedCompany((current) =>
      current?.id === companyId
        ? {
            ...current,
            newsState: "loading",
            newsError: null,
          }
        : current
    );

    try {
      const response = await ingestCompanyNews(companyId, 30);

      if (requestId !== detailsRequestId.current) return;

      /*
       * The ingestion endpoint queues a background worker.
       * Start polling immediately.
       */
      setSelectedCompany((current) =>
        current?.id === companyId
          ? {
              ...current,
              newsState: "processing",
              newsLatestRun:
                response.run || current.newsLatestRun || null,
              newsError: null,
            }
          : current
      );

      /*
       * Get the latest status immediately.
       *
       * This also handles workers that finish very quickly.
       */
      try {
        const newsData = await getCompanyNews(companyId);

        if (requestId !== detailsRequestId.current) return;

        applyCompanyNews(
          companyId,
          newsData,
          response.run || null
        );
      } catch (error) {
        /*
         * The polling effect will retry this request.
         * Do not mark ingestion as failed because of
         * a temporary status-fetch error.
         */
        console.warn(
          "Initial news refresh failed; polling will retry:",
          error
        );
      }
    } catch (ingestionError) {
      if (requestId !== detailsRequestId.current) return;

      /*
       * An existing processing run may cause the backend
       * to reject a duplicate ingestion request.
       *
       * Check the current backend state before displaying
       * an error. If a run is already processing, join it.
       */
      try {
        const newsData = await getCompanyNews(companyId);

        if (requestId !== detailsRequestId.current) return;

        if (isNewsActive(newsData.state)) {
          applyCompanyNews(companyId, newsData);

          setNewsActionError(null);

          return;
        }

        /*
         * The backend has returned a terminal state.
         * Update the UI with its actual state and articles.
         */
        applyCompanyNews(companyId, newsData);

        /*
         * If the original POST failed and no active ingestion
         * exists, report the original error.
         */
        if (
          newsData.state === "not_fetched" ||
          newsData.state === "failed"
        ) {
          setNewsActionError(
            ingestionError.message || "News ingestion failed."
          );
        }
      } catch (statusError) {
        console.error(
          "Could not verify news ingestion status:",
          statusError
        );

        setNewsActionError(
          ingestionError.message || "News ingestion failed."
        );
      }
    } finally {
      newsActionInFlight.current.delete(companyId);

      setNewsActionCompanyIds((current) =>
        current.filter((id) => id !== companyId)
      );
    }
  }

  /*
   * Initial loading
   */
  if (loadingCompanies) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/30">
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
      <div className="flex min-h-screen items-center justify-center bg-muted/30">
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
            onClick={() =>
              setCompanyReloadToken((value) => value + 1)
            }
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
  const totalQualified = companies.filter(
    (company) =>
      company.qualification?.qualification_status === "qualified"
  ).length;

  return (
    <div className="h-screen min-w-0 flex-1 overflow-y-auto">
      <DashboardHeader />

      <StatCards
        totalQualified={totalQualified}
        suspectCount={suspects.length}
        prospectCount={prospects.length}
      />

      {salesStageError && (
        <div
          role="alert"
          className="mx-6 mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
        >
          {salesStageError}
        </div>
      )}

      <div className="px-6 pb-6">
        <LeadTable
          leads={filteredLeads}
          search={search}
          onSearchChange={setSearch}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          suspectCount={suspects.length}
          prospectCount={prospects.length}
          onSelect={handleSelectCompany}
          onQualify={handleQualify}
          onRemove={handleRemove}
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
        newsActionLoading={newsActionCompanyIds.includes(
          selectedCompany?.id
        )}
        newsActionError={newsActionError}
        onFetchNews={handleFetchCompanyNews}
      />
    </div>
  );
}
