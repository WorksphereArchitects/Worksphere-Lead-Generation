# WorkSphere Project Status

Practical handoff status based on the repository as inspected on 10 October 2026. This document is an update of the earlier project-flow report; the broader product vision is retained, but the current primary flow is now represented accurately.

## Current primary flow

```text
COMPANIES
    ↓
FINANCIAL DATA / QUALIFICATION
    ↓
QUALIFIED COMPANIES
    ↓
ANNUAL REPORT PIPELINE
    ↓
ANNUAL REPORT STORED / REFERENCED IN GOOGLE DRIVE
    ↓
ANNUAL REPORT INGESTION / PROCESSING
    ↓
EVIDENCE EXTRACTION + PROVENANCE / DEDUPLICATION
    ↓
EVIDENCE / ANNUAL REPORT INTELLIGENCE
    ↓
annual_reports TABLE + evidence TABLE
    ↓
COMPANY INTELLIGENCE API
    ↓
FRONTEND COMPANY DETAILS / ANNUAL INTELLIGENCE
```

Annual reports are downstream of financial qualification. They are not the initial company-discovery mechanism.

## Company and qualification flow

The `companies` table is the starting company universe. `GET /api/companies` reads target companies from Supabase and joins their persisted financial records. The key relationship is:

```text
companies.id = company_financials.company_id
```

`company_financials.qualification_status` is the source of truth. The supported statuses are:

- `qualified`
- `not_qualified`
- `insufficient_data`

The backend does not recalculate qualification in `GET /api/companies`. It returns persisted financial values, thresholds, source information, and status. Companies without a financial record are represented as `insufficient_data`.

The frontend does not recalculate qualification and does not rerun yfinance. `QualifiedCompanies.jsx` calls `getCompanies()` and filters `qualification_status === "qualified"`. `NotQualifiedCompanies.jsx` filters `qualification_status === "not_qualified"`. Therefore insufficient-data companies do not appear in either dedicated page.

## Annual-report flow

The intended downstream flow is:

```text
Qualified company
    ↓
Find/fetch annual report
    ↓
Store local report and optionally upload/reference it in Google Drive
    ↓
Create/update annual_reports metadata
    ↓
Extract report text
    ↓
Run evidence/financial processing
    ↓
Persist evidence and processing status
    ↓
Expose through company intelligence
    ↓
Render Annual Intelligence in the frontend
```

Relevant files:

- `backend/applications/services/annual_report_ingestion.py`: completed background annual-report discovery/download, PDF text extraction, Google Drive authentication/upload, and report-ingestion orchestration.
- `backend/applications/services/annual_reports.py`: Supabase CRUD/upsert/status helpers for `annual_reports`. The upsert uses `company_id + financial_year` as the conflict key.
- `backend/applications/services/gemini_engine.py`: report retrieval/context construction and Gemini processing; it updates report processing state and creates intelligence/evidence through the supporting services.
- `backend/tests/gemini_poc.py`: a POC/reference path for the same annual-report ingestion and evidence-processing components; the production background flow is implemented in the application services.
- `backend/applications/models/document.py`: generic web/document storage model used by the source/document/evidence foundation.
- `backend/applications/models/evidence.py`: ORM model for evidence linked to documents; this is not an annual-report model.
- `backend/applications/services/evidence_extractor.py`: deterministic text normalization, sentence/chunk retrieval, candidate classification/scoring, deduplication, excerpts, locations, and rich evidence construction.
- `backend/applications/services/evidence_service.py`: creates and retrieves persisted evidence rows.

Google Drive is the reference/document-storage layer for annual reports. The report also retains `local_file_path` and `nse_url`. The Drive file reference stored by the service is `google_drive_file_id`, and the company-intelligence serializer exposes it. The completed background workflow handles the upload/reference; the frontend consumes the resulting annual-report intelligence data.

## `annual_reports` database layer

The repository queries `annual_reports` through Supabase but does not include its table DDL/model in the checked-in SQLAlchemy models or Alembic migrations. The following schema is therefore the actual application contract visible in `annual_reports.py`, `annual_report_ingestion.py`, and `company_intelligence.py`; any additional database columns cannot be established from this repository.

