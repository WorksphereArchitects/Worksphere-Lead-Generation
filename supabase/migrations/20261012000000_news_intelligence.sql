-- News tables are managed by Supabase, separate from the legacy SQLAlchemy
-- sources/documents/evidence migrations under backend/migrations.

create table if not exists public.news_ingestion_runs (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references public.companies(id) on delete cascade,
    status text not null check (status in (
        'processing', 'completed', 'completed_with_errors', 'failed'
    )),
    lookback_days integer not null check (lookback_days between 1 and 90),
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    discovered_count integer not null default 0 check (discovered_count >= 0),
    accepted_count integer not null default 0 check (accepted_count >= 0),
    rejected_count integer not null default 0 check (rejected_count >= 0),
    duplicate_count integer not null default 0 check (duplicate_count >= 0),
    failed_count integer not null default 0 check (failed_count >= 0),
    classification_failed_count integer not null default 0 check (classification_failed_count >= 0),
    persistence_failed_count integer not null default 0 check (persistence_failed_count >= 0),
    malformed_count integer not null default 0 check (malformed_count >= 0),
    truncated_count integer not null default 0 check (truncated_count >= 0),
    failure_reason text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists ix_news_ingestion_runs_company_started
    on public.news_ingestion_runs (company_id, started_at desc);

-- The partial unique index acts as an atomic, cross-process per-company lock.
create unique index if not exists ux_news_ingestion_runs_one_processing_per_company
    on public.news_ingestion_runs (company_id)
    where status = 'processing';

create table if not exists public.news_articles (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references public.companies(id) on delete cascade,
    latest_run_id uuid references public.news_ingestion_runs(id) on delete set null,
    normalized_url text not null,
    source_url text not null,
    title text not null,
    publisher text,
    publisher_url text,
    published_at timestamptz,
    rss_description text,
    relevance_status text not null check (relevance_status in (
        'accepted', 'rejected'
    )),
    relevance jsonb not null,
    processing_status text not null check (processing_status in (
        'not_relevant', 'events_extracted', 'no_supported_event'
    )),
    events jsonb not null default '[]'::jsonb,
    discovery_metadata jsonb not null default '{}'::jsonb,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_news_articles_company_normalized_url
        unique (company_id, normalized_url)
);

create index if not exists ix_news_articles_company_published
    on public.news_articles (company_id, published_at desc);
create index if not exists ix_news_articles_company_relevance
    on public.news_articles (company_id, relevance_status, last_seen_at desc);

-- The Flask API accesses these tables with the server-only Supabase service key.
-- No public/anonymous policies are created.
alter table public.news_ingestion_runs enable row level security;
alter table public.news_articles enable row level security;
