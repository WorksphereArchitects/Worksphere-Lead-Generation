# News Intelligence Manual Test Guide

This guide covers the single-company Google News RSS → Groq classification → Supabase → Flask API → React drawer flow. The application does not download or scrape publisher article bodies; it uses only Google News RSS titles, descriptions, links, publisher labels, and publication timestamps when supplied.

## Prerequisites

The backend needs these environment variable names in `backend/.env`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (server-side only; never put this in a Vite variable)
- `GROQ_API_KEY`
- `GROQ_MODEL` (optional)

The Groq and Gemini credentials previously exposed in a command output should be revoked and replaced before any live provider test. Restart Flask after updating environment values.

## Apply the Supabase migration

The production Supabase schema is not managed by the older SQLAlchemy/Alembic migrations under `backend/migrations`. The read-only schema check found no existing `news_articles` or `news_ingestion_runs` tables. Apply the new migration exactly once:

1. Open the Supabase project’s **SQL Editor**.
2. Open [`supabase/migrations/20261012000000_news_intelligence.sql`](../supabase/migrations/20261012000000_news_intelligence.sql) locally.
3. Paste and run the complete SQL in the SQL Editor.
4. Confirm `news_articles` and `news_ingestion_runs` appear under the public schema.

The migration creates company-scoped article uniqueness on `(company_id, normalized_url)` and a partial unique index that prevents two `processing` runs for the same company. Articles and their zero-or-more validated event objects are stored in `news_articles.events` JSONB; run counts and status are stored in `news_ingestion_runs`. RLS is enabled without public policies; the Flask server uses the service-role key.

## Start the app

Terminal 1, from the repository root:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python app.py
```

Terminal 2, from the repository root:

```powershell
cd frontend
npm run dev
```

Open the Vite URL printed in Terminal 2 (normally `http://localhost:5173`). In development, Vite proxies `/api` to Flask at `http://127.0.0.1:5000`.

## API verification for one existing company

Choose a company already listed by `GET /api/companies`. Use its UUID from the returned `id` field:

```powershell
$companyId = '<existing company UUID>'
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/company-intelligence/$companyId/news"
```

Before the first fetch, expect `state = not_fetched`, `articles = []`, and `latest_run = null`.

Trigger ingestion for one company and a bounded 30-day lookback:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:5000/api/company-intelligence/$companyId/news/ingest?days=30"
```

The API returns HTTP 202 with a processing run immediately. Poll the news GET endpoint until the run status is no longer `processing`; its `metadata.progress` reports the current stage and article counts. Each run is capped at ten RSS candidates, Groq classifies up to five new articles per request, and completed prior classifications are reused. A second simultaneous run for that company should return HTTP 409. A lookback outside 1–90 days should return HTTP 400; an unknown company should return HTTP 404.

Fetch the stored results again:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/company-intelligence/$companyId/news?limit=50"
```

Possible states include `not_fetched`, `processing`, `failed`, `completed_with_errors`, `completed_empty`, and `completed_with_articles`. An empty result refers only to the searched RSS sources and time window.

## Verify persistence and idempotency

In the Supabase SQL Editor, substitute the same UUID and check the run history:

```sql
select id, company_id, status, lookback_days,
       discovered_count, accepted_count, rejected_count,
       duplicate_count, failed_count, failure_reason,
       started_at, completed_at
from public.news_ingestion_runs
where company_id = '<existing company UUID>'
order by started_at desc;
```

Check accepted article provenance and events:

```sql
select id, company_id, source_url, normalized_url, title,
       publisher, published_at, relevance_status,
       processing_status, events, last_seen_at
from public.news_articles
where company_id = '<existing company UUID>'
order by published_at desc nulls last;
```

Run the same ingestion again. The article row count for the company should not increase for URLs already stored, and prior classifications should be reused without another Groq call. Existing rows are not rewritten merely to record a repeat discovery. The unique constraint is scoped to company, so two companies can store the same publisher URL independently.

## Frontend checks

In the company drawer:

1. Before ingestion, verify the panel says news has not been fetched and offers **Fetch latest news**.
2. Click once. The API should return quickly; the button stays in its loading state while the background job runs, and the panel reports discovery/classification progress.
3. Verify returned headlines use actual RSS titles, publisher/date only when provided, and links open the stored source URL.
4. Any event must show its category, factual description, and an excerpt copied from that article’s RSS title or summary. No WorkSphere buying intent is inferred.
5. If the fetch completes empty, confirm the panel says no relevant articles were found in the searched sources/window and does not claim that no company news exists.
6. If a refresh fails, confirm any previously stored articles remain visible with an error message.
7. Switch companies while a request is pending; the old response must not replace the newly selected company’s news.
8. An article without an extracted event should still render as relevant news with the “no source-backed business event” explanation.

## Automated checks

Run the focused offline backend tests (they mock Groq, RSS, and Supabase):

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest discover -s tests -p 'test_news_intelligence.py'
.\venv\Scripts\python.exe -m unittest discover -s tests -p 'test_p0_reliability.py'
```

Then run the configured frontend build and lint. The repo’s legacy lint may report existing issues in untouched UI components; report those separately from changed-file lint.

Live one-company ingestion is intentionally separate from offline tests. It contacts Google News and Groq and writes Supabase rows; run it only after credential rotation, migration application, and approval for the live provider/database operation.