| Field/contract | Meaning |
|---|---|
| `id` | Primary report identifier used by processing route/service. |
| `company_id` | Relationship to `companies.id`. |
| `financial_year` | Report year; used with `company_id` for upsert conflict handling. |
| `report_title` | Report title/filename metadata. |
| `nse_url` | Source/reference URL for the NSE report. |
| `local_file_path` | Local downloaded report path. |
| `google_drive_file_id` | Google Drive file reference when upload is performed. |
| `page_count` | Report page-count metadata returned by company intelligence. |
| `processing_status` | Processing lifecycle value, including pending/processing/completed/failed paths. |
| `processed_at` | Processing completion timestamp returned by the API. |
| `created_at`, `updated_at` | Timestamps returned/used by the API/service. |

No extracted evidence/intelligence payload is shown as a column in the application contract. Evidence is stored separately in `evidence` and linked through document/report processing context rather than embedded directly in `annual_reports`. The company-intelligence endpoint separately loads annual reports and evidence.

## Database tables

These tables are verified from Supabase `.table(...)` usage, ORM models, or migrations. A Python filename alone was not treated as proof of a table.

| Table | Purpose | Important Relationships | Used By | Status |
|---|---|---|---|---|
| `companies` | Company identity, symbol, sector, target flag, classification. | `id → company_financials.company_id`; `id → annual_reports.company_id`; company intelligence/evidence queries. | `companies_routes.py`, `companies.py`, `company_intelligence.py`, `gemini_engine.py` | Implemented/read |
| `company_financials` | Financial metrics and persisted qualification result. | `company_id → companies.id`; may reference `annual_report_id`. | `companies_routes.py`, `financial_service.py`, `qualification_service.py`, seed scripts. | Implemented/read |
| `annual_reports` | Annual-report metadata and processing lifecycle. | `company_id → companies.id`; upsert uniqueness contract is company/year; `google_drive_file_id` references Drive externally. | `annual_reports.py`, `annual_report_ingestion.py`, `company_intelligence.py`, `gemini_engine.py`. | Implemented/read; DDL not checked in |
| `sources` | Registered source records for generic document ingestion. | `sources.id → documents.source_id`. | `source.py`, `sources.py`, document route/service. | Implemented ORM + migration |
| `documents` | Retrieved source documents, metadata, raw text/hash. | `source_id → sources.id`; `documents.id → evidence.document_id`. | `document.py`, documents routes, evidence extraction. | Implemented ORM + migration |
| `evidence` | Extracted, validated, provenance-bearing evidence. | `document_id → documents.id`; production Supabase queries also use `company_id`, report/year, and current status fields. | `evidence.py`, evidence routes/service, company intelligence. | Implemented ORM/migration + Supabase usage |
| `processing_runs` | Processing history/status for company report work. | `company_id` is used to query company runs; exact FK/DDL is not checked in here. | `processing_runs.py`, `company_intelligence.py`, Gemini POC/engine. | Service/query contract; database DDL not verified |

Actual relationship shape:

```text
companies
├── company_financials
│   └── qualification_status
└── annual_reports
    ├── local_file_path / nse_url / google_drive_file_id
    └── processing status

annual report processing
└── evidence
    └── document → source provenance chain where a document record is used
```

## Evidence extraction and persistence

The generic evidence pipeline is:

```text
Source
  ↓ POST /api/sources
Document fetch/storage
  ↓ POST /api/documents
Evidence extraction
  ↓ POST /api/documents/<id>/extract-evidence
Evidence provenance/deduplication
  ↓ POST /api/documents/<id>/validate-evidence
Evidence retrieval
```

`evidence_extractor.py` performs deterministic candidate generation, classification, semantic/linguistic scoring, deduplication, excerpt construction, location hints, and rich signal fields. `evidence_service.py` persists batches and retrieves company/evidence records. `evidence.py` defines the ORM fields and document relationship. Evidence uniqueness and provenance persistence are present.

For annual reports, `gemini_engine.py` adds report-context retrieval and model-assisted structured extraction around the existing extraction/storage services. This runs as part of the completed background annual-report workflow and has the expected external credential/quota dependencies.

## Separate news pipeline

News discovery is separate from the annual-report pipeline:

```text
News / external sources
    ↓
discovery.py
    ↓
discovery_relevance.py
    ↓
company-scoped validation + event extraction
    ↓
news_articles + news_ingestion_runs (Supabase)
    ↓
company news API
    ↓
RecentIntelligence.jsx
```

