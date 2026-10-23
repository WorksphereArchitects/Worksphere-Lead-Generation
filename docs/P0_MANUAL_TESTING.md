# WorkSphere P0 manual testing guide

This guide covers the current Flask/Supabase API and React/Vite dashboard. Use a development Supabase project and do not delete company, report, run, or evidence rows to prepare a test.

## Configuration

Set these backend environment variables in `backend/.env` or the process environment. Do not commit the file.

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY` (needed only for report processing)
- `DATABASE_URL` (optional for Flask-SQLAlchemy migrations; the company intelligence data is read from Supabase)
- `GEMINI_MODEL` (optional; defaults to `gemini-3.8-flash`)
- `GEMINI_FALLBACK_MODEL` (optional; defaults to `gemini-3.5-flash-lite`)
- `GEMINI_MAX_INPUT_TOKENS` (optional; defaults to `64000`)
- `GEMINI_CONTEXT_TOKEN_BUDGET` (optional; defaults to `48000`)
- `GEMINI_MAX_OUTPUT_TOKENS` (optional; defaults to `16384`)
- `GEMINI_INPUT_TOKENS_PER_MINUTE` (optional; defaults to `250000`)
- `GEMINI_MAX_CANDIDATES` (optional; defaults to `350`)
- `GEMINI_MAX_PASSAGE_CHARS` (optional; defaults to `6000`)

`VITE_API_BASE_URL` is optional for the frontend. In development, Vite proxies `/api` to `http://127.0.0.1:5000`.

Annual-report discovery uses the NSE endpoint and local PDF storage. Google Drive OAuth uses `backend/credentials.json` and `backend/token.json` only when Drive upload is enabled in the ingestion path; do not copy or print their contents.

## Start the application

In PowerShell, from the repository root, start the backend in one terminal:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python -m flask run
```

The README's clean setup, if no virtual environment exists, is:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m flask run
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`). The API base is normally `http://127.0.0.1:5000/api`.

## Confirm the database schema

The checked-in Flask migrations define the older SQLAlchemy evidence foundation; they do not define the Supabase `companies`, `annual_reports`, `processing_runs`, or production `evidence` tables. No new migration is required by the changes in this task. Check the Supabase project schema before testing:

```sql
select column_name, column_default, is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'companies'
  and column_name = 'sales_stage';

select constraint_name, check_clause
from information_schema.check_constraints
where constraint_schema = 'public'
  and constraint_name ilike '%sales_stage%';
```

The application expects `companies.sales_stage` to default to `suspect` and accept only `suspect` or `prospect`. The report workflow expects the existing `annual_reports`, `processing_runs`, and `evidence` tables and their columns as selected by the API. If a required Supabase column is missing, apply the project owner's Supabase migration for that schema before running these steps; this repository contains no authoritative production schema migration to apply.

## Verify dashboard and sales-stage persistence

1. Open the dashboard. Company loading should end in the company list, or show a visible error with **Retry loading companies**.
2. Confirm the Suspects and Prospects counts contain only financially qualified companies; the sales stage remains independent of financial qualification.
3. Open a suspect company. The detail panel should show a loading state, then the same persisted stage as the dashboard row.
4. Click **Qualify as Prospect**. The company should move once to Prospects after the API confirms the update.
5. Refresh the page and confirm it remains in Prospects. Move it back using **Remove from Prospects**, refresh, and confirm it returns to Suspects.
6. Invalid stage values should return HTTP `400`; a valid but unknown UUID should return `404`; a database error should return `500` without changing the UI stage.

The exact sales-stage API request is:

```powershell
$companyId = '<company UUID from GET /api/companies>'
Invoke-RestMethod -Method Patch `
  -Uri "http://127.0.0.1:5000/api/companies/$companyId/sales-stage" `
  -ContentType 'application/json' `
  -Body '{"sales_stage":"prospect"}'
```

Expect HTTP `200` with `company.id` and `company.sales_stage = "prospect"`. Repeat with `suspect` to move it back.

List companies and their persisted stage:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/companies'
```

The response has `count`, `companies[]`, and `qualification`; each company includes `id`, `symbol`, `name`, `sales_stage`, and `qualification`. An empty `companies` array with HTTP `200` means there are no target companies. An HTTP error means the list request failed.

## Verify company details and report states

Open the company drawer and confirm its company name, NSE symbol, industry, persisted stage, qualification, report state, evidence, and processing attempt belong to the selected company. Selecting another company quickly should not allow an earlier response to replace its details.