The company-level news integration discovers from Google News RSS, classifies new articles with Groq in batches, reuses stored classifications for repeat discoveries, validates source excerpts, normalizes tracking URLs, and upserts by `(company_id, normalized_url)`. Ingestion runs in a Flask background worker; the company drawer polls run progress and updates as results arrive. News tables are Supabase-managed through `supabase/migrations/20261012000000_news_intelligence.sql`; they are separate from the legacy SQLAlchemy migrations. `RecentIntelligence.jsx` renders persisted articles and fetch/empty/error/progress states. Apply the migration and rotate the exposed provider credentials before attempting the live integration run; see `docs/NEWS_INTELLIGENCE_MANUAL_TESTING.md`.

## Frontend status

### Currently implemented

- `frontend/src/App.jsx`: routes `/dashboard`, `/qualified`, `/not-qualified`, and `/settings`; `/` redirects to `/dashboard`.
- `frontend/src/pages/Dashboard.jsx`: loads companies, maps company-intelligence responses, supports search/filtering, and opens company details.
- `frontend/src/pages/QualifiedCompanies.jsx`: API-backed table, persisted qualification filtering, count card, company/symbol/sector/current revenue/prior revenue/growth/source columns, search, right-side search icon, controlled table widths, and Tailwind/shadcn-style UI.
- `frontend/src/pages/NotQualifiedCompanies.jsx`: equivalent API-backed not-qualified table/search flow.
- `frontend/src/components/layout/Sidebar.jsx`: fixed desktop sidebar (`h-screen`, `w-64`, `shrink-0`), Dashboard, Qualified Companies, Not Qualified Companies, Settings, Help & Support, and Sales Team / Lead Manager. NavLinks explicitly use `text-foreground`/`no-underline`, preventing unwanted blue link styling. Main content is laid out beside the sidebar in `App.jsx`.
- `frontend/src/api/clientApi.js`: wrappers for companies, company intelligence, report processing, documents, and evidence retrieval/extraction endpoints.
- `CompanyDetails.jsx`, `CompanyOverview.jsx`, `AnnualIntelligence.jsx`, and `RecentIntelligence.jsx`: UI components for company summary, annual evidence, and recent intelligence.

### Annual-report intelligence wiring

`Dashboard.jsx` calls `getCompanyIntelligence()` and maps returned reports/evidence into `annualReport` and `annualEvidence`. `AnnualIntelligence.jsx` renders the report year and evidence fields such as headline, event state, type, summary, why-it-matters, investment, scale, timeline, location, consequence, and excerpt. `CompanyDetails.jsx` displays evidence counts and the Annual Intelligence component.

This is connected for read/display when a company is selected. Report acquisition, Drive reference, PDF processing, evidence extraction, and persistence occur in the completed background pipeline; the frontend displays the resulting annual-report intelligence. `RecentIntelligence.jsx` now loads persisted news and exposes a single-company fetch/refresh action. Settings is only a static heading. `frontend/src/data/mockLeads.js` remains transitional mock lead data.

## Current frontend flow

```text
Dashboard ──connected──> Company list
Company list ──connected──> persisted qualification data
Qualified page ──connected──> qualified company table
Qualified company ──connected──> getCompanyIntelligence()
Company details ──connected──> annual reports/evidence returned by API
Annual Intelligence ──connected for display──> mapped annual evidence
Annual report acquisition/processing ──not connected──> frontend controls
News discovery/relevance ──connected──> Supabase news tables ──connected──> Recent Intelligence data
```

## API status

| Method | Endpoint | Purpose | Implemented | Frontend connected |
|---|---|---|---|---|
| POST | `/api/sources` | Create source record. | Yes | No |
| GET | `/api/companies` | Target companies plus persisted financial qualification/counts. | Yes; paginates Supabase reads. | Yes |
| GET | `/api/company-intelligence/<identifier>` | Company, reports, current evidence, financial summary, processing runs. | Yes | Yes, Dashboard |
| GET | `/api/company-intelligence/<identifier>/news` | Stored relevant news and latest ingestion state. | Yes | Yes, company drawer |
| POST | `/api/company-intelligence/<identifier>/news/ingest?days=30` | Discover, classify, extract, and upsert news for one company. | Yes | Yes, company drawer |
| POST | `/api/reports/<report_id>/process` | Process an annual report through `process_annual_report`; the background workflow also invokes the processing services. | Yes | Client wrapper exists; results are consumed through Company Intelligence |
| POST | `/api/documents` | Fetch and persist a document. | Yes | Client wrapper absent |
| GET | `/api/documents` | List documents. | Yes | Client wrapper exists; no visible page |
| GET | `/api/documents/<document_id>` | Retrieve one document. | Yes | No |
| POST | `/api/documents/<document_id>/extract-evidence` | Extract/store evidence for a document. | Yes | Client wrapper exists; no visible page |
| POST | `/api/documents/<document_id>/validate-evidence` | Validate document evidence. | Yes | Client wrapper exists; no visible page |
| GET | `/api/documents/<document_id>/evidence` | Retrieve document evidence, optionally filtered by status. | Yes | Client wrapper exists; no visible page |
| GET | `/api/evidences` | List persisted evidence. | Yes | Client path appears inconsistent: `clientApi.js` calls `/evidence` singular |
| GET | `/api/evidences/<evidence_id>` | Retrieve one evidence row. | Yes | No |