The details API accepts either the UUID or NSE symbol:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/company-intelligence/360ONE'
```

Expect `company`, `qualification`, `summary`, `reports[]`, `evidence[]`, and `processing_runs[]`. A missing company returns HTTP `404`; a Supabase failure returns HTTP `500` and does not become an empty success.

In the annual-report panel, verify these states:

- No report row: **No annual report record is available** and **Find latest NSE report**.
- `pending`: report available but not processed, with **Process report**.
- `processing` or latest run `running`: processing message; no duplicate process action.
- `failed` or latest run `failed`: failure message and **Retry processing**; any earlier evidence remains visible as earlier stored data.
- `completed` with evidence: completion message and evidence list; unresolved sources are counted separately.
- `completed` with no evidence for that report: **Processing completed; no evidence was found**.
- Empty News Intelligence: explicitly says the feature is not available in this app version and does not claim that no real-world news exists.

## Ingest and process the 360ONE annual report

First revalidate the company, report, and local file; do not assume a previous report ID or overwrite a PDF:

```sql
select id, symbol, name, sales_stage
from public.companies
where upper(symbol) = '360ONE';

select id, company_id, financial_year, processing_status,
       report_title, local_file_path, page_count, processed_at
from public.annual_reports
where company_id = '<360ONE company UUID>'
order by financial_year desc;
```

NSE `toYr` is stored as the ending year (for example, `2026` for a report whose filename contains `2025_2026`). The UI displays the stored value and does not reinterpret that year as a new fiscal-year range.

If there is no report row, use the company UUID from the first query:

```powershell
$companyId = '<360ONE company UUID>'
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:5000/api/reports/companies/$companyId/ingest"
```

The response is HTTP `200` and includes the existing/upserted `report.id`, `financial_year`, `report_title`, `nse_url`, `page_count`, and actual `processing_status` (normally `pending`). Repeating ingestion uses the existing company/year identity and preserves an existing processing status.

Process the exact returned report ID:

```powershell
$reportId = '<report UUID returned by ingestion or selected from Supabase>'
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:5000/api/reports/$reportId/process"
```

On success expect `success = true`, a report with `processing_status = "completed"`, a completed `processing_run`, signals and retrieval statistics. A concurrent request returns HTTP `409`; a missing report returns `404`; exhausted processing failures return `500` with a sanitized error. Retry only after the current attempt has settled and the report is `failed` or otherwise retryable. Reprocessing a completed report is supported and report/source-candidate evidence duplicates are skipped.

The company drawer provides these same ingest, process, and retry actions. It refreshes the company detail after a successful operation and shows an API error instead of a success state when the request fails.

## Verify persisted report, run, and evidence rows

Use read-only Supabase SQL Editor checks:

```sql
select id, company_id, financial_year, processing_status,
       report_title, nse_url, page_count, processed_at
from public.annual_reports
where id = '<report UUID>';

select id, annual_report_id, status, model_attempted, model_used,
       candidate_count, signal_count, resolved_signal_count,
       unresolved_signal_count, error_message, started_at, completed_at
from public.processing_runs
where annual_report_id = '<report UUID>'
order by created_at desc;

select id, source_id, source_type, financial_year, evidence_type,
       headline, source_resolution_status, source_candidate_ids,
       is_current, created_at
from public.evidence
where source_type = 'annual_report'
  and source_id = '<report UUID>'
order by created_at desc;
```

For the previous 360ONE attempt, re-check the reported ID `2f8de323-ecf0-4adf-b7d8-ba92367c28c3` against these queries. Use it only if it still belongs to 360ONE. The prior local PDF name was `AR_30295_360ONE_2025_2026_A_13329916_11082026184412.pdf`; confirm the `local_file_path` exists before processing. Do not run ingestion or processing across all companies.

## Check failure handling without damaging data

- A malformed sales-stage body should return `400`; an unknown report ID should return `404`; an already-processing report should return `409`.
- To check UI/network errors, stop the backend, attempt company loading, and confirm the page shows an error plus retry rather than an empty company list. Restart the backend and retry.
- Do not remove or rename the stored PDF to force a failure. For an actual Gemini failure, inspect the latest failed `processing_runs` row and `annual_reports.processing_status`; both should show failure, and the original evidence rows should still be present.
- A failed database status update must not replace the original server-side processing exception. Client responses intentionally omit stack traces and credentials.