The pluralization mismatch between the backend blueprint (`/api/evidences`) and frontend `getEvidence()` (`/evidence`) should be verified before using that client function.

## Completed

- Company universe and persisted qualification architecture are implemented.
- `companies.id = company_financials.company_id` is the active company/financial relationship used by the API.
- `GET /api/companies` returns qualification status and counts.
- Qualified and Not Qualified pages are API-backed and use persisted status filtering.
- Qualified table includes the verified company, symbol, sector, current-year revenue, previous-year revenue, growth, source, count card, search, search icon, controlled widths, and Tailwind/shadcn UI.
- Complete background annual-report workflow: discovery/fetch, storage, Google Drive reference, PDF processing, evidence extraction, and persistence.
- Evidence extraction, provenance, deduplication, and evidence APIs exist.
- Company intelligence API exists and the Dashboard reads it.
- Annual Intelligence data flow is complete: processed annual-report evidence reaches the Company Intelligence API and is rendered by the Annual Intelligence frontend.
- Company-level news pipeline is implemented offline: Google News RSS discovery, Groq relevance/event output validation, URL deduplication, Supabase schema/API integration, and drawer rendering.

## Partially Completed

- Dashboard still uses transitional suspects/prospects terminology and mock lead structures alongside real company intelligence data.

## Frontend Implemented but Backend Flow Incomplete

- Prospect/suspect actions are UI actions over the dashboard view; no confirmed persisted opportunity/lead workflow is present.
- Settings route is present without settings functionality.

## Not Yet Implemented

- Opportunity scoring/prioritization.
- Decision-maker intelligence and contact/relationship workflows.
- Competitive intelligence.
- Production-grade auth/authorization, observability, retries, and deployment controls.

## Needs Verification

- Exact live DDL for Supabase-managed `companies`, `company_financials`, `annual_reports`, and `processing_runs`; their application contracts are visible, but their DDL is not included in the checked-in migrations.
- Whether the current `/api/evidences` versus frontend `/api/evidence` mismatch is exercised anywhere.
- Runtime/API behavior against the configured database and external providers. No expensive pipelines were run for this report.

## Remaining work

### P0 — Required for the current visible product

1. Apply the Supabase news migration, rotate the exposed provider credentials, then complete an approved one-company live ingestion and repeat-ingestion check.
2. Resolve the evidence endpoint pluralization mismatch if the client function is retained.

### P1 — Important

1. Add live-schema verification for Supabase-managed tables and document the exact constraints/foreign keys.
2. Add persistent suspects/prospects/opportunity workflow.

### P2 — Future product capabilities

Signals, project/opportunity inference, opportunity scoring, decision-maker intelligence, competitive intelligence, outreach/CRM, lead conversion, and broader lead-management workflows remain future product vision. They should not be confused with the current qualification → annual-report → evidence flow.

## Do Not Redo

- Supabase 1,000-row pagination in `companies_routes.py`.
- The `companies` / `company_financials` relationship and persisted qualification-status architecture.
- Qualified Companies API/UI.
- Not Qualified Companies API/UI.
- Existing evidence extraction, provenance, and deduplication infrastructure.
- Existing annual-report discovery/storage/processing services.
- Existing company-intelligence API.
- Existing news discovery/relevance backend code.

## Where To Continue

Start with the current core dependency chain:

1. Complete the one-company news integration after migration and credential rotation, then review operational limits before expanding.
2. Add persistent suspects/prospects/opportunity workflow.
3. Continue with broader signal, project, opportunity, decision-maker, competitive, outreach, and lead functionality.

Do not rerun yfinance or recalculate qualification from the frontend; the current architecture intentionally uses persisted `company_financials.qualification_status`.
